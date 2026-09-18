"""Code's calls to Ade OS that are not file reads and writes (those are the
shared FilesClient's): the checker, and the terminal.

The terminal has its OWN session token. The General chat's `!command` runs
on "ade-desktop"; sharing it would make each pane 409 the other, and a `cd`
in one would move the other.

The terminal's lines are BATCHED on the worker: `line` carries every NDJSON
line gathered in the last 50 ms (or 1,000 of them), joined by newlines.
One cross-thread signal per line saturated the UI thread at ~23k lines/s
and starved the pane's own flush -- 1.35 s freezes, measured by the
piece-7 review.
"""

from __future__ import annotations

import threading
from urllib.parse import urlencode

from ade_desktop.ade_status import ade_base
from ade_desktop.asyncclient import AsyncClient
from ade_desktop.net import get_json, request_json, stream_lines

SESSION = "ade-desktop-code"
# The checker may take a cold start (60 s) plus a request (10 s), and
# Ade OS respawns it once on a timeout: 140 s before it gives up itself.
TIMEOUTS = {"diagnostics": 150.0, "kill": 15.0}
BATCH_S = 0.05
BATCH_LINES = 1000


class _Batcher:
    """Lines from a stream, handed on in batches from a worker thread. The
    lock is held across the emit, so batches leave in the order their lines
    came -- from the reading thread (a full batch) or the ticker (a timed
    one) alike. Holds no QObject: `emit` is call_lines' relay closure."""

    def __init__(self, emit) -> None:
        self._emit = emit
        self._lines: list[str] = []
        self._lock = threading.Lock()
        self._closed = threading.Event()
        self._ticker = threading.Thread(target=self._tick, name="ade-code-batch", daemon=True)
        self._ticker.start()

    def add(self, line: str) -> None:
        with self._lock:
            self._lines.append(line)
            if len(self._lines) >= BATCH_LINES:
                self._flush_locked()

    def _flush_locked(self) -> None:
        if self._lines:
            lines, self._lines = self._lines, []
            self._emit("\n".join(lines))

    def _tick(self) -> None:
        while not self._closed.wait(BATCH_S):
            with self._lock:
                self._flush_locked()

    def close(self) -> None:
        """Everything gathered is handed on before this returns -- and so
        before the stream's result, which follows it."""
        self._closed.set()
        self._ticker.join(2.0)
        with self._lock:
            self._flush_locked()


class CodeClient(AsyncClient):
    def __init__(self, base=None, *, get=get_json, request=request_json, stream=stream_lines,
                 parent=None) -> None:
        super().__init__(parent)
        self.base = (base or ade_base()).rstrip("/")
        self._get, self._request, self._stream = get, request, stream
        self._reading = threading.Event()        # set: the current stream stops reading

    def diagnostics(self, path: str) -> str:
        get, url = self._get, self.base + "/v1/lsp/diagnostics?" + urlencode({"file": path})
        return self.call(lambda: get(url, TIMEOUTS["diagnostics"]))

    def run(self, cmd: str) -> str:
        """One command, streamed: `line` signals carrying batches of NDJSON
        frames, then `done`. No read timeout (a long build must not die
        silently); Stop is the way out."""
        self._reading = stop = threading.Event()
        stream, url = self._stream, self.base + "/v1/terminal/run"
        body = {"session": SESSION, "cmd": cmd}

        def work(emit):
            batcher = _Batcher(emit)
            try:
                return stream(url, body, batcher.add, stop.is_set)
            finally:
                batcher.close()
        return self.call_lines(work)

    def kill(self) -> str:
        """Stop reading AND drop the session's PowerShell, so the command
        itself ends; the next run starts a fresh one."""
        self._reading.set()
        request, url = self._request, self.base + "/v1/terminal/kill"
        return self.call(lambda: request("POST", url, {"session": SESSION},
                                         TIMEOUTS["kill"]))

    def kill_now(self, timeout: float = 2.0) -> dict:
        """The same, on the calling thread, bounded: for quitting, when no
        worker would outlive the process to send it."""
        self._reading.set()
        return self._request("POST", self.base + "/v1/terminal/kill", {"session": SESSION},
                             timeout)
