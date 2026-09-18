"""Polls GET /v1/approvals (pending) every 2 s, INDEPENDENT of the busy
gate: a /v1/tasks call blocks while its own approval waits, so that approval
has to reach Ray while the turn is still in flight.

A poll that fails changes nothing. An unreachable Ade OS is not evidence that
anything was decided, so no card is ever marked "answered elsewhere" because
the network blinked.

Each poll runs on a DAEMON thread holding only a weak reference to the
watcher, and stop() waits at most 2 s (review findings, 2026-09-18: a
ThreadPoolExecutor stop waited the whole request timeout on a hung Ade OS,
and a worker could outlive -- and so destroy -- the watcher off the UI
thread).
"""

from __future__ import annotations

import threading
import weakref

from PySide6.QtCore import QObject, QTimer, Signal

from ade_desktop.ade_status import ade_base
from ade_desktop.net import get_json


class ApprovalWatcher(QObject):
    appeared = Signal(object)    # the approval dict, once per new id
    vanished = Signal(str)       # an id that is no longer pending
    _polled = Signal(object)

    def __init__(self, base=None, *, get=get_json, interval_ms=2000,
                 parent=None) -> None:
        super().__init__(parent)
        self.base = (base or ade_base()).rstrip("/")
        self._get = get
        self._lock = threading.Lock()
        self._inflight: threading.Thread | None = None
        self._stopped = threading.Event()
        self._pending: dict[str, dict] = {}
        self._timer = QTimer(self)
        self._timer.setInterval(interval_ms)
        self._timer.timeout.connect(self.poll_now)
        self._polled.connect(self._apply)

    def start(self) -> None:
        self._timer.start()
        self.poll_now()

    def stop(self) -> None:
        self._stopped.set()
        self._timer.stop()
        with self._lock:
            running = self._inflight
        if running is not None:
            running.join(2.0)

    def poll_now(self) -> None:
        with self._lock:
            if self._stopped.is_set() or self._inflight is not None:
                return
            get, url = self._get, self.base + "/v1/approvals"
            wself, lock, stopped = weakref.ref(self), self._lock, self._stopped

            def work():
                try:
                    body = get(url, 4.0)
                except Exception as exc:  # noqa: BLE001
                    body = {"error": str(exc)}
                me = wself()
                if me is not None:
                    with lock:
                        me._inflight = None
                    if not stopped.is_set():
                        me._polled.emit(body)
                    del me

            self._inflight = threading.Thread(target=work, name="ade-approvals",
                                              daemon=True)
            self._inflight.start()

    def _apply(self, body) -> None:
        if self._stopped.is_set():
            return
        if not isinstance(body, dict) or "error" in body \
                or not isinstance(body.get("approvals"), list):
            return
        now = {}
        for a in body["approvals"]:
            if isinstance(a, dict) and a.get("id") and not a.get("decided"):
                now[str(a["id"])] = a
        for aid in [k for k in self._pending if k not in now]:
            del self._pending[aid]
            self.vanished.emit(aid)
        for aid, a in now.items():
            if aid not in self._pending:
                self._pending[aid] = a
                self.appeared.emit(dict(a))
