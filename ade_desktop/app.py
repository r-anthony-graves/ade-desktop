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

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication, QIcon, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication, QHBoxLayout, QLabel, QListWidget, QMainWindow, QMenu,
    QMessageBox, QSplitter, QStackedWidget, QSystemTrayIcon, QToolButton,
    QVBoxLayout, QWidget,
)

from ade_desktop.ade_status import brain_name, health_pill
from ade_desktop.geometry import (
    Rect, centred_on, clamp_to_screens, load_state, rect_from_state,
    save_state,
)
from ade_desktop.sections import Section
from ade_desktop.theme import TONES, stylesheet

log = logging.getLogger("ade_desktop.app")

ICON_PATH = Path(__file__).resolve().parent.parent / "icon.png"
DEFAULT_W, DEFAULT_H = 1360, 860  # the trader window's size: its screens
                                  # were laid out for it
PANEL_MIN_W, PANEL_MAX_W, PANEL_DEFAULT_W = 280, 900, 420


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
    def __init__(self, sections: list[Section], status, *, state_path: Path,
                 tray_available: bool | None = None,
                 quit_fn: Callable[[], None] | None = None,
                 panel=None, confirm_quit=None, parent=None) -> None:
        super().__init__(parent)
        self.sections = list(sections)
        self.status = status
        self.panel = panel
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
        trader_qss = next((s.qss for s in self.sections if s.qss), None)
        self.setStyleSheet(stylesheet(trader_qss))

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
        self.panel_toggle = QToolButton()
        self.panel_toggle.setObjectName("panelToggle")
        self.panel_toggle.setToolTip("Show or hide the Ade panel (Ctrl+Shift+A)")
        self.panel_toggle.clicked.connect(self._toggle_panel)
        self.panel_toggle.setVisible(panel is not None)
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
        self.rail.currentRowChanged.connect(self.stack.setCurrentIndex)
        body.addWidget(self.rail)
        body.addWidget(self.stack, 1)
        # rail + section | the conversation panel
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setChildrenCollapsible(False)
        self.splitter.addWidget(main)
        if panel is not None:
            self.splitter.addWidget(panel)
            self.splitter.setStretchFactor(0, 1)
            self.splitter.setStretchFactor(1, 0)
            panel.approval_needed.connect(self.raise_for_approval)
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
        if self.panel is not None:
            self.panel.watcher.start()

    # -- the conversation panel ---------------------------------------------

    def panel_open(self) -> bool:
        return self.panel is not None and not self.panel.isHidden()

    def set_panel_open(self, open_: bool) -> None:
        if self.panel is None:
            return
        if open_ and self.panel.isHidden():
            self.panel.show()
            total = sum(self.splitter.sizes()) or self.width()
            width = clamp_panel_width(self._panel_width)
            self.splitter.setSizes([max(1, total - width), width])
        elif not open_ and not self.panel.isHidden():
            self._remember_panel_width()
            self.panel.hide()
        self.panel_toggle.setText("Ade ◂" if self.panel_open() else "Ade ▸")

    def _toggle_panel(self) -> None:
        self.set_panel_open(not self.panel_open())

    def _remember_panel_width(self) -> None:
        if self.panel_open():
            sizes = self.splitter.sizes()
            if len(sizes) == 2 and sizes[1] > 0:
                self._panel_width = clamp_panel_width(sizes[1])

    def raise_for_approval(self, tool: str) -> None:
        """A decision is waiting: an approval nobody sees times out as a
        denial. Show and raise the window, open the panel (it has already
        selected Chat), and if the window was hidden, say so from the tray."""
        was_hidden = not self.isVisible()
        self.show_and_raise()
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
        if self.panel is not None:
            for step in (self.panel.on_quit, self.panel.client.stop,
                         self.panel.watcher.stop):
                try:
                    step()
                except Exception:  # noqa: BLE001 -- quitting must finish
                    log.exception("stopping the panel failed")
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
        names = self.section_names()
        wanted = state.get("section")
        if names:
            self.rail.setCurrentRow(names.index(wanted) if wanted in names
                                    else 0)
        if self.panel is not None:
            self._panel_width = clamp_panel_width(
                state.get("panel_width", PANEL_DEFAULT_W))
            self.panel.hide()   # set_panel_open sizes it on the way back in
            self.set_panel_open(state.get("panel_open", True) is not False)
