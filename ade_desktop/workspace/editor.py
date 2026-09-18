"""The one file editor: PM artifacts now, QA sections and Code later.

    open(path)   GET /v1/file?source=disk. The editor is read-only until the
                 file is here, and stays read-only -- with the reason shown --
                 when the answer is the QVM index copy, too large, not a text
                 type, or missing.
    save()       re-reads the file first and REFUSES if the disk changed
                 since it was opened (Ade OS has no version check: the last
                 writer wins, and Ade writes into these folders), then
                 PUT /v1/file. A failed save keeps the text.
    revert()     reads it again.

The server writes LF, so CRLF is not a difference. Unsaved edits are never
dropped without asking.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFontDatabase, QKeySequence, QShortcut
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QMessageBox, QPlainTextEdit,
                               QPushButton, QVBoxLayout, QWidget)

from ade_desktop.conversation.replies import error_cause

CACHED_NOTE = ("This is Ade's index copy, not the file on disk, so editing is off: "
               "saving it would overwrite the file with a fragment. Ade OS serves "
               "the disk copy after its next restart.")
CHANGED_NOTE = ("{path} changed on disk since you opened it, so nothing was saved. "
                "Your text is still here; Revert loads the new version.")


def _norm(text: str) -> str:
    return (text or "").replace("\r\n", "\n")


def _why_not(result) -> str:
    status = result.get("status") if isinstance(result, dict) else None
    reasons = {404: "There is no file at this path.",
               413: "Too large to open here.",
               415: "Not a text type Ade OS will serve.",
               403: "Outside the workspace."}
    return reasons.get(status) or f"Could not open it: {error_cause(result)}."


class FileEditor(QWidget):
    saved = Signal(str)
    closed = Signal()
    loaded = Signal(str, bool)      # path, whether its text arrived (False: missing / refused)

    def __init__(self, files, *, confirm=None, parent=None) -> None:
        super().__init__(parent)
        self.files = files
        self._confirm = confirm
        self.path: str | None = None
        self.baseline: str | None = None
        self.readonly_reason = ""
        self._pending: dict[str, tuple] = {}

        box = QVBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        row = QHBoxLayout()
        self.title = QLabel("")
        self.title.setStyleSheet("font-family: monospace;")
        self.save_button = QPushButton("Save")
        self.revert_button = QPushButton("Revert")
        self.close_button = QPushButton("Close")
        for b in (self.save_button, self.revert_button, self.close_button):
            b.setAutoDefault(False)
        row.addWidget(self.title, 1)
        row.addWidget(self.save_button)
        row.addWidget(self.revert_button)
        row.addWidget(self.close_button)
        box.addLayout(row)
        self.note = QLabel("")
        self.note.setWordWrap(True)
        self.note.setStyleSheet("color:#9aa1ab;")
        box.addWidget(self.note)
        self.text = QPlainTextEdit()
        self.text.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        self.text.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        box.addWidget(self.text, 1)

        self.save_button.clicked.connect(self.save)
        self.revert_button.clicked.connect(self.revert)
        self.close_button.clicked.connect(self.close_file)
        self.text.textChanged.connect(self._refresh)
        self.files.done.connect(self._on_done)
        self.save_shortcut = QShortcut(QKeySequence.StandardKey.Save, self,
                                       context=Qt.ShortcutContext.WidgetWithChildrenShortcut,
                                       activated=self.save)
        self._refresh()

    # -- state ------------------------------------------------------------------

    def is_dirty(self) -> bool:
        return (self.baseline is not None and not self.readonly_reason
                and _norm(self.text.toPlainText()) != self.baseline)

    def _ask(self, question: str) -> bool:
        if self._confirm is not None:
            return bool(self._confirm(question))
        answer = QMessageBox.question(self, "Unsaved changes", question)
        return answer == QMessageBox.StandardButton.Yes

    def _refresh(self) -> None:
        dirty = self.is_dirty()
        self.title.setText((self.path or "") + (" •" if dirty else ""))
        editable = self.baseline is not None and not self.readonly_reason
        self.text.setReadOnly(not editable)
        self.save_button.setEnabled(editable and dirty)
        self.revert_button.setEnabled(self.path is not None)
        self.close_button.setEnabled(self.path is not None)

    # -- actions ----------------------------------------------------------------

    def open(self, path: str) -> bool:
        """False if the user kept unsaved edits instead."""
        if self.is_dirty() and not self._ask(
                f"Discard your unsaved changes to {self.path}?"):
            return False
        self._load(path)
        return True

    def _load(self, path: str) -> None:
        self.path, self.baseline, self.readonly_reason = path, None, ""
        self.text.blockSignals(True)
        self.text.setPlainText("")
        self.text.blockSignals(False)
        self.note.setText("Loading…")
        self._pending[self.files.read(path)] = ("open", path)
        self._refresh()

    def revert(self) -> None:
        if self.path is None:
            return
        if self.is_dirty() and not self._ask(f"Discard your changes to {self.path}?"):
            return
        self._load(self.path)

    def close_file(self) -> bool:
        if self.is_dirty() and not self._ask(
                f"Close {self.path} and discard your unsaved changes?"):
            return False
        self.path, self.baseline, self.readonly_reason = None, None, ""
        self.text.blockSignals(True)
        self.text.setPlainText("")
        self.text.blockSignals(False)
        self.note.setText("")
        self._refresh()
        self.closed.emit()
        return True

    def save(self) -> None:
        if not self.is_dirty() or self.path is None:
            return
        content = _norm(self.text.toPlainText())
        self.note.setText("Checking the file on disk before saving…")
        self._pending[self.files.read(self.path)] = ("check", self.path, content)
        self.save_button.setEnabled(False)

    # -- results ----------------------------------------------------------------

    def _on_done(self, rid: str, result) -> None:
        job = self._pending.pop(rid, None)
        if job is None or job[1] != self.path:
            return                              # another file is open now
        kind = job[0]
        if kind == "open":
            self._opened(result)
        elif kind == "check":
            self._checked(result, job[2])
        elif kind == "write":
            self._written(result, job[2])
        self._refresh()

    def _opened(self, result) -> None:
        if not isinstance(result, dict) or "error" in result:
            self.readonly_reason = _why_not(result)
            self.baseline = ""
            self.note.setText(self.readonly_reason)
            self.loaded.emit(self.path, False)
            return
        text = _norm(result.get("text", ""))
        self.text.blockSignals(True)
        self.text.setPlainText(text)
        self.text.blockSignals(False)
        self.baseline = text
        if result.get("cached"):
            self.readonly_reason = CACHED_NOTE
            self.note.setText(CACHED_NOTE)
        else:
            self.note.setText("")
        self.loaded.emit(self.path, True)

    def _checked(self, result, content: str) -> None:
        if not isinstance(result, dict) or "error" in result:
            self.note.setText(f"Could not re-read {self.path} before saving "
                              f"({error_cause(result)}), so nothing was saved.")
            return
        if result.get("cached"):
            self.note.setText(CACHED_NOTE)
            return
        if _norm(result.get("text", "")) != self.baseline:
            self.note.setText(CHANGED_NOTE.format(path=self.path))
            return
        self.note.setText("Saving…")
        self._pending[self.files.write(self.path, content)] = ("write", self.path, content)

    def _written(self, result, content: str) -> None:
        if not isinstance(result, dict) or "error" in result or not result.get("ok"):
            self.note.setText(f"Save failed: {error_cause(result)}. Your text is kept.")
            return
        self.baseline = content
        self.note.setText(f"Saved {self.path}.")
        self.saved.emit(self.path)
