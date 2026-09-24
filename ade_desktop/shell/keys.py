"""One Qt key event -> what a terminal actually sends. Pure: no widget, no
pty, so the table is testable on its own.

Ctrl+C must reach the CHILD -- it is how you stop a runaway command, and a
terminal that copies instead is a terminal you cannot interrupt. So copy
and paste move to Ctrl+Shift+C / Ctrl+Shift+V, the same trade every
terminal makes. view.py handles those two before calling here.
"""

from __future__ import annotations

from PySide6.QtCore import Qt

# The sequences xterm sends, which is what PSReadLine and every TUI expect.
_SPECIAL = {
    Qt.Key.Key_Up: "\x1b[A",
    Qt.Key.Key_Down: "\x1b[B",
    Qt.Key.Key_Right: "\x1b[C",
    Qt.Key.Key_Left: "\x1b[D",
    Qt.Key.Key_Home: "\x1b[H",
    Qt.Key.Key_End: "\x1b[F",
    Qt.Key.Key_PageUp: "\x1b[5~",
    Qt.Key.Key_PageDown: "\x1b[6~",
    Qt.Key.Key_Insert: "\x1b[2~",
    Qt.Key.Key_Delete: "\x1b[3~",
    Qt.Key.Key_Return: "\r",
    Qt.Key.Key_Enter: "\r",
    Qt.Key.Key_Tab: "\t",
    Qt.Key.Key_Backtab: "\x1b[Z",
    Qt.Key.Key_Backspace: "\x7f",
    Qt.Key.Key_Escape: "\x1b",
    Qt.Key.Key_F1: "\x1bOP",
    Qt.Key.Key_F2: "\x1bOQ",
    Qt.Key.Key_F3: "\x1bOR",
    Qt.Key.Key_F4: "\x1bOS",
    Qt.Key.Key_F5: "\x1b[15~",
    Qt.Key.Key_F6: "\x1b[17~",
    Qt.Key.Key_F7: "\x1b[18~",
    Qt.Key.Key_F8: "\x1b[19~",
    Qt.Key.Key_F9: "\x1b[20~",
    Qt.Key.Key_F10: "\x1b[21~",
    Qt.Key.Key_F11: "\x1b[23~",
    Qt.Key.Key_F12: "\x1b[24~",
}

# A bare modifier press sends nothing. Without this, holding Ctrl to type
# Ctrl+C would send a stray byte first.
_MODIFIER_KEYS = frozenset({
    Qt.Key.Key_Control, Qt.Key.Key_Shift, Qt.Key.Key_Alt, Qt.Key.Key_Meta,
    Qt.Key.Key_CapsLock, Qt.Key.Key_NumLock, Qt.Key.Key_ScrollLock,
    Qt.Key.Key_AltGr,
})


def sequence_for(key, modifiers, text: str) -> str | None:
    """None means "send nothing"."""
    if key in _MODIFIER_KEYS:
        return None
    special = _SPECIAL.get(key)
    if special is not None:
        return special
    # Ctrl+<letter> is mapped HERE rather than trusted to event.text().
    # Qt is documented to fold it into a control character (Ctrl+C -> \x03)
    # and usually does -- but measured 2026-09-24, a Ctrl+C event can arrive
    # with text() == '', and then this returned None and the terminal sent
    # NOTHING. Deriving it from the key code cannot have that failure.
    if modifiers & Qt.KeyboardModifier.ControlModifier:
        code = int(key)
        if Qt.Key.Key_A <= key <= Qt.Key.Key_Z:
            return chr(code - int(Qt.Key.Key_A) + 1)      # Ctrl+A..Z -> 1..26
        if key == Qt.Key.Key_BracketLeft:
            return "\x1b"
        if key == Qt.Key.Key_Backslash:
            return "\x1c"
        if key == Qt.Key.Key_BracketRight:
            return "\x1d"
    return text or None
