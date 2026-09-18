"""Code (piece 7): the workspace tree, a tab per open file, and underneath
them Problems and a terminal -- the three things the web's VS Code frame
was used for, native.

Every tab is the shared FileEditor (pieces 4 and 5), so the rules it
learned hold here unchanged: the QVM index copy is never saved, a file
that changed on disk is never overwritten, a BOM survives, unsaved text
is never dropped without asking.

Problems are the checker's view of the file AS SAVED: Ade OS's language
server reads the disk, not this window, and the label says so.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeySequence, QShortcut, QTextCursor, QTextDocument
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QLineEdit, QPushButton, QSplitter,
                               QStackedWidget, QTabWidget, QTreeWidget, QTreeWidgetItem,
                               QVBoxLayout, QWidget)

from ade_desktop.sections.code.model import diag_note, diag_summary, tab_title
from ade_desktop.sections.code.terminal import TerminalPane
from ade_desktop.sections.code.tree import FileTree
from ade_desktop.workspace.editor import FileEditor

EMPTY_NOTE = "Open a file from the tree on the left."
LINE, COL, SOURCE = (Qt.ItemDataRole.UserRole, Qt.ItemDataRole.UserRole + 1,
                     Qt.ItemDataRole.UserRole + 2)


def _name(path: str) -> str:
    return path.replace("\\", "/").rsplit("/", 1)[-1]


class FindBox(QLineEdit):
    back = Signal()
    dismissed = Signal()

    def keyPressEvent(self, event) -> None:  # noqa: N802 -- Qt's name
        enter = event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter)
        if enter and event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            self.back.emit()
        elif event.key() == Qt.Key.Key_Escape:
            self.dismissed.emit()
        else:
            super().keyPressEvent(event)


class FindBar(QWidget):
    find = Signal(str, bool)         # text, backward

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        self.box = FindBox()
        self.box.setPlaceholderText("Find (Enter: next, Shift+Enter: previous, Esc: close)")
        self.prev_button = QPushButton("Previous")
        self.next_button = QPushButton("Next")
        self.close_button = QPushButton("Close")
        self.note = QLabel("")
        self.note.setTextFormat(Qt.TextFormat.PlainText)
        for w in (self.box, self.prev_button, self.next_button, self.note, self.close_button):
            row.addWidget(w, 1 if w is self.box else 0)
        for b in (self.prev_button, self.next_button, self.close_button):
            b.setAutoDefault(False)
        self.box.returnPressed.connect(self._next)
        self.next_button.clicked.connect(self._next)
        self.box.back.connect(self._prev)
        self.prev_button.clicked.connect(self._prev)
        self.box.dismissed.connect(self.hide)
        self.close_button.clicked.connect(self.hide)

    def _next(self) -> None:
        self.find.emit(self.box.text(), False)

    def _prev(self) -> None:
        self.find.emit(self.box.text(), True)


class CodePanel(QWidget):
    def __init__(self, client, files, *, confirm=None, parent=None) -> None:
        super().__init__(parent)
        self.client, self.files = client, files
        self._confirm = confirm
        self._listed = False
        self._diag_ticket = 0
        self._diag_pending: dict[str, tuple[int, str]] = {}
        self._checked_text = ""

        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        split = QSplitter(Qt.Orientation.Horizontal)
        outer.addWidget(split)

        # -- the tree
        left = QWidget()
        lbox = QVBoxLayout(left)
        lbox.setContentsMargins(0, 0, 0, 0)
        head = QHBoxLayout()
        self.root_label = QLabel("Workspace")
        self.root_label.setTextFormat(Qt.TextFormat.PlainText)
        self.root_label.setStyleSheet("color:#9aa1ab;")
        self.refresh_button = QPushButton("Refresh")
        self.refresh_button.setAutoDefault(False)
        head.addWidget(self.root_label, 1)
        head.addWidget(self.refresh_button)
        lbox.addLayout(head)
        self.tree = FileTree(files)
        lbox.addWidget(self.tree, 1)
        split.addWidget(left)

        # -- tabs over Problems / Terminal
        right = QSplitter(Qt.Orientation.Vertical)
        top = QWidget()
        tbox = QVBoxLayout(top)
        tbox.setContentsMargins(0, 0, 0, 0)
        self.find_bar = FindBar()
        self.find_bar.hide()
        tbox.addWidget(self.find_bar)
        self.stack = QStackedWidget()
        self.empty = QLabel(EMPTY_NOTE)
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty.setStyleSheet("color:#9aa1ab;")
        self.tabs = QTabWidget()
        self.tabs.setTabsClosable(True)
        self.tabs.setMovable(True)
        self.tabs.setDocumentMode(True)
        self.stack.addWidget(self.empty)
        self.stack.addWidget(self.tabs)
        tbox.addWidget(self.stack, 1)
        self.position = QLabel("")
        self.position.setStyleSheet("color:#9aa1ab;")
        tbox.addWidget(self.position, 0, Qt.AlignmentFlag.AlignRight)
        right.addWidget(top)

        self.bottom = QTabWidget()
        self.bottom.setDocumentMode(True)
        problems = QWidget()
        pbox = QVBoxLayout(problems)
        pbox.setContentsMargins(0, 0, 0, 0)
        prow = QHBoxLayout()
        self.problems_label = QLabel("Open a Python or JavaScript file to check it.")
        self.problems_label.setTextFormat(Qt.TextFormat.PlainText)
        self.problems_label.setWordWrap(True)
        self.check_button = QPushButton("Check again")
        self.check_button.setAutoDefault(False)
        prow.addWidget(self.problems_label, 1)
        prow.addWidget(self.check_button)
        pbox.addLayout(prow)
        self.problems = QTreeWidget()
        self.problems.setHeaderLabels(["", "Line", "Problem"])
        self.problems.setRootIsDecorated(False)
        self.problems.setUniformRowHeights(True)
        pbox.addWidget(self.problems, 1)
        self.bottom.addTab(problems, "Problems")
        self.terminal = TerminalPane(client)
        self.bottom.addTab(self.terminal, "Terminal")
        right.addWidget(self.bottom)
        right.setStretchFactor(0, 3)
        right.setStretchFactor(1, 2)
        split.addWidget(right)
        split.setStretchFactor(0, 1)
        split.setStretchFactor(1, 4)
        # Stretch factors share out only what is left over the size hints --
        # measured live: the editor got 130 px of 860 and the tree a third
        # of the width. Starting sizes, in proportion, say what is meant.
        right.setSizes([600, 300])
        split.setSizes([280, 1120])

        self.find_shortcut = QShortcut(QKeySequence.StandardKey.Find, self,
                                       context=Qt.ShortcutContext.WidgetWithChildrenShortcut,
                                       activated=self.show_find)
        self.refresh_button.clicked.connect(self.tree.refresh)
        self.tree.open_requested.connect(self.open_file)
        self.tree.root_named.connect(self.root_label.setText)
        self.tabs.tabCloseRequested.connect(self._close_tab)
        self.tabs.currentChanged.connect(self._on_current)
        self.problems.itemActivated.connect(self._jump)
        self.check_button.clicked.connect(self.check)
        self.find_bar.find.connect(self._find)
        self.client.done.connect(self._on_client_done)

    # -- tabs ---------------------------------------------------------------------

    def editors(self) -> list[FileEditor]:
        return [self.tabs.widget(i) for i in range(self.tabs.count())]

    def current_editor(self) -> FileEditor | None:
        widget = self.tabs.currentWidget()
        return widget if isinstance(widget, FileEditor) else None

    def open_file(self, path: str) -> FileEditor:
        for i, editor in enumerate(self.editors()):
            if editor.path == path:
                self.tabs.setCurrentIndex(i)
                return editor
        editor = FileEditor(self.files, confirm=self._confirm)
        editor.closed.connect(self._on_editor_closed)
        editor.saved.connect(self._on_saved)
        editor.loaded.connect(self._on_loaded)
        editor.text.textChanged.connect(self._retitle_current)
        editor.text.cursorPositionChanged.connect(self._show_position)
        index = self.tabs.addTab(editor, tab_title(path, False))
        self.tabs.setTabToolTip(index, path)
        self.stack.setCurrentWidget(self.tabs)
        editor.open(path)
        self.tabs.setCurrentIndex(index)
        return editor

    def _close_tab(self, index: int) -> None:
        editor = self.tabs.widget(index)
        if isinstance(editor, FileEditor):
            editor.close_file()          # asks when dirty; `closed` removes the tab

    def _on_editor_closed(self) -> None:
        editor = self.sender()
        index = self.tabs.indexOf(editor)
        if index < 0:
            return
        self.tabs.removeTab(index)
        editor.deleteLater()
        if self.tabs.count() == 0:
            self.stack.setCurrentWidget(self.empty)
            self.position.setText("")
            self._show_problems_note("Open a Python or JavaScript file to check it.")

    def _retitle(self, index: int) -> None:
        editor = self.tabs.widget(index)
        if isinstance(editor, FileEditor) and editor.path:
            self.tabs.setTabText(index, tab_title(editor.path, editor.is_dirty()))

    def _retitle_current(self) -> None:
        self._retitle(self.tabs.currentIndex())

    def _retitle_all(self) -> None:
        for i in range(self.tabs.count()):
            self._retitle(i)

    def _show_position(self) -> None:
        editor = self.current_editor()
        if editor is None:
            self.position.setText("")
            return
        cursor = editor.text.textCursor()
        self.position.setText(f"Ln {cursor.blockNumber() + 1}, Col {cursor.positionInBlock() + 1}")

    def _on_current(self, _index: int) -> None:
        self._show_position()
        editor = self.current_editor()
        if editor is not None and editor.baseline is not None and not editor.missing:
            self.check()
            return
        # Nothing to check yet (still opening) or at all (it did not open):
        # the last tab's problems must not stay up under this tab's name.
        self._diag_ticket += 1
        if editor is None:
            self._show_problems_note("Open a Python or JavaScript file to check it.")
        elif editor.baseline is None:
            self._show_problems_note(f"Waiting for {_name(editor.path or '')} to open…")
        else:
            self._show_problems_note(f"Nothing to check: {_name(editor.path or '')} "
                                     "did not open.")

    def _on_loaded(self, path: str, ok: bool) -> None:
        self._retitle_all()
        editor = self.current_editor()
        if editor is not self.sender():
            return
        if ok:
            self.check()
        else:
            self._diag_ticket += 1
            self._show_problems_note(f"Nothing to check: {_name(path)} did not open.")

    def _on_saved(self, path: str) -> None:
        self._retitle_all()
        editor = self.current_editor()
        if editor is not None and editor.path == path:
            self.check()

    # -- Problems -------------------------------------------------------------------

    def _show_problems_note(self, text: str) -> None:
        self.problems.clear()
        self.problems_label.setText(text)
        self.bottom.setTabText(0, "Problems")

    def check(self) -> None:
        editor = self.current_editor()
        if editor is None or not editor.path:
            return
        self._diag_ticket += 1
        self._diag_pending[self.client.diagnostics(editor.path)] = (self._diag_ticket,
                                                                    editor.path)
        self._show_problems_note(f"Checking {_name(editor.path)}…")

    def _on_client_done(self, rid: str, result) -> None:
        job = self._diag_pending.pop(rid, None)
        if job is None:
            return                          # the terminal's, or an old check
        ticket, path = job
        editor = self.current_editor()
        if ticket != self._diag_ticket or editor is None or editor.path != path:
            return                          # a newer check, or another tab, has the list
        note = diag_note(result, path)
        if note:
            self._show_problems_note(note)
            return
        data = result["data"]
        items = [i for i in (data.get("items") or []) if isinstance(i, dict)]
        summary = diag_summary(data.get("counts"))
        self.problems.clear()
        self._checked_text = f"{_name(path)} as saved on disk: {summary}"
        self.problems_label.setText(self._checked_text)
        self.bottom.setTabText(0, f"Problems ({len(items)})" if items else "Problems")
        for item in items:
            message = str(item.get("message", ""))
            code = str(item.get("code") or "")
            first = message.splitlines()[0] if message else ""
            row = QTreeWidgetItem(self.problems, [
                str(item.get("severity", "")), f"{item.get('line', '?')}:{item.get('col', '?')}",
                first + (f"  [{code}]" if code else "")])
            row.setToolTip(2, message)
            row.setData(0, LINE, item.get("line"))
            row.setData(0, COL, item.get("col"))
            row.setData(0, SOURCE, path)

    def _jump(self, row, _column=0) -> None:
        editor = self.current_editor()
        line, col = row.data(0, LINE), row.data(0, COL)
        if editor is None or editor.path != row.data(0, SOURCE) or not isinstance(line, int):
            return
        block = editor.text.document().findBlockByNumber(max(0, line - 1))
        if not block.isValid():
            return
        offset = max(0, min((col if isinstance(col, int) else 1) - 1, block.length() - 1))
        cursor = QTextCursor(block)
        cursor.setPosition(block.position() + offset)
        editor.text.setTextCursor(cursor)
        editor.text.centerCursor()
        editor.text.setFocus()
        if editor.is_dirty():
            # The checker read the saved file; typed lines move what it named.
            self.problems_label.setText(self._checked_text + ". You have unsaved edits, "
                                        "so these lines may have moved: save to check again.")

    # -- find ---------------------------------------------------------------------

    def show_find(self) -> None:
        self.find_bar.show()
        self.find_bar.box.setFocus()
        self.find_bar.box.selectAll()

    def _find(self, text: str, backward: bool) -> None:
        editor = self.current_editor()
        if editor is None or not text:
            return
        edit = editor.text
        flags = (QTextDocument.FindFlag.FindBackward if backward
                 else QTextDocument.FindFlag(0))
        if edit.find(text, flags):
            self.find_bar.note.setText("")
            return
        # wrap around once -- and put the cursor back if that finds nothing
        before = edit.textCursor()
        cursor = QTextCursor(before)
        cursor.movePosition(QTextCursor.MoveOperation.End if backward
                            else QTextCursor.MoveOperation.Start)
        edit.setTextCursor(cursor)
        found = edit.find(text, flags)
        if not found:
            edit.setTextCursor(before)
        self.find_bar.note.setText("" if found else "No match")

    # -- the app's questions --------------------------------------------------------

    def showEvent(self, event) -> None:  # noqa: N802 -- Qt's name
        super().showEvent(event)
        if not self._listed:
            self._listed = True
            self.tree.refresh()

    def unsaved(self) -> list[str]:
        lost = []
        for editor in self.editors():
            if editor.is_dirty():
                lost.append(f"unsaved changes to {editor.path}")
            if editor.is_busy():
                lost.append(f"a save of {editor.path} still in flight")
        if self.terminal.may_be_running():
            lost.append("a command that may still be running in the Code terminal "
                        "(quitting stops it)")
        return lost

    def stop_clients(self) -> None:
        self.terminal.stop_now()
        self.client.stop()
        self.files.stop()
