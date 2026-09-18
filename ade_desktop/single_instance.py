"""One Ade Desktop per user. A second launch says "show" to the first and
exits, so `run-desktop.ps1` on a running app means "bring it forward".

Two parts, because neither is enough alone:

- a named local socket (a named pipe on Windows) carries "show" to the
  running app;
- a QLockFile decides who IS the running app. On Windows a second
  QLocalServer.listen() on a held name succeeds (measured in review,
  2026-09-17), so two launches that both miss notify_running() would both
  run. The lock never goes stale by age -- only when the process holding it
  is gone -- so a crash does not lock the next launch out.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from PySide6.QtCore import QLockFile, QObject, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket


def _let_the_running_app_come_forward() -> None:
    """Windows refuses SetForegroundWindow to a process that is not in the
    foreground -- the running app would only flash its taskbar button. The
    launch the user just clicked IS in the foreground, and may hand that
    right on before it says "show". Best effort; no-op elsewhere."""
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ASFW_ANY = -1
        ctypes.windll.user32.AllowSetForegroundWindow(ASFW_ANY)
    except Exception:  # noqa: BLE001 -- flashing is the worst case
        pass


def instance_name() -> str:
    user = os.environ.get("USERNAME") or os.environ.get("USER") or "user"
    return f"ade-desktop-{user}"


class SingleInstance(QObject):
    show_requested = Signal()

    def __init__(self, name: str | None = None, parent=None) -> None:
        super().__init__(parent)
        self.name = name or instance_name()
        self._server: QLocalServer | None = None
        self._lock: QLockFile | None = None

    def acquire(self, lock_dir: Path) -> bool:
        """True if this launch is THE instance. Held until release() or
        process exit."""
        Path(lock_dir).mkdir(parents=True, exist_ok=True)
        lock = QLockFile(str(Path(lock_dir) / f"{self.name}.lock"))
        # 0 = never stale by AGE. With Qt's default (30 s) a lock held by a
        # long-running app would be judged stale and taken by the next
        # launch; with 0 only a dead owner makes it stale.
        lock.setStaleLockTime(0)
        if not lock.tryLock(0):
            return False
        self._lock = lock
        return True

    def release(self) -> None:
        if self._lock is not None:
            self._lock.unlock()
            self._lock = None

    def notify_running(self, timeout_ms: int = 1000) -> bool:
        """True if another instance answered and was told to show itself."""
        sock = QLocalSocket()
        sock.connectToServer(self.name)
        if not sock.waitForConnected(timeout_ms):
            return False
        _let_the_running_app_come_forward()
        sock.write(b"show\n")
        sock.flush()
        sock.waitForBytesWritten(timeout_ms)
        sock.disconnectFromServer()
        if sock.state() != QLocalSocket.LocalSocketState.UnconnectedState:
            sock.waitForDisconnected(timeout_ms)
        return True

    def listen(self) -> bool:
        # On Unix this clears a socket file left by a crash. On Windows
        # named pipes leave nothing behind and this does nothing.
        QLocalServer.removeServer(self.name)
        self._server = QLocalServer(self)
        self._server.newConnection.connect(self._on_connection)
        return self._server.listen(self.name)

    def close(self) -> None:
        if self._server is not None:
            self._server.close()

    def _on_connection(self) -> None:
        # NO lambda capturing the socket and self (found 2026-09-18 by a
        # full-suite abort): the connection held them both, so the socket's
        # own deleteLater dropped the LAST reference to this object -- whose
        # server then deleted that same socket, mid-destruction, a second
        # time. A connection to our own method captures nothing.
        while self._server is not None and self._server.hasPendingConnections():
            conn = self._server.nextPendingConnection()
            conn.readyRead.connect(self._on_ready_read)
            conn.disconnected.connect(conn.deleteLater)
            if conn.bytesAvailable():
                self._read(conn)

    def _on_ready_read(self) -> None:
        conn = self.sender()
        if isinstance(conn, QLocalSocket):
            self._read(conn)

    def _read(self, conn: QLocalSocket) -> None:
        if b"show" in bytes(conn.readAll()):
            self.show_requested.emit()
