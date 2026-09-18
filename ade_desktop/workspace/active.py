"""Which project the app is looking at -- ONE answer for every section, as
the web's useActiveProject is (PM picks it, QA reads it). Kept by NAME, the
way the web keys it: a name survives the id churn of a rebuilt PM table,
and the backlog joins on it. Remembered in window.json, merged with the
window's own keys."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, Signal

from ade_desktop.geometry import load_state, save_state

KEY = "active_project"


class ActiveProject(QObject):
    changed = Signal(str)

    def __init__(self, state_path: Path | None = None, parent=None) -> None:
        super().__init__(parent)
        self._path = Path(state_path) if state_path else None
        value = load_state(self._path).get(KEY) if self._path else None
        self._name = value if isinstance(value, str) and value else ""

    @property
    def name(self) -> str:
        return self._name

    def set(self, name: str) -> None:
        name = str(name or "")
        if name == self._name:
            return
        self._name = name
        if self._path is not None:
            state = load_state(self._path)
            state[KEY] = name
            save_state(self._path, state)
        self.changed.emit(name)
