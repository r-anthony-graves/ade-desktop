"""Every /v1 call the panel makes, off the UI thread.

Results come back as QUEUED signals to this long-lived QObject. No Qt object
is created, parented or destroyed on a worker thread -- the piece-1 lesson
(a PySide access violation when the collector tore a window down mid
cross-thread signal). Signals carry `object`, not `dict`: a `dict` signal is
marshalled through Qt's variant map across threads, which is free to
reshape what it carries.

Workers are DAEMON threads holding only a WEAK reference to the client
(review findings, 2026-09-18):
- a ThreadPoolExecutor's workers are joined at interpreter exit, so quitting
  mid-ask kept the process alive until the ask ended -- up to 45 minutes,
  forever for a silent stream (measured: 20.7 s for a 20 s call);
- a worker holding `self` became the client's last owner when the panel let
  go, and the QObject was destroyed ON THE WORKER THREAD.
A worker whose client is gone simply drops its result.
"""

from __future__ import annotations

import itertools
import threading
import time
import weakref

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
        self._ids = itertools.count(1)
        self._threads: set[threading.Thread] = set()
        self._lock = threading.Lock()
        self._stop_stream = threading.Event()
        self._stopped = threading.Event()

    # -- plumbing -----------------------------------------------------------

    def _submit(self, fn) -> str:
        """Run fn(rid) on a daemon thread. fn must not capture `self`: every
        route below binds what it needs (the transport callable, the URL)
        before it is handed over."""
        rid = f"r{next(self._ids)}"
        if self._stopped.is_set():
            return rid
        wself = weakref.ref(self)
        threads, lock, stopped = self._threads, self._lock, self._stopped

        def work():
            try:
                result = fn(rid)
            except Exception as exc:  # noqa: BLE001 -- a failure is a result
                result = {"error": f"{type(exc).__name__}: {exc}"}
            if not isinstance(result, dict):
                result = {"error": "non-dict reply"}
            try:
                if not stopped.is_set():
                    me = wself()
                    if me is not None:
                        me.done.emit(rid, result)
                        del me
            finally:
                with lock:
                    threads.discard(threading.current_thread())

        thread = threading.Thread(target=work, name=f"ade-conv-{rid}",
                                  daemon=True)
        with lock:
            threads.add(thread)
        thread.start()
        return rid

    def _post_to(self, path, body, kind="default"):
        post, url, timeout = self._post, self.base + path, TIMEOUTS[kind]
        return lambda rid: post(url, body, timeout)

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
        stop, stream, wself = self._stop_stream.is_set, self._stream, weakref.ref(self)

        def go(rid):
            def on_line(text):
                me = wself()
                if me is not None:
                    me.line.emit(rid, text)
            return stream(url, body, on_line, stop)
        return self._submit(go)

    def stop_stream(self) -> None:
        self._stop_stream.set()

    def kill(self) -> str:
        """Stop reading the stream AND drop the session's PowerShell, so the
        command itself ends (the next run respawns the session)."""
        self._stop_stream.set()
        return self._submit(self._post_to("/v1/terminal/kill",
                                          {"session": SESSION}))

    def _get_from(self, path, timeout):
        get, url = self._get, self.base + path
        return lambda rid: get(url, timeout)

    def health(self) -> str:
        return self._submit(self._get_from("/v1/health", 5.0))

    def skills(self) -> str:
        return self._submit(self._get_from("/v1/skills", 10.0))

    def task_types(self) -> str:
        return self._submit(self._get_from("/v1/task-types", 10.0))

    def decide(self, approval_id, allow) -> str:
        verb = "allowed" if allow else "denied"
        return self._submit(self._post_to(
            f"/v1/approvals/{approval_id}/decide",
            {"allow": bool(allow), "reason": f"{verb} from the desktop app",
             "decided_by": "human"}))

    def upload(self, files, overwrite) -> str:
        url, upload = self.base + "/v1/upload", self._upload
        files = list(files)

        def go(rid):
            sent, bytes_, failed = 0, 0, []
            for f in files:
                r = upload(url, f.full, {
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
        """No new calls, no more results; wait at most 2 s in total for work
        in flight. A long ask is abandoned, not waited for -- Ade OS keeps
        going server-side, and the panel's quit note says so. The daemon
        threads never hold the process open at exit."""
        self._stopped.set()
        self._stop_stream.set()
        deadline = time.monotonic() + 2.0
        with self._lock:
            running = list(self._threads)
        for thread in running:
            thread.join(max(0.0, deadline - time.monotonic()))
