"""One way to call Ade OS off the UI thread, for the sections after piece 2.

    rid = client.call(fn)      fn() runs on a daemon thread; its dict result
                               arrives as client.done(rid, result) on the UI
                               thread. fn must not capture the client.
    rid = client.call_lines(fn)
                               fn(emit) likewise; each emit(text) arrives as
                               client.line(rid, text), in order, before done.

The piece-2 workers promote their weak reference to a strong one to emit
(`me = wself(); me.done.emit(...); del me`), so for an instant the WORKER
can hold the last reference -- and a QObject freed there is freed on the
wrong thread. Here the worker never holds the client at all: it emits on
one immortal relay created on the UI thread, carrying only a weakref, and
the relay's slot -- on the UI thread -- resolves it and emits `done`.
"""

from __future__ import annotations

import itertools
import threading
import weakref

from PySide6.QtCore import QObject, Signal


class _Relay(QObject):
    carry = Signal(object, str, object)   # weakref to the client, rid, result
    carry_line = Signal(object, str, str)  # weakref to the client, rid, one line

    def __init__(self) -> None:
        super().__init__()
        self.carry.connect(self._deliver)
        self.carry_line.connect(self._deliver_line)

    def _deliver_line(self, ref, rid, text) -> None:
        client = ref()
        if client is not None and not client._stopped.is_set():
            client.line.emit(rid, text)

    def _deliver(self, ref, rid, result) -> None:
        client = ref()
        if client is not None and not client._stopped.is_set():
            client.done.emit(rid, result)


_RELAY: _Relay | None = None


def _relay() -> _Relay:
    """Created by the first client, which is built on the UI thread; kept
    for the life of the process so no worker can ever be its last owner."""
    global _RELAY
    if _RELAY is None:
        _RELAY = _Relay()
    return _RELAY


class AsyncClient(QObject):
    done = Signal(str, object)    # request id, result dict
    line = Signal(str, str)       # request id, one streamed line (call_lines)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._ids = itertools.count(1)
        self._stopped = threading.Event()
        self._relay = _relay()
        self._prefix = type(self).__name__.lower()

    def call(self, fn) -> str:
        return self._start(lambda emit: fn())

    def call_lines(self, fn) -> str:
        """fn(emit) on a daemon thread; emit(text) -> line(rid, text) on the
        UI thread. Lines and the result travel through the one relay, so
        they arrive in the order they were emitted, the result last."""
        return self._start(fn)

    def _start(self, fn) -> str:
        rid = f"{self._prefix}-{next(self._ids)}"
        if self._stopped.is_set():
            return rid
        ref, relay, stopped = weakref.ref(self), self._relay, self._stopped

        def emit(text) -> None:
            if not stopped.is_set():
                relay.carry_line.emit(ref, rid, str(text))

        def work():
            try:
                result = fn(emit)
            except Exception as exc:  # noqa: BLE001 -- a failure is a result
                result = {"error": f"{type(exc).__name__}: {exc}"}
            if not isinstance(result, dict):
                result = {"error": "non-dict reply"}
            if not stopped.is_set():
                relay.carry.emit(ref, rid, result)

        threading.Thread(target=work, name=f"ade-{rid}", daemon=True).start()
        return rid

    def stop(self) -> None:
        """No result is delivered after this."""
        self._stopped.set()
