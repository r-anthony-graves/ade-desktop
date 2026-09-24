"""The shell pane: a session tab strip over N terminals.

Each tab is its own ConPTY with its own cwd, environment, history and
scrollback -- one running a server, one for git, as a person actually
works. Closing a tab kills that pty and only that one.

The LAST tab cannot be closed: a shell pane with no shell is a dead
rectangle, and "+" to get back what you just lost is not a feature.
"""

from __future__ import annotations

from PySide6.QtWidgets import (QHBoxLayout, QPushButton, QStackedWidget,
                               QTabBar, QVBoxLayout, QWidget)

from ade_desktop.shell.view import DEFAULT_FONT_PX, TerminalView


class ShellPane(QWidget):
    def __init__(self, parent=None, *, autostart: bool = True) -> None:
        super().__init__(parent)
        self.setObjectName("shellPane")
        self._autostart = autostart
        self._next_number = 1           # session numbers are never reused
        self.views: list[TerminalView] = []

        box = QVBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(0)
        row = QHBoxLayout()
        row.setContentsMargins(6, 4, 6, 0)
        row.setSpacing(4)
        self.tabs = QTabBar()
        self.tabs.setObjectName("shellTabs")
        self.tabs.setExpanding(False)
        self.tabs.setTabsClosable(True)
        self.tabs.setDrawBase(False)
        self.add_button = QPushButton("+")
        self.add_button.setObjectName("shellAdd")
        self.add_button.setFixedWidth(34)
        self.add_button.setAutoDefault(False)
        self.add_button.setToolTip("Open another shell")
        row.addWidget(self.tabs, 1)
        row.addWidget(self.add_button)
        box.addLayout(row)
        self.stack = QStackedWidget()
        box.addWidget(self.stack, 1)

        self.tabs.currentChanged.connect(self._on_tab)
        self.tabs.tabCloseRequested.connect(self.close_session)
        self.add_button.clicked.connect(self.add_session)
        self.add_session()

    # -- sessions -----------------------------------------------------------

    def add_session(self) -> TerminalView:
        view = TerminalView()
        self.views.append(view)
        self.stack.addWidget(view)
        index = self.tabs.addTab(f"{view.title()} {self._next_number}")
        self._next_number += 1
        self.tabs.setCurrentIndex(index)
        if self._autostart:
            view.start()
        return view

    def close_session(self, index: int) -> None:
        if len(self.views) <= 1 or not 0 <= index < len(self.views):
            return                      # never the last one
        view = self.views.pop(index)
        self.tabs.removeTab(index)
        self.stack.removeWidget(view)
        view.stop()                     # no tab, no shell
        view.deleteLater()

    def current(self) -> TerminalView | None:
        index = self.tabs.currentIndex()
        return self.views[index] if 0 <= index < len(self.views) else None

    def session_count(self) -> int:
        return len(self.views)

    # -- the app ------------------------------------------------------------

    def set_font_px(self, px: int) -> None:
        for view in self.views:
            view.set_font_px(px)

    def apply_zoom(self, scale: float) -> None:
        """The window's zoom_changed lands here. QSS cannot reach a
        QPainter surface, so the scale is applied as a pixel size."""
        self.set_font_px(round(DEFAULT_FONT_PX * float(scale)))

    def stop_all(self) -> None:
        """Quit. Every pty goes, or a pwsh outlives the window that was the
        only way to notice it."""
        for view in self.views:
            view.stop()

    def _on_tab(self, index: int) -> None:
        if 0 <= index < len(self.views):
            view = self.views[index]
            self.stack.setCurrentWidget(view)
            view.setFocus()
