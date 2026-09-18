"""One Ade Desktop per user. A second launch says "show" to the first and
exits, so `run-desktop.ps1` on a running app means "bring it forward".

A named local socket (a named pipe on Windows) rather than a lock file: a
crashed app leaves a lock file behind and the next launch refuses to start.
"""

from __future__ import annotations

import os

from PySide6.QtCore import QObject, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket


def instance_name() -> str:
    user = os.environ.get("USERNAME") or os.environ.get("USER") or "user"
    return f"ade-desktop-{user}"


class SingleInstance(QObject):
    show_requested = Signal()

    def __init__(self, name: str | None = None, parent=None) -> None:
        super().__init__(parent)
        self.name = name or instance_name()
        self._server: QLocalServer | None = None

    def notify_running(self, timeout_ms: int = 1000) -> bool:
        """True if another instance answered and was told to show itself."""
        sock = QLocalSocket()
        sock.connectToServer(self.name)
        if not sock.waitForConnected(timeout_ms):
            return False
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
        while self._server is not None and self._server.hasPendingConnections():
            conn = self._server.nextPendingConnection()
            conn.readyRead.connect(lambda c=conn: self._read(c))
            conn.disconnected.connect(conn.deleteLater)
            if conn.bytesAvailable():
                self._read(conn)

    def _read(self, conn: QLocalSocket) -> None:
        if b"show" in bytes(conn.readAll()):
            self.show_requested.emit()
