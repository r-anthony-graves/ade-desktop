"""The window: a header that always says what Ade OS is doing, a rail of the
sections that exist, the sections themselves, and a tray to come back from.

Close HIDES to the tray -- the trader's pollers keep running while the window
is out of the way, as the avatar does. With no system tray, close quits:
a hidden window with nothing to click is a window nobody can ever reach.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QGuiApplication, QIcon, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication, QHBoxLayout, QLabel, QListWidget, QMainWindow, QMenu,
    QMessageBox, QSplitter, QStackedWidget, QSystemTrayIcon, QToolButton,
    QVBoxLayout, QWidget,
)

from ade_desktop.ade_status import brain_name, health_pill
from ade_desktop.conversation.sessions import GENERAL
from ade_desktop.geometry import (
    Rect, centred_on, clamp_to_screens, load_state, rect_from_state,
    save_state,
)
from ade_desktop.sections import Section
from ade_desktop.theme import TONES, clamp_zoom, stylesheet

log = logging.getLogger("ade_desktop.app")

ICON_PATH = Path(__file__).resolve().parent.parent / "icon.png"
DEFAULT_W, DEFAULT_H = 1360, 860  # the trader window's size: its screens
                                  # were laid out for it
PANEL_MIN_W, PANEL_MAX_W, PANEL_DEFAULT_W = 280, 900, 420
ZOOM_STEP = 0.1
# Ray, 2026-09-18: "need a general chat not just trader pm and qa, add a
# general", then "create chat sessions for each so chats dont overlap". The
# rail's first section is General's chat, full size; every other section has
# a chat of its own beside it (conversation/sessions.py), so a question asked
# in PM never lands in QA and one long ask never blocks another section.


def clamp_panel_width(value) -> int:
    try:
        width = int(value)
    except (TypeError, ValueError):
        return PANEL_DEFAULT_W
    return max(PANEL_MIN_W, min(PANEL_MAX_W, width))


class Pill(QLabel):
    """The trader's StatusPill look, drawn here rather than imported: the
    header must render when the trader failed to import."""

    def __init__(self, name: str, parent=None) -> None:
        super().__init__(parent)
        self._name = name
        self.label = "—"
        self.tone = "off"
        self.set_state("—", "off")

    def set_state(self, label: str, tone: str, tooltip: str = "") -> None:
        self.label = label
        self.tone = tone
        color = TONES.get(tone, TONES["off"])
        self.setText(f"{self._name} ● {label}")
        self.setToolTip(tooltip)
        self.setStyleSheet(
            f"color: {color}; padding: 2px 10px; border: 1px solid {color};"
            "border-radius: 9px; font-weight: 600;")


def _screen_rects() -> list[Rect]:
    primary = QGuiApplication.primaryScreen()
    ordered = [primary] + [s for s in QGuiApplication.screens()
                           if s is not primary]
    rects = []
    for screen in ordered:
        if screen is None:
            continue
        g = screen.availableGeometry()
        rects.append(Rect(g.x(), g.y(), g.width(), g.height()))
    return rects


class DesktopWindow(QMainWindow):
    # Ctrl+= / Ctrl+- / Ctrl+0 restyle the app through QSS. The terminal
    # paints itself, so QSS cannot reach it -- it takes the scale from here.
    zoom_changed = Signal(float)

    def __init__(self, sections: list[Section], status, *, state_path: Path,
                 tray_available: bool | None = None,
                 quit_fn: Callable[[], None] | None = None,
                 panel=None, side_panels=None, approvals=None, confirm_quit=None,
                 shell=None, parent=None) -> None:
        super().__init__(parent)
        self.sections = list(sections)
        self.status = status
        # A chat per section (Ray, 2026-09-18): `panel` is General's, full
        # size on its own page; `side_panels` holds each section's own chat,
        # shown beside that section. `approvals` is the one Ade OS-wide
        # watcher (the orb counts from it); each chat sees only its own.
        self.panel = panel
        self.side_panels = dict(side_panels or {})
        # Ray, 2026-09-24, requirements 1 and 8: "the shell only is needed
        # in the general chat tab" and "stack the chat and shell session on
        # the right col". ONE shell pane, under General's chat. Every other
        # page keeps its side chat and has no shell at all.
        self.shell = shell
        self.approvals = approvals if approvals is not None else getattr(panel, "watcher", None)
        self._panel_width = PANEL_DEFAULT_W
        self._state_path = Path(state_path)
        self._quit_fn = quit_fn or QApplication.quit
        self._confirm_quit = confirm_quit
        self._quitting = False
        self._last_health: str | None = None
        self._start_maximized = False
        self.orb_controller = None      # piece 3: set by build_window

        self.setWindowTitle("Ade")
        if ICON_PATH.exists():
            self.setWindowIcon(QIcon(str(ICON_PATH)))
        self._trader_qss = next((s.qss for s in self.sections if s.qss), None)
        self._zoom = 1.0
        self.setStyleSheet(stylesheet(self._trader_qss))
        # Ray, 2026-09-24, requirement 3. WindowShortcut, not Application:
        # an app must not take a key from the rest of the desktop (the
        # avatar's lesson with Alt+Space). Ctrl++ as well as Ctrl+=, because
        # on most keyboards "Ctrl and plus" is physically Ctrl+Shift+=.
        #
        # CONNECTED, never activated=partial(self._bump, step): a partial
        # holding a bound method is held STRONGLY by the shortcut, and the
        # shortcut is the window's child -- a cycle the collector has to
        # break, which is exactly what test_a_dropped_window_is_freed_at_once
        # forbids. Measured: three zero-argument methods and plain
        # connections leave the window freed at once. (2026-09-24)
        for keys, slot in (("Ctrl+=", self.zoom_in), ("Ctrl++", self.zoom_in),
                           ("Ctrl+-", self.zoom_out),
                           ("Ctrl+0", self.zoom_reset)):
            QShortcut(QKeySequence(keys), self,
                      context=Qt.ShortcutContext.WindowShortcut).activated.connect(slot)

        central = QWidget()
        outer = QVBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        header = QWidget()
        header.setObjectName("header")
        row = QHBoxLayout(header)
        row.setContentsMargins(14, 8, 14, 8)
        title = QLabel("Ade")
        title.setObjectName("appTitle")
        self.ade_pill = Pill("ADE OS")
        self.brain_label = QLabel("—")
        self.brain_label.setObjectName("brain")
        row.addWidget(title)
        row.addSpacing(14)
        row.addWidget(self.ade_pill)
        row.addSpacing(10)
        row.addWidget(self.brain_label)
        row.addStretch(1)
        # Mute: shown once an orb (and so a microphone) is attached.
        self.mic_button = QToolButton()
        self.mic_button.setObjectName("micButton")
        self.mic_button.setVisible(False)
        row.addWidget(self.mic_button)
        row.addSpacing(8)
        self.panel_toggle = QToolButton()
        self.panel_toggle.setObjectName("panelToggle")
        self.panel_toggle.setToolTip("Show or hide the Ade panel (Ctrl+Shift+A)")
        self.panel_toggle.clicked.connect(self._toggle_panel)
        self.panel_toggle.setVisible(False)     # shown in a section that has a chat
        row.addWidget(self.panel_toggle)
        outer.addWidget(header)

        main = QWidget()
        body = QHBoxLayout(main)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        self.rail = QListWidget()
        self.rail.setObjectName("rail")
        self.rail.setFixedWidth(160)
        self.stack = QStackedWidget()
        for section in self.sections:
            self.rail.addItem(section.name)
            self.stack.addWidget(section.widget)
        self._side_open = True          # the side chat's open state, shared by sections
        if panel is not None:
            # Chat on top, shell underneath, divider draggable. A vertical
            # splitter rather than a tab pair: you watch a command run while
            # you type the next question, which tabs cannot do.
            self.general_page = QSplitter(Qt.Orientation.Vertical)
            self.general_page.setObjectName("generalPage")
            self.general_page.setChildrenCollapsible(False)
            self.general_page.addWidget(panel)      # General's own chat, for good
            if shell is not None:
                self.general_page.addWidget(shell)
                self.general_page.setStretchFactor(0, 3)
                self.general_page.setStretchFactor(1, 2)
                self.zoom_changed.connect(shell.apply_zoom)
            self.rail.insertItem(0, GENERAL)
            self.stack.insertWidget(0, self.general_page)
        self.rail.currentRowChanged.connect(self.stack.setCurrentIndex)
        self.rail.currentRowChanged.connect(self._on_rail_row)
        body.addWidget(self.rail)
        body.addWidget(self.stack, 1)
        # rail + section | the conversation panel
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setChildrenCollapsible(False)
        self.splitter.addWidget(main)
        # Each section's chat, one at a time, beside its section.
        self.side = QStackedWidget()
        self.side.setObjectName("sideChats")
        for chat in self.side_panels.values():
            self.side.addWidget(chat)
        self.side.hide()
        if self.side_panels:
            self.splitter.addWidget(self.side)
            self.splitter.setStretchFactor(0, 1)
            self.splitter.setStretchFactor(1, 0)
        for stack in self.stacks():
            stack.approval_needed.connect(self._on_approval_needed)
        if self.side_panels:
            # Inside THIS window only: an app must not take an OS key (the
            # avatar's lesson with Alt+Space).
            self.panel_shortcut = QShortcut(
                QKeySequence("Ctrl+Shift+A"), self,
                context=Qt.ShortcutContext.WindowShortcut,
                activated=self._toggle_panel)
        outer.addWidget(self.splitter, 1)
        self.setCentralWidget(central)

        status.health.connect(self.apply_health)
        status.settings.connect(self.apply_settings)

        self.tray_available = (QSystemTrayIcon.isSystemTrayAvailable()
                               if tray_available is None else tray_available)
        self.tray = self._make_tray() if self.tray_available else None
        self._restore_state()

    # -- zoom ---------------------------------------------------------------

    def zoom(self) -> float:
        return self._zoom

    def set_zoom(self, scale) -> None:
        """One knob for every surface. QSS carries it everywhere except the
        terminal, which paints itself and so listens to zoom_changed."""
        scale = clamp_zoom(scale)
        if scale == self._zoom:
            return
        self._zoom = scale
        self.setStyleSheet(stylesheet(self._trader_qss, scale))
        self.zoom_changed.emit(scale)

    def zoom_in(self) -> None:
        self.set_zoom(self._zoom + ZOOM_STEP)

    def zoom_out(self) -> None:
        self.set_zoom(self._zoom - ZOOM_STEP)

    def zoom_reset(self) -> None:
        self.set_zoom(1.0)

    # -- the microphone -----------------------------------------------------

    def attach_mic(self, controller) -> None:
        """The header's Mute button drives the orb's microphone and shows
        what it is REALLY doing -- the orb's own menu item stays in step,
        because both go through the controller."""
        self.mic_button.clicked.connect(controller.toggle_mic)
        controller.mic_state.connect(self.show_mic)
        self.mic_button.setVisible(True)
        self.show_mic(controller.mic.running())

    def show_mic(self, listening: bool) -> None:
        self.mic_button.setText("Mute" if listening else "Unmute")
        self.mic_button.setToolTip("Ade is listening for its name. Click to mute the microphone."
                                   if listening else
                                   "The microphone is off: Ade hears nothing. Click to unmute.")
        self.mic_button.setProperty("muted", not listening)
        self.mic_button.style().unpolish(self.mic_button)
        self.mic_button.style().polish(self.mic_button)

    # -- sections -----------------------------------------------------------

    def section_names(self) -> list[str]:
        return [self.rail.item(i).text() for i in range(self.rail.count())]

    def current_section(self) -> str | None:
        item = self.rail.currentItem()
        return item.text() if item is not None else None

    def show_section(self, name: str) -> bool:
        """Switch the rail to `name` ("Open QA desk" from PM). False if no
        such section exists yet."""
        names = self.section_names()
        if name not in names:
            return False
        self.rail.setCurrentRow(names.index(name))
        return True

    def start(self) -> None:
        self.status.start()
        for section in self.sections:
            if section.start is not None:
                section.start()
        for stack in self.stacks():
            stack.start()

    # -- the conversation panel ---------------------------------------------

    # -- General: the conversation, full size ---------------------------------

    def stacks(self) -> list:
        """Every chat STACK: General's first, then each section's."""
        return (([self.panel] if self.panel is not None else [])
                + list(self.side_panels.values()))

    def all_panels(self) -> list:
        """Every chat SESSION, across every stack. Start, quit and the
        approval wiring all walk sessions, not pages (2026-09-24, req 7)."""
        return [panel for stack in self.stacks() for panel in stack.panels]

    def side_chat(self):
        """The chat shown beside the current section, or None (General,
        or a section without one)."""
        return self.side_panels.get(self.current_section())

    def _on_rail_row(self, row: int) -> None:
        chat = self.side_chat()
        if chat is None:
            if not self.side.isHidden():
                self._remember_panel_width()
                self.side.hide()
            self.panel_toggle.hide()
            return
        self.side.setCurrentWidget(chat)
        self.panel_toggle.show()
        self._apply_side()

    def panel_open(self) -> bool:
        """Whether the side chat is open -- one preference for every
        section, remembered while General or a chat-less section shows."""
        return self._side_open

    def set_panel_open(self, open_: bool) -> None:
        self._side_open = bool(open_)
        self._apply_side()

    def _apply_side(self) -> None:
        self.panel_toggle.setText("Ade ◂" if self._side_open else "Ade ▸")
        if self.side_chat() is None:
            return                      # nothing beside this section to show
        if self._side_open and self.side.isHidden():
            self.side.show()
            total = sum(self.splitter.sizes()) or self.width()
            width = clamp_panel_width(self._panel_width)
            self.splitter.setSizes([max(1, total - width), width])
        elif not self._side_open and not self.side.isHidden():
            self._remember_panel_width()
            self.side.hide()

    def _toggle_panel(self) -> None:
        self.set_panel_open(not self.panel_open())

    def _remember_panel_width(self) -> None:
        if not self.side.isHidden():
            sizes = self.splitter.sizes()
            if len(sizes) == 2 and sizes[1] > 0:
                self._panel_width = clamp_panel_width(sizes[1])

    def _on_approval_needed(self, tool: str) -> None:
        stack = self.sender()
        section = next((name for name, s in self.side_panels.items()
                        if s is stack), GENERAL)
        self.raise_for_approval(tool, section)

    def raise_for_approval(self, tool: str, section: str | None = None) -> None:
        """A decision is waiting: an approval nobody sees times out as a
        denial. Show the section whose chat holds the card, raise the
        window, open the side chat when it is one, and if the window was
        hidden, say so from the tray."""
        was_hidden = not self.isVisible()
        if section is not None:
            self.show_section(section)
        self.show_and_raise()
        if self.side_chat() is not None:
            self.set_panel_open(True)
        if was_hidden and self.tray is not None:
            self.tray.showMessage("Ade needs a decision", tool,
                                  QSystemTrayIcon.MessageIcon.Warning, 10000)

    # -- header -------------------------------------------------------------

    def apply_health(self, payload: dict) -> None:
        label, tone, tip = health_pill(payload)
        if label != self._last_health:
            log.info("ade os: %s -> %s (%s)", self._last_health, label,
                     tip.replace("\n", "; ")[:200])
            self._last_health = label
        self.ade_pill.set_state(label, tone, tip)

    def apply_settings(self, payload: dict) -> None:
        self.brain_label.setText(brain_name(payload))

    # -- showing, hiding, quitting -----------------------------------------

    def show_initial(self) -> None:
        if self._start_maximized:
            self.showMaximized()
        else:
            self.show()

    def show_and_raise(self) -> None:
        if self.isMinimized():
            self.showNormal()
        else:
            self.show()
        self.raise_()
        self.activateWindow()

    def closeEvent(self, event) -> None:  # noqa: N802 -- Qt's name
        if self._quitting:
            event.accept()
            return
        self.save_state()
        if self.tray_available:
            event.ignore()
            self.hide()
            return
        event.accept()
        self.quit_app()

    def unsaved(self) -> list[str]:
        """What quitting now would lose, from every section that can say."""
        lost = []
        for section in self.sections:
            ask = getattr(section.widget, "unsaved", None)
            if callable(ask):
                try:
                    lost += list(ask())
                except Exception:  # noqa: BLE001 -- asking must not stop a quit
                    log.exception("section %s could not say what is unsaved", section.name)
        return lost

    def _may_quit(self, lost: list[str]) -> bool:
        question = ("Quit Ade and lose:\n\n- " + "\n- ".join(lost))
        if self._confirm_quit is not None:
            return bool(self._confirm_quit(question))
        answer = QMessageBox.question(self, "Quit Ade?", question)
        return answer == QMessageBox.StandardButton.Yes

    def quit_app(self) -> None:
        if self._quitting:
            return
        lost = self.unsaved()
        if lost and not self._may_quit(lost):
            return                      # the review: quitting dropped unsaved edits
        self._quitting = True
        self.save_state()
        for section in self.sections:
            if section.stop is not None:
                try:
                    section.stop()
                except Exception:  # noqa: BLE001 -- quitting must finish
                    log.exception("stopping section %s failed", section.name)
        if self.orb_controller is not None:
            try:
                self.orb_controller.stop()
            except Exception:  # noqa: BLE001 -- quitting must finish
                log.exception("stopping the orb failed")
        if self.shell is not None:
            try:
                self.shell.stop_all()   # no window, no shell
            except Exception:  # noqa: BLE001 -- quitting must finish
                log.exception("stopping the shell failed")
        for chat in self.all_panels():
            for step in (chat.on_quit, chat.client.stop, chat.watcher.stop):
                try:
                    step()
                except Exception:  # noqa: BLE001 -- quitting must finish
                    log.exception("stopping a chat failed")
        self.status.stop()
        if self.tray is not None:
            self.tray.hide()
        log.info("quit")
        self._quit_fn()

    def _make_tray(self) -> QSystemTrayIcon:
        tray = QSystemTrayIcon(self.windowIcon(), self)
        menu = QMenu(self)
        menu.addAction("Show Ade", self.show_and_raise)
        menu.addSeparator()
        menu.addAction("Quit", self.quit_app)
        tray.setContextMenu(menu)
        tray.setToolTip("Ade")
        tray.activated.connect(self._on_tray_activated)
        tray.show()
        return tray

    def _on_tray_activated(self, reason) -> None:
        if reason in (QSystemTrayIcon.ActivationReason.Trigger,
                      QSystemTrayIcon.ActivationReason.DoubleClick):
            self.show_and_raise()

    # -- remembered state ---------------------------------------------------

    def save_state(self) -> None:
        g = self.normalGeometry() if self.isMaximized() else self.geometry()
        self._remember_panel_width()
        # Merged, not replaced: window.json also holds the orb's own keys.
        state = load_state(self._state_path)
        state.update({
            "x": g.x(), "y": g.y(), "w": g.width(), "h": g.height(),
            "maximized": self.isMaximized(),
            "section": self.current_section(),
            "panel_open": self.panel_open(),
            "panel_width": self._panel_width,
            "zoom": self._zoom,
            "general_split": (list(self.general_page.sizes())
                              if self.shell is not None else None),
        })
        save_state(self._state_path, state)

    def _restore_state(self) -> None:
        state = load_state(self._state_path)
        screens = _screen_rects()
        rect = rect_from_state(state)
        if rect is None:
            rect = (centred_on(screens[0], DEFAULT_W, DEFAULT_H) if screens
                    else Rect(0, 0, DEFAULT_W, DEFAULT_H))
        rect = clamp_to_screens(rect, screens)
        self.setGeometry(rect.x, rect.y, rect.w, rect.h)
        self._start_maximized = bool(state.get("maximized"))
        self._panel_width = clamp_panel_width(state.get("panel_width", PANEL_DEFAULT_W))
        self.set_zoom(state.get("zoom", 1.0))
        split = state.get("general_split")
        if (self.shell is not None and isinstance(split, list)
                and len(split) == 2 and all(isinstance(n, int) and n > 0
                                            for n in split)):
            self.general_page.setSizes(split)
        self._side_open = state.get("panel_open", True) is not False
        # Selecting the section shows (or hides) its side chat.
        names = self.section_names()
        wanted = state.get("section")
        if names:
            self.rail.setCurrentRow(names.index(wanted) if wanted in names
                                    else 0)
