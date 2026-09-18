"""Which package folders Ade is writing into right now -- one answer for
the whole app, like the web's useFillingDirs.

PM and QA each run their own AddProjectFlow, and either can be writing
qa/<slug>/ while the other has one of its documents open. /v1/pm/author
overwrites without asking (records/author.py), so an editor must not save
a document in a folder that is being written: the review found a save
landing and then being silently replaced.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal

WRITING_NOTE = "Ade is writing this package right now; save after it finishes."


class FillingDirs(QObject):
    changed = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._dirs: dict[str, int] = {}

    def mark(self, folder: str) -> None:
        self._dirs[folder] = self._dirs.get(folder, 0) + 1
        self.changed.emit()

    def clear(self, folder: str) -> None:
        n = self._dirs.get(folder, 0) - 1
        if n > 0:
            self._dirs[folder] = n
        else:
            self._dirs.pop(folder, None)
        self.changed.emit()

    def folder_of(self, path: str | None) -> str | None:
        """The folder being written that holds `path`, or None."""
        for folder in self._dirs:
            if path and (path == folder or path.startswith(folder + "/")):
                return folder
        return None

    def is_filling(self, folder: str) -> bool:
        return folder in self._dirs


_FILLING: FillingDirs | None = None


def filling() -> FillingDirs:
    """Created on first use -- by a panel, on the UI thread -- and kept for
    the life of the process."""
    global _FILLING
    if _FILLING is None:
        _FILLING = FillingDirs()
    return _FILLING
