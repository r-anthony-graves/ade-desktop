"""Every /v1 call the panel makes, off the UI thread.

Results come back as QUEUED signals to this long-lived QObject. No Qt object
is created, parented or destroyed on a worker thread -- the piece-1 lesson
(a PySide access violation when the collector tore a window down mid
cross-thread signal). Signals carry `object`, not `dict`: a `dict` signal is
marshalled through Qt's variant map across threads, which is free to
reshape what it carries.
"""

from __future__ import annotations

import itertools
import threading
from concurrent.futures import ThreadPoolExecutor, wait

from PySide6.QtCore import QObject, Signal

from ade_desktop.ade_status import ade_base
from ade_desktop.net import get_json, post_file, post_json, stream_lines

TOPIC = "u/local/desktop"
SESSION = "ade-desktop"
# The avatar's per-route timeouts (adeos/avatar/main.js ADE_CALL_TIMEOUT_MS):
# Ade turns take minutes by architecture. The streamed shell has none.
TIMEOUTS = {"ask": 2700, "chat": 2700, "task": 1200, "shell": 300,
            "default": 120}


class ConversationClient(QObject):
    done = Signal(str, object)    # request id, result dict
    line = Signal(str, str)       # request id, one NDJSON line

    def __init__(self, base=None, *, post=post_json, get=get_json,
                 upload=post_file, stream=stream_lines, parent=None) -> None:
        super().__init__(parent)
        self.base = (base or ade_base()).rstrip("/")
        self._post, self._get = post, get
        self._upload, self._stream = upload, stream
        self._pool = ThreadPoolExecutor(max_workers=4,
                                        thread_name_prefix="ade-conv")
        self._ids = itertools.count(1)
        self._futures: set = set()
        self._stop_stream = threading.Event()
        self._stopped = False

    # -- plumbing -----------------------------------------------------------

    def _submit(self, fn) -> str:
        rid = f"r{next(self._ids)}"
        if self._stopped:
            return rid

        def work():
            try:
                result = fn(rid)
            except Exception as exc:  # noqa: BLE001 -- a failure is a result
                result = {"error": f"{type(exc).__name__}: {exc}"}
            if not isinstance(result, dict):
                result = {"error": "non-dict reply"}
            self.done.emit(rid, result)

        future = self._pool.submit(work)
        self._futures.add(future)
        future.add_done_callback(self._futures.discard)
        return rid

    def _post_to(self, path, body, kind="default"):
        url, timeout = self.base + path, TIMEOUTS[kind]
        return lambda rid: self._post(url, body, timeout)

    # -- the routes ---------------------------------------------------------

    def ask(self, question, skills, history) -> str:
        return self._submit(self._post_to("/v1/ask", {
            "question": question, "skills": list(skills),
            "history": list(history)}, "ask"))

    def chat(self, text) -> str:
        return self._submit(self._post_to("/v1/chat/completions", {
            "messages": [{"role": "user", "content": text}],
            "stream": False}, "chat"))

    def task(self, text, task_type, skills) -> str:
        return self._submit(self._post_to("/v1/tasks", {
            "description": text, "task_type": task_type, "topic": TOPIC,
            "skills": list(skills)}, "task"))

    def shell(self, cmd) -> str:
        return self._submit(self._post_to("/v1/terminal", {"cmd": cmd},
                                          "shell"))

    def run(self, cmd) -> str:
        """The streamed shell: one `line` signal per NDJSON frame, then
        `done`. No timeout -- Stop is the way out."""
        self._stop_stream.clear()
        url, body = self.base + "/v1/terminal/run", {"session": SESSION,
                                                     "cmd": cmd}
        stop = self._stop_stream.is_set

        def go(rid):
            return self._stream(url, body,
                                lambda text: self.line.emit(rid, text), stop)
        return self._submit(go)

    def stop_stream(self) -> None:
        self._stop_stream.set()

    def kill(self) -> str:
        """Stop reading the stream AND drop the session's PowerShell, so the
        command itself ends (the next run respawns the session)."""
        self._stop_stream.set()
        return self._submit(self._post_to("/v1/terminal/kill",
                                          {"session": SESSION}))

    def health(self) -> str:
        url = self.base + "/v1/health"
        return self._submit(lambda rid: self._get(url, 5.0))

    def skills(self) -> str:
        url = self.base + "/v1/skills"
        return self._submit(lambda rid: self._get(url, 10.0))

    def task_types(self) -> str:
        url = self.base + "/v1/task-types"
        return self._submit(lambda rid: self._get(url, 10.0))

    def decide(self, approval_id, allow) -> str:
        verb = "allowed" if allow else "denied"
        return self._submit(self._post_to(
            f"/v1/approvals/{approval_id}/decide",
            {"allow": bool(allow), "reason": f"{verb} from the desktop app",
             "decided_by": "human"}))

    def upload(self, files, overwrite) -> str:
        url = self.base + "/v1/upload"
        files = list(files)

        def go(rid):
            sent, bytes_, failed = 0, 0, []
            for f in files:
                r = self._upload(url, f.full, {
                    "relpath": f.rel,
                    "overwrite": "true" if overwrite else "false"},
                    TIMEOUTS["default"])
                if "error" in r:
                    err = r["error"]
                    why = (err.get("message") or err.get("code") or str(err)
                           if isinstance(err, dict) else str(err))
                    failed.append([f.rel, why])
                else:
                    sent += 1
                    bytes_ += f.size
            return {"sent": sent, "bytes": bytes_, "failed": failed}
        return self._submit(go)

    def stop(self) -> None:
        """Cancel queued work; wait at most 2 s for work in flight. A long
        ask is abandoned, not waited for -- Ade OS keeps going server-side,
        and the panel's quit note says so."""
        self._stopped = True
        self._stop_stream.set()
        self._pool.shutdown(wait=False, cancel_futures=True)
        wait(list(self._futures), timeout=2.0)
