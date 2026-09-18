"""The Code terminal: one command at a time in Ade OS's PowerShell session
"ade-desktop-code", streamed.

Lines are put on the screen in batches every 50 ms, and the screen keeps
the last 10,000: a command printing 100k lines must not freeze the window.
Stop KILLS the session (the only stop that stops the command, not just
the reading of it); Run stays off until Ade OS says the kill is done, so
the next command cannot meet the old one's 409.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit, QPushButton,
                               QVBoxLayout, QWidget)

from ade_desktop.conversation.replies import error_cause
from ade_desktop.sections.code.client import SESSION
from ade_desktop.sections.code.model import History, parse_frame, strip_ansi

MAX_LINES = 10_000
FLUSH_MS = 50
READY_NOTE = (f"Commands run in Ade OS's PowerShell (session {SESSION}); cd and variables "
              "carry over between commands, until the session sits idle for 30 minutes "
              "(Ade OS then ends it). Up and Down recall earlier ones.")
STOPPED_NOTE = ("Stopped. The next command starts a fresh PowerShell in Ade OS's folder.")
BUSY_NOTE = "Ade OS is still ending the last command. Try again in a moment, or Stop."


class CommandLine(QLineEdit):
    """Up/Down walk the history; Enter runs (QLineEdit's returnPressed)."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.history = History()

    def keyPressEvent(self, event) -> None:  # noqa: N802 -- Qt's name
        if event.key() == Qt.Key.Key_Up:
            self.setText(self.history.prev(self.text()))
        elif event.key() == Qt.Key.Key_Down:
            self.setText(self.history.next(self.text()))
        else:
            super().keyPressEvent(event)


class TerminalPane(QWidget):
    running_changed = Signal(bool)

    def __init__(self, client, parent=None) -> None:
        super().__init__(parent)
        self.client = client
        self._run_rid: str | None = None
        self._kill_rid: str | None = None
        self._saw_exit = False
        self._saw_frame = False
        self._stuck = False             # a kill failed, or the session answered busy
        self._buffer: list[str] = []

        box = QVBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        self.output = QPlainTextEdit()
        self.output.setReadOnly(True)
        self.output.setMaximumBlockCount(MAX_LINES)
        self.output.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.output.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        box.addWidget(self.output, 1)
        row = QHBoxLayout()
        self.command = CommandLine()
        self.command.setPlaceholderText("A PowerShell command")
        self.command.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        self.run_button = QPushButton("Run")
        self.stop_button = QPushButton("Stop")
        self.clear_button = QPushButton("Clear")
        for b in (self.run_button, self.stop_button, self.clear_button):
            b.setAutoDefault(False)
        row.addWidget(self.command, 1)
        row.addWidget(self.run_button)
        row.addWidget(self.stop_button)
        row.addWidget(self.clear_button)
        box.addLayout(row)
        self.note = QLabel(READY_NOTE)
        self.note.setTextFormat(Qt.TextFormat.PlainText)
        self.note.setWordWrap(True)
        self.note.setStyleSheet("color:#9aa1ab;")
        box.addWidget(self.note)

        self._flush_timer = QTimer(self)
        self._flush_timer.setSingleShot(True)
        self._flush_timer.setInterval(FLUSH_MS)
        self._flush_timer.timeout.connect(self.flush)

        self.command.returnPressed.connect(self.run)
        self.run_button.clicked.connect(self.run)
        self.stop_button.clicked.connect(self.stop)
        self.clear_button.clicked.connect(self.output.clear)
        self.client.line.connect(self._on_line)
        self.client.done.connect(self._on_done)
        self._sync()

    # -- state ------------------------------------------------------------------

    def is_running(self) -> bool:
        return self._run_rid is not None

    def may_be_running(self) -> bool:
        """Running, being stopped, or lost track of: anything Ade OS may
        still be executing that only a kill from here could end."""
        return self._run_rid is not None or self._kill_rid is not None or self._stuck

    def _sync(self) -> None:
        self.run_button.setEnabled(self._run_rid is None and self._kill_rid is None)
        # Stop stays usable while something may still be running in Ade OS
        # that nothing else here could end.
        self.stop_button.setEnabled(self._kill_rid is None
                                    and (self._run_rid is not None or self._stuck))

    def _put(self, text: str) -> None:
        self._buffer.append(text)
        if len(self._buffer) > MAX_LINES:
            del self._buffer[:-MAX_LINES]       # the screen keeps no more anyway
        if not self._flush_timer.isActive():
            self._flush_timer.start()

    def flush(self) -> None:
        self._flush_timer.stop()
        if self._buffer:
            text, self._buffer = "\n".join(self._buffer), []
            self.output.appendPlainText(text)
            self.output.verticalScrollBar().setValue(self.output.verticalScrollBar().maximum())

    def _end(self) -> None:
        self._run_rid = None
        self.flush()
        self._sync()
        self.running_changed.emit(False)

    # -- actions ----------------------------------------------------------------

    def run(self) -> None:
        cmd = self.command.text().strip()
        if not cmd:
            return
        if self._run_rid is not None or self._kill_rid is not None:
            self.note.setText("One command at a time: Stop the running one first."
                              if self._run_rid else BUSY_NOTE)
            return
        self.command.history.add(cmd)
        self.command.clear()
        self._saw_exit = self._saw_frame = self._stuck = False
        self._put(f"PS> {cmd}")
        self.flush()
        self.note.setText(READY_NOTE)
        self._run_rid = self.client.run(cmd)
        self._sync()
        self.running_changed.emit(True)

    def stop(self) -> None:
        if self._kill_rid is not None or (self._run_rid is None and not self._stuck):
            return
        self._stuck = False
        self._kill_rid = self.client.kill()
        self.note.setText("Stopping…")
        if self._run_rid is not None:
            self._put("[stopped]")
            self._end()
        else:
            self._sync()

    def stop_now(self) -> None:
        """At quit: anything that may still be running is killed before the
        app goes, since nothing here could stop it afterwards."""
        if self.may_be_running():
            self._run_rid = self._kill_rid = None
            self._stuck = False
            self.client.kill_now()

    # -- answers ----------------------------------------------------------------

    def _on_line(self, rid: str, batch: str) -> None:
        """One batch of NDJSON lines (the client joins them with newlines;
        a JSON frame never holds a raw one)."""
        if rid != self._run_rid:
            return                      # a stopped run's late output
        self._saw_frame = True
        for line in batch.split("\n"):
            kind, value = parse_frame(line)
            if kind == "out":
                self._put(strip_ansi(value))
            elif kind == "exit":
                self._saw_exit = True
                self._put(f"[exit {value}]")
            elif kind == "error":
                self._put(f"[error] {strip_ansi(value)}")
            else:
                self._put(strip_ansi(value))

    def _on_done(self, rid: str, result) -> None:
        if rid == self._kill_rid:
            self._kill_rid = None
            if isinstance(result, dict) and "error" not in result:
                self.note.setText(STOPPED_NOTE)
            else:
                self._stuck = True
                self.note.setText(f"Could not stop it: {error_cause(result)}. "
                                  "The command may still be running in Ade OS; Stop tries again.")
            self._sync()
            return
        if rid != self._run_rid:
            return
        if isinstance(result, dict) and result.get("status") == 409:
            self._put("[not run: the session is busy]")
            self._stuck = True
            self.note.setText(BUSY_NOTE)
        elif not isinstance(result, dict) or "error" in result:
            # Output already came back: the command ran, and it is the
            # connection that went -- the command may still be running.
            if self._saw_frame:
                self._stuck = True      # it may still be running: Stop, and quit, can end it
                self._put(f"[connection lost: {error_cause(result)}; it may still be running]")
                self.note.setText("The connection to Ade OS was lost mid-command. Stop "
                                  "ends the command if it is still running.")
            else:
                self._put(f"[not run: {error_cause(result)}]")
        elif not self._saw_exit:
            self._put("[the stream ended without an exit code]")
        self._end()
