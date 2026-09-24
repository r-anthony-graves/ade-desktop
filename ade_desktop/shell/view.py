"""The terminal widget: paint the screen buffer, send the keys.

Output is BATCHED on a member timer (50 ms), never painted per chunk: a
command printing 100k lines must not repaint 100k times. That is the bar
`sections/code/terminal.py` already met (FLUSH_MS = 50, MAX_LINES =
10_000), and this replaces it.

The timer is a MEMBER QTimer, never QTimer.singleShot(0, self.method): a
pending single-shot holds its bound method -- and so this widget -- alive
until it fires. Measured 2026-09-18, and the dropped-panel test caught it.
Nothing here captures `self` in a lambda, for the same reason.

The zoom arrives by SIGNAL rather than through QSS, because a QPainter
surface cannot be styled. It must be forwarded to the pty as well as
applied here: a running btop that is not told the new size keeps drawing at
the old one.
"""

from __future__ import annotations

from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtGui import QColor, QFontDatabase, QFontMetricsF, QPainter
from PySide6.QtWidgets import QApplication, QWidget

from ade_desktop.shell.keys import sequence_for
from ade_desktop.shell.pty import PtySession
from ade_desktop.shell.screen import TerminalScreen

FLUSH_MS = 50
DEFAULT_FONT_PX = 15
BACKGROUND = QColor("#0f1115")
FOREGROUND = QColor("#d6d9de")
CURSOR = QColor("#4f8cc9")

# pyte's own colour names. Note `brown`, not `yellow` -- pyte calls ANSI 33
# brown, and a palette keyed on "yellow" silently renders it as the default
# foreground.
PALETTE = {
    "black": "#1a1d23", "red": "#d95757", "green": "#3fb68b",
    "brown": "#d9a441", "blue": "#4f8cc9", "magenta": "#b07cc6",
    "cyan": "#49b5c4", "white": "#d6d9de",
    "brightblack": "#5c626b", "brightred": "#ff8a8a",
    "brightgreen": "#6fe0b4", "brightbrown": "#ffc96b",
    "brightblue": "#79b4ef", "brightmagenta": "#d5a6e8",
    "brightcyan": "#7fe0ee", "brightwhite": "#ffffff",
}

_HEX = frozenset("0123456789abcdefABCDEF")


def colour(name: str, default: QColor) -> QColor:
    """pyte gives either a NAME or a 6-digit hex string (256-colour and
    truecolor both arrive as hex). Anything unrecognised falls back rather
    than raising: a bad colour must not stop the paint."""
    if not name or name == "default":
        return default
    hit = PALETTE.get(name)
    if hit is not None:
        return QColor(hit)
    if len(name) == 6 and all(c in _HEX for c in name):
        return QColor("#" + name)
    return default


class TerminalView(QWidget):
    exited = Signal(int)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("terminalView")
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        self.setCursor(Qt.CursorShape.IBeamCursor)
        self._font_px = DEFAULT_FONT_PX
        self._font = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        self._font.setPixelSize(self._font_px)
        self._metrics = QFontMetricsF(self._font)
        self._pending: list[str] = []
        self._dropped = 0
        self.screen = TerminalScreen(80, 24)
        # NOT parented to this widget, deliberately. A closed tab calls
        # deleteLater(), and Qt would then destroy a child PtySession while
        # its reader thread is still inside self.output.emit() -- emitting
        # from a destroyed sender is an access violation, not an exception.
        # Unparented, the session outlives the widget until the reader
        # thread drops its last reference, and Qt has already broken the
        # connection to this (destroyed) receiver, so the emit goes nowhere
        # instead of into freed memory.
        self.session = PtySession()
        self.session.output.connect(self._on_output)
        self.session.exited.connect(self.exited)
        self._flush_timer = QTimer(self)
        self._flush_timer.setSingleShot(True)
        self._flush_timer.setInterval(FLUSH_MS)
        self._flush_timer.timeout.connect(self.flush)

    # -- geometry -----------------------------------------------------------

    def _cell(self) -> tuple[float, float]:
        return (max(1.0, self._metrics.horizontalAdvance("M")),
                max(1.0, self._metrics.height()))

    def grid(self) -> tuple[int, int]:
        cw, ch = self._cell()
        return max(1, int(self.width() // cw)), max(1, int(self.height() // ch))

    def _apply_grid(self) -> None:
        cols, rows = self.grid()
        if (cols, rows) == self.screen.size:
            return
        self.screen.resize(cols, rows)
        self.session.resize(cols, rows)     # or a running btop keeps the old size
        self.update()

    def resizeEvent(self, event) -> None:       # noqa: N802 -- Qt's name
        super().resizeEvent(event)
        self._apply_grid()

    def set_font_px(self, px: int) -> None:
        """Requirement 3 reaches the terminal. QSS cannot style a QPainter
        surface, so the zoom arrives here -- and the new grid MUST go to the
        pty, which is what _apply_grid does."""
        px = max(6, int(px))
        if px == self._font_px:
            return
        self._font_px = px
        self._font.setPixelSize(px)
        self._metrics = QFontMetricsF(self._font)
        self._apply_grid()
        self.update()

    def font_px(self) -> int:
        return self._font_px

    # -- lifetime -----------------------------------------------------------

    def start(self) -> None:
        cols, rows = self.grid()
        self.screen.resize(cols, rows)
        self.session.start(cols=cols, rows=rows)

    def stop(self) -> None:
        self._flush_timer.stop()
        self.session.stop()

    def title(self) -> str:
        return "PowerShell"

    # -- output -------------------------------------------------------------

    def pending_chunks(self) -> int:
        return len(self._pending)

    def _on_output(self, text: str) -> None:
        self._pending.append(text)
        if not self._flush_timer.isActive():
            self._flush_timer.start()

    def flush(self) -> None:
        self._flush_timer.stop()
        if not self._pending:
            return
        text, self._pending = "".join(self._pending), []
        dropped = self.screen.feed(text)
        if dropped:
            # Say so. A silent gap is a lie about what the command printed.
            self._dropped += dropped
            self.screen.feed(
                f"\r\n[{dropped // 1024} KB of output dropped to keep up]\r\n")
        self.update()

    def dropped_bytes(self) -> int:
        return self._dropped

    # -- input --------------------------------------------------------------

    def keyPressEvent(self, event) -> None:     # noqa: N802 -- Qt's name
        mods = event.modifiers()
        ctrl = bool(mods & Qt.KeyboardModifier.ControlModifier)
        shift = bool(mods & Qt.KeyboardModifier.ShiftModifier)
        key = event.key()
        if ctrl and shift and key == Qt.Key.Key_V:
            self.session.write(QApplication.clipboard().text())
            return
        if ctrl and shift and key == Qt.Key.Key_C:
            return                              # copy; selection lands later
        data = sequence_for(key, mods, event.text())
        if data is not None:
            self.session.write(data)
        # Nothing is echoed locally: the shell echoes, as a terminal expects.

    def wheelEvent(self, event) -> None:        # noqa: N802 -- Qt's name
        steps = event.angleDelta().y() // 120
        if steps:
            self.screen.scroll(-steps)
            self.update()

    # -- painting -----------------------------------------------------------

    def paintEvent(self, event) -> None:        # noqa: N802 -- Qt's name
        painter = QPainter(self)
        painter.fillRect(self.rect(), BACKGROUND)
        cw, ch = self._cell()
        ascent = self._metrics.ascent()
        for y, row in enumerate(self.screen.rows()):
            top = y * ch
            for x, cell in enumerate(row):
                fg = colour(cell.fg, FOREGROUND)
                bg = colour(cell.bg, BACKGROUND)
                if cell.reverse:
                    fg, bg = bg, fg
                if bg != BACKGROUND:
                    painter.fillRect(int(x * cw), int(top),
                                     int(cw) + 1, int(ch) + 1, bg)
                if cell.text and cell.text != " ":
                    self._font.setBold(cell.bold)
                    self._font.setUnderline(cell.underline)
                    painter.setFont(self._font)
                    painter.setPen(fg)
                    painter.drawText(int(x * cw), int(top + ascent), cell.text)
        cx, cy, hidden = self.screen.cursor()
        if not hidden:
            painter.fillRect(int(cx * cw), int(cy * ch),
                             max(2, int(cw)), int(ch), CURSOR)
        painter.end()
