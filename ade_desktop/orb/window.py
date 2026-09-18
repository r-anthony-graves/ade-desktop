"""The orb: Ade's face on the desktop. A frameless, always-on-top,
transparent Tool window (no taskbar entry) that never takes keyboard focus.

It only SHOWS frames and reports the pointer; OrbController decides what is
drawn and what a click means.

Clicks go through wherever the orb is not solid enough to aim at (alpha 48
within 5 px -- the avatar's numbers). Windows passes a click through a
layered window only where alpha is exactly 0, and the backing glow is
faint over ~46% of the square (measured, review 2026-09-18), so the orb
polls the pointer ~30 times a second and flips its own WS_EX_TRANSPARENT
style: solid under the pointer = clickable, faint = the window below gets
the click. That is what Electron's setIgnoreMouseEvents does for the
avatar. A setMask() region would CLIP the painting and cut the glow off.
"""

from __future__ import annotations

import ctypes
import logging

from PySide6.QtCore import QPoint, QRect, Qt, QTimer, Signal
from PySide6.QtGui import QCursor, QGuiApplication, QImage, QPainter
from PySide6.QtWidgets import QWidget

log = logging.getLogger("ade_desktop.orb.window")

HIT_ALPHA = 48
HIT_PAD = 5
CLICK_SLOP = 6
POINTER_MS = 33
SIZES = {"S": 280, "M": 380, "L": 480}
GWL_EXSTYLE = -20
WS_EX_TRANSPARENT = 0x20


def set_input_transparent(hwnd: int, through: bool) -> bool:
    """Our own window's extended style, nobody else's. False if it could
    not be set (not Windows, or the call failed)."""
    try:
        user32 = ctypes.windll.user32
        style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        new = (style | WS_EX_TRANSPARENT) if through else (style & ~WS_EX_TRANSPARENT)
        if new != style:
            user32.SetWindowLongW(hwnd, GWL_EXSTYLE, new)
        return True
    except Exception:  # noqa: BLE001 -- clicks then behave as a plain window
        log.exception("could not set click-through")
        return False


class OrbWindow(QWidget):
    open_requested = Signal()
    menu_requested = Signal(QPoint)      # global position
    moved = Signal(int, int)             # where a drag left it

    def __init__(self, size: int = SIZES["M"], parent=None) -> None:
        super().__init__(parent, Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.WindowStaysOnTopHint
                         | Qt.WindowType.Tool
                         | Qt.WindowType.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setWindowTitle("Ade")
        self.frame: QImage | None = None
        self._press: QPoint | None = None
        self._origin: QPoint | None = None
        self._dragging = False
        self.through = False            # clicks currently pass to the window below
        self._pointer = QTimer(self)
        self._pointer.setInterval(POINTER_MS)
        self._pointer.timeout.connect(self.poll_pointer)
        self.set_orb_size(size)

    def set_orb_size(self, px: int) -> None:
        self.setFixedSize(int(px), int(px))

    def show_frame(self, img: QImage) -> None:
        self.frame = img
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 -- Qt's name
        p = QPainter(self)
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
        if self.frame is None:
            p.fillRect(self.rect(), Qt.GlobalColor.transparent)
        else:
            p.drawImage(self.rect(), self.frame)
        p.end()

    # -- hit testing --------------------------------------------------------

    def hit(self, pos: QPoint) -> bool:
        """Is there enough of the orb under `pos` (widget coordinates) to
        have aimed at?"""
        img = self.frame
        if img is None or img.isNull():
            return False
        dpr = img.devicePixelRatio() or 1.0
        cx, cy = int(pos.x() * dpr), int(pos.y() * dpr)
        pad = max(1, int(HIT_PAD * dpr))
        box = QRect(cx - pad, cy - pad, 2 * pad + 1, 2 * pad + 1).intersected(img.rect())
        step = max(1, pad // 3)
        for y in range(box.top(), box.bottom() + 1, step):
            for x in range(box.left(), box.right() + 1, step):
                if img.pixelColor(x, y).alpha() >= HIT_ALPHA:
                    return True
        return False

    # -- click-through --------------------------------------------------------

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self._pointer.start()

    def hideEvent(self, event) -> None:  # noqa: N802
        self._pointer.stop()
        super().hideEvent(event)

    def should_pass_through(self, local: QPoint) -> bool:
        """Clicks at `local` belong to the window below unless the orb is
        solid there. Never while a drag is in progress: flipping the style
        mid-grab would drop the orb."""
        if self._press is not None:
            return False
        return not (self.rect().contains(local) and self.hit(local))

    def poll_pointer(self) -> None:
        self.set_through(self.should_pass_through(self.mapFromGlobal(QCursor.pos())))

    def set_through(self, through: bool) -> None:
        if through == self.through:
            return
        self.through = through
        if QGuiApplication.platformName() == "windows":
            set_input_transparent(int(self.winId()), through)

    # -- pointer ------------------------------------------------------------

    def mousePressEvent(self, event) -> None:  # noqa: N802
        pos = event.position().toPoint()
        if not self.hit(pos):
            event.ignore()
            return
        if event.button() == Qt.MouseButton.RightButton:
            self.menu_requested.emit(event.globalPosition().toPoint())
            return
        if event.button() == Qt.MouseButton.LeftButton:
            self._press = event.globalPosition().toPoint()
            self._origin = self.pos()
            self._dragging = False

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._press is None:
            return
        delta = event.globalPosition().toPoint() - self._press
        if not self._dragging and delta.manhattanLength() >= CLICK_SLOP:
            self._dragging = True
        if self._dragging:
            self.move(self._origin + delta)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if self._press is None or event.button() != Qt.MouseButton.LeftButton:
            return
        dragged, self._press = self._dragging, None
        self._dragging = False
        if dragged:
            self.moved.emit(self.x(), self.y())
        else:
            self.open_requested.emit()
