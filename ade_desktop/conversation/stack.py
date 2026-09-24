"""Many chat sessions on one page (Ray, 2026-09-24, requirement 7).

Each session is a real conversation -- its own ConversationPanel, its own
thread file, its own Ade OS topic and its own busy state -- so a long
/task in one does not block another. That is the same reason each SECTION
got a chat of its own on 2026-09-18, applied one level down.

The panels are built by a `make_panel(index)` callable, so
`__main__.build_window` keeps ownership of the store/client/router wiring
and this widget stays about tabs.

THE SELECTED SESSION IS THE APPROVAL FALLBACK. An approval nobody owns has
to land where somebody can see it: a card on a hidden tab is never
answered, and an unanswered approval times out -- which denies.
"""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (QHBoxLayout, QPushButton, QStackedWidget,
                               QTabBar, QVBoxLayout, QWidget)

from ade_desktop.conversation.sessions import GENERAL


class ChatStack(QWidget):
    approval_needed = Signal(str)       # forwarded from whichever panel asked
    # The orb connects to reply_landed and the voice controller calls note/
    # stage/voice_ask. Both used to hold General's one panel; they now hold
    # the stack, and everything below lands in whichever session is
    # SELECTED. That is the point: "Ade, ..." should answer in the chat Ray
    # is looking at, not in whichever one happened to be first.
    reply_landed = Signal(str)

    def __init__(self, name: str, make_panel: Callable[[int], QWidget],
                 router=None, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("chatStack")
        self.name = name
        self._make_panel = make_panel
        self._router = router
        self._next_number = 1           # session numbers are never reused
        self.panels: list = []

        box = QVBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(0)
        row = QHBoxLayout()
        row.setContentsMargins(6, 4, 6, 0)
        row.setSpacing(4)
        self.tabs = QTabBar()
        self.tabs.setObjectName("chatTabs")
        self.tabs.setExpanding(False)
        self.tabs.setTabsClosable(True)
        self.tabs.setDrawBase(False)
        self.add_button = QPushButton("+")
        self.add_button.setObjectName("chatAdd")
        self.add_button.setFixedWidth(34)
        self.add_button.setAutoDefault(False)
        self.add_button.setToolTip("Start another chat")
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

    def key_for(self, index: int) -> str:
        return f"{self.name}#{index}"

    def add_session(self):
        number = self._next_number
        self._next_number += 1
        panel = self._make_panel(number)
        panel.setProperty("session_key", self.key_for(number))
        panel.approval_needed.connect(self.approval_needed)
        panel.reply_landed.connect(self.reply_landed)
        self.panels.append(panel)
        self.stack.addWidget(panel)
        at = self.tabs.addTab(f"Chat {number}")
        self.tabs.setCurrentIndex(at)
        return panel

    def close_session(self, index: int) -> None:
        if len(self.panels) <= 1 or not 0 <= index < len(self.panels):
            return                      # a chat page with no chat is a dead page
        panel = self.panels.pop(index)
        self.tabs.removeTab(index)
        self.stack.removeWidget(panel)
        for step in (panel.on_quit, panel.client.stop, panel.watcher.stop):
            try:
                step()
            except Exception:           # noqa: BLE001 -- closing must finish
                pass
        panel.deleteLater()

    def current(self):
        at = self.tabs.currentIndex()
        return self.panels[at] if 0 <= at < len(self.panels) else None

    def session_count(self) -> int:
        return len(self.panels)

    def select(self, panel) -> bool:
        """Show the tab holding `panel`. raise_for_approval needs this: a
        card on a tab you cannot see is a card you never answer."""
        if panel in self.panels:
            self.tabs.setCurrentIndex(self.panels.index(panel))
            return True
        return False

    # -- what voice and the orb call ----------------------------------------
    #
    # Delegated to the SELECTED session rather than to a remembered one: a
    # spoken question must land in the chat that is on screen. Each is a
    # plain forward -- no state lives here.

    @property
    def busy(self) -> bool:
        panel = self.current()
        return bool(panel is not None and panel.busy)

    @property
    def watcher(self):
        """DesktopWindow falls back to `panel.watcher` when it is given no
        Ade OS-wide watcher of its own. The real app always passes one; a
        test that does not must still get something with the signals."""
        panel = self.current()
        return None if panel is None else panel.watcher

    def note(self, text: str) -> None:
        panel = self.current()
        if panel is not None:
            panel.note(text)

    def focus_input(self) -> None:
        panel = self.current()
        if panel is not None:
            panel.focus_input()

    def stage(self, text: str, note: str = "") -> None:
        panel = self.current()
        if panel is not None:
            panel.stage(text, note)

    def voice_ask(self, text: str) -> bool:
        panel = self.current()
        return bool(panel is not None and panel.voice_ask(text))

    def queue_voice_ask(self, text: str) -> bool:
        panel = self.current()
        return bool(panel is not None and panel.queue_voice_ask(text))

    def on_quit(self) -> None:
        for panel in self.panels:
            panel.on_quit()

    # -- the app ------------------------------------------------------------

    def start(self) -> None:
        for panel in self.panels:
            panel.watcher.start()

    def _on_tab(self, index: int) -> None:
        if not 0 <= index < len(self.panels):
            return
        panel = self.panels[index]
        self.stack.setCurrentWidget(panel)
        if self._router is not None and self.name == GENERAL:
            self._router.set_default(str(panel.property("session_key")))
