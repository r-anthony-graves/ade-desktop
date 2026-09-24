"""A Qt key event -> the bytes a terminal sends. Pure, so it is a table."""

from PySide6.QtCore import Qt

from ade_desktop.shell.keys import sequence_for

CTRL = Qt.KeyboardModifier.ControlModifier
NONE = Qt.KeyboardModifier.NoModifier


def test_ctrl_c_is_sigint_not_a_copy():
    """A terminal's Ctrl+C interrupts the running command; copy moves to
    Ctrl+Shift+C, as in every terminal. Falsify by routing Ctrl+C to the
    clipboard in view.py -- you then cannot stop a runaway command."""
    assert sequence_for(Qt.Key.Key_C, CTRL, "\x03") == "\x03"


def test_ctrl_d_and_ctrl_z_reach_the_child():
    assert sequence_for(Qt.Key.Key_D, CTRL, "\x04") == "\x04"
    assert sequence_for(Qt.Key.Key_Z, CTRL, "\x1a") == "\x1a"


def test_enter_sends_carriage_return():
    assert sequence_for(Qt.Key.Key_Return, NONE, "\r") == "\r"
    assert sequence_for(Qt.Key.Key_Enter, NONE, "\r") == "\r"


def test_the_arrows_send_cursor_sequences():
    """PSReadLine's history and inline completion ride on these."""
    assert sequence_for(Qt.Key.Key_Up, NONE, "") == "\x1b[A"
    assert sequence_for(Qt.Key.Key_Down, NONE, "") == "\x1b[B"
    assert sequence_for(Qt.Key.Key_Right, NONE, "") == "\x1b[C"
    assert sequence_for(Qt.Key.Key_Left, NONE, "") == "\x1b[D"


def test_home_end_delete_and_the_page_keys():
    assert sequence_for(Qt.Key.Key_Home, NONE, "") == "\x1b[H"
    assert sequence_for(Qt.Key.Key_End, NONE, "") == "\x1b[F"
    assert sequence_for(Qt.Key.Key_Delete, NONE, "") == "\x1b[3~"
    assert sequence_for(Qt.Key.Key_PageUp, NONE, "") == "\x1b[5~"
    assert sequence_for(Qt.Key.Key_PageDown, NONE, "") == "\x1b[6~"


def test_tab_and_backspace():
    """Tab completion and backspace are the two most-pressed keys in a
    shell; both are special-cased rather than left to event.text()."""
    assert sequence_for(Qt.Key.Key_Tab, NONE, "\t") == "\t"
    assert sequence_for(Qt.Key.Key_Backspace, NONE, "\b") == "\x7f"


def test_the_function_keys_are_covered():
    assert sequence_for(Qt.Key.Key_F1, NONE, "") == "\x1bOP"
    assert sequence_for(Qt.Key.Key_F12, NONE, "") == "\x1b[24~"


def test_plain_text_passes_through():
    assert sequence_for(Qt.Key.Key_A, NONE, "a") == "a"
    assert sequence_for(Qt.Key.Key_Space, NONE, " ") == " "


def test_a_bare_modifier_sends_nothing():
    """Holding Ctrl before pressing C must not send a stray byte first."""
    assert sequence_for(Qt.Key.Key_Control, CTRL, "") is None
    assert sequence_for(Qt.Key.Key_Shift, NONE, "") is None
    assert sequence_for(Qt.Key.Key_CapsLock, NONE, "") is None


def test_an_unknown_key_with_no_text_sends_nothing():
    assert sequence_for(Qt.Key.Key_VolumeUp, NONE, "") is None


def test_ctrl_letters_do_not_depend_on_event_text():
    """Measured 2026-09-24: a Ctrl+C key event can arrive with text() == '',
    and the terminal then sent NOTHING at all -- Ray reported Ctrl+C not
    working. The control code is now derived from the KEY, so an empty
    text() cannot silence it.

    Falsify by returning `text or None` for Ctrl+letter: this goes red."""
    assert sequence_for(Qt.Key.Key_C, CTRL, "") == "\x03"
    assert sequence_for(Qt.Key.Key_A, CTRL, "") == "\x01"
    assert sequence_for(Qt.Key.Key_D, CTRL, "") == "\x04"
    assert sequence_for(Qt.Key.Key_Z, CTRL, "") == "\x1a"


def test_ctrl_letters_agree_with_what_qt_would_have_given():
    """The derivation must match Qt's own folding, or the two disagree
    whenever text() IS populated."""
    for key, txt in ((Qt.Key.Key_C, "\x03"), (Qt.Key.Key_D, "\x04"),
                     (Qt.Key.Key_Z, "\x1a"), (Qt.Key.Key_L, "\x0c")):
        assert sequence_for(key, CTRL, txt) == txt


def test_plain_letters_are_unaffected_by_the_ctrl_branch():
    assert sequence_for(Qt.Key.Key_C, NONE, "c") == "c"
    assert sequence_for(Qt.Key.Key_C, NONE, "C") == "C"
