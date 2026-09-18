"""The orb: Ade's face on the desktop. A frameless, always-on-top,
transparent Tool window (no taskbar entry) that never takes keyboard focus.

It only SHOWS frames and reports the pointer; OrbController decides what is
drawn and what a click means. Transparent pixels belong to the window
below: Windows hit-tests a per-pixel-alpha (layered) window by its alpha,
so a fully clear pixel passes the click through with no mask at all -- a
setMask() region would also CLIP the painting and cut the glow off. Inside
the painted area, a press counts only where the frame is solid enough to
aim at (alpha 48 within 5 px -- the avatar's numbers); a faint pixel
ignores it.
"""

from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, Qt, Signal
from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import QWidget

HIT_ALPHA = 48
HIT_PAD = 5
CLICK_SLOP = 6
SIZES = {"S": 280, "M": 380, "L": 480}


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
