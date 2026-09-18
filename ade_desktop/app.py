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

from PySide6.QtGui import QGuiApplication, QIcon
from PySide6.QtWidgets import (
    QApplication, QHBoxLayout, QLabel, QListWidget, QMainWindow, QMenu,
    QStackedWidget, QSystemTrayIcon, QVBoxLayout, QWidget,
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
                 parent=None) -> None:
        super().__init__(parent)
        self.sections = list(sections)
        self.status = status
        self._state_path = Path(state_path)
        self._quit_fn = quit_fn or QApplication.quit
        self._quitting = False
        self._last_health: str | None = None
        self._start_maximized = False

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
        outer.addWidget(header)

        body = QHBoxLayout()
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
        outer.addLayout(body, 1)
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

    def start(self) -> None:
        self.status.start()
        for section in self.sections:
            if section.start is not None:
                section.start()

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

    def quit_app(self) -> None:
        if self._quitting:
            return
        self._quitting = True
        self.save_state()
        for section in self.sections:
            if section.stop is not None:
                try:
                    section.stop()
                except Exception:  # noqa: BLE001 -- quitting must finish
                    log.exception("stopping section %s failed", section.name)
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
        save_state(self._state_path, {
            "x": g.x(), "y": g.y(), "w": g.width(), "h": g.height(),
            "maximized": self.isMaximized(),
            "section": self.current_section(),
        })

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
