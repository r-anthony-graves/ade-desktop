"""The workspace, one directory per expand, through /v1/fs.

Ade OS's list_dir is the containment and the filter (dotfiles, venvs and
node_modules never come back); this only asks and draws. No create, rename
or delete here: the terminal does those, and Refresh shows the result.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QTreeWidget, QTreeWidgetItem

from ade_desktop.conversation.replies import error_cause
from ade_desktop.sections.code.model import dirs_first, listing_note
from ade_desktop.workspace.files import is_missing

PATH = Qt.ItemDataRole.UserRole
KIND = Qt.ItemDataRole.UserRole + 1
LOADED = Qt.ItemDataRole.UserRole + 2
LOADING = "Loading…"


class FileTree(QTreeWidget):
    open_requested = Signal(str)       # a file's workspace-relative path
    root_named = Signal(str)           # the workspace folder, from the first listing

    def __init__(self, files, parent=None) -> None:
        super().__init__(parent)
        self.files = files
        self.setHeaderHidden(True)
        self.setColumnCount(1)
        self.setUniformRowHeights(True)
        self._pending: dict[str, tuple[str, int]] = {}   # rid -> (dir path, generation)
        self._generation = 0
        self._reopen: set[str] = set()
        self.files.done.connect(self._on_done)
        self.itemExpanded.connect(self._on_expanded)
        self.itemActivated.connect(self._on_activated)

    # -- asking ---------------------------------------------------------------

    def refresh(self) -> None:
        """Re-list from the top, re-opening every folder that was open."""
        self._reopen = self.expanded_paths()
        self._generation += 1
        self._pending.clear()
        self.clear()
        self._list("")

    def expanded_paths(self) -> set[str]:
        found = set()
        stack = [self.invisibleRootItem()]
        while stack:
            item = stack.pop()
            for i in range(item.childCount()):
                child = item.child(i)
                if child.data(0, KIND) == "dir" and child.isExpanded():
                    found.add(child.data(0, PATH))
                    stack.append(child)
        return found

    def _list(self, path: str) -> None:
        self._pending[self.files.list_dir(path)] = (path, self._generation)

    def _on_expanded(self, item) -> None:
        if item.data(0, KIND) == "dir" and not item.data(0, LOADED):
            item.setData(0, LOADED, True)
            self._list(item.data(0, PATH))

    def _on_activated(self, item, _column=0) -> None:
        if item.data(0, KIND) == "file":
            self.open_requested.emit(item.data(0, PATH))

    # -- answers --------------------------------------------------------------

    def _item_for(self, path: str):
        if path == "":
            return self.invisibleRootItem()
        stack = [self.invisibleRootItem()]
        while stack:
            item = stack.pop()
            for i in range(item.childCount()):
                child = item.child(i)
                if child.data(0, PATH) == path and child.data(0, KIND) == "dir":
                    return child
                if child.data(0, KIND) == "dir" and path.startswith(
                        str(child.data(0, PATH)) + "/"):
                    stack.append(child)
        return None

    @staticmethod
    def _note(parent, text: str) -> None:
        note = QTreeWidgetItem(parent, [text])
        note.setFlags(Qt.ItemFlag.NoItemFlags)
        note.setData(0, KIND, "note")

    def _on_done(self, rid: str, result) -> None:
        job = self._pending.pop(rid, None)
        if job is None or job[1] != self._generation:
            return                      # not ours, or from before a refresh
        path = job[0]
        parent = self._item_for(path)
        if parent is None:
            return                      # its folder is no longer in the tree
        parent.takeChildren()
        if not isinstance(result, dict) or "error" in result or not isinstance(
                result.get("entries"), list):
            if parent is not self.invisibleRootItem():
                parent.setData(0, LOADED, False)     # expanding again asks again
            self._note(parent, "This folder is gone. Refresh the tree."
                       if is_missing(result) else f"Could not list it: {error_cause(result)}")
            return
        if path == "" and result.get("root"):
            self.root_named.emit(str(result["root"]))
        entries = result["entries"]
        for entry in dirs_first([e for e in entries if isinstance(e, dict)]):
            item = QTreeWidgetItem(parent, [str(entry.get("name", ""))])
            item.setData(0, PATH, str(entry.get("path", "")))
            item.setData(0, KIND, "dir" if entry.get("kind") == "dir" else "file")
            item.setToolTip(0, str(entry.get("path", "")))
            if entry.get("kind") == "dir":
                self._note(item, LOADING)        # the arrow, until it is listed
        note = listing_note(entries)
        if note:
            self._note(parent, note)
        for i in range(parent.childCount()):
            child = parent.child(i)
            if child.data(0, KIND) == "dir" and child.data(0, PATH) in self._reopen:
                child.setExpanded(True)          # lists it, through _on_expanded
