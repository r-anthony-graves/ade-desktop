"""The VT screen, headless: no Qt, no pty, no process.

This is where the escape-sequence behaviour is pinned, because it is the
part with edges -- and pinning it here means a renderer bug and a parser
bug can never be confused for one another.
"""

from ade_desktop.shell.screen import TerminalScreen


def _line(screen, y=0) -> str:
    return "".join(c.text for c in screen.rows()[y]).rstrip()


def test_plain_text_lands_on_the_first_row():
    s = TerminalScreen(20, 3)
    s.feed("hello")
    assert _line(s) == "hello"


def test_truecolor_survives_as_hex():
    s = TerminalScreen(20, 3)
    s.feed("\x1b[38;2;255;128;0mhi\x1b[0m")
    assert s.rows()[0][0].fg == "ff8000"


def test_a_named_colour_survives_as_a_name():
    s = TerminalScreen(20, 3)
    s.feed("\x1b[31mRED")
    assert s.rows()[0][0].fg == "red"


def test_bold_and_reverse_are_carried():
    s = TerminalScreen(20, 3)
    s.feed("\x1b[1m\x1b[7mX")
    cell = s.rows()[0][0]
    assert cell.bold and cell.reverse


def test_the_cursor_is_reported_and_can_hide():
    s = TerminalScreen(20, 3)
    s.feed("abc")
    assert s.cursor() == (3, 0, False)
    s.feed("\x1b[?25l")
    assert s.cursor()[2] is True


def test_the_alternate_screen_does_not_destroy_the_primary():
    """vim, btop and less all use this. Falsify by feeding a plain
    pyte.Screen, which has no alternate-screen handling."""
    s = TerminalScreen(20, 3)
    s.feed("primary")
    s.feed("\x1b[?1049h")                  # enter the alternate screen
    s.feed("\x1b[2J\x1b[Halt")
    assert _line(s) == "alt"
    s.feed("\x1b[?1049l")                  # leave it
    assert _line(s) == "primary"


def test_resize_takes_cols_first_even_though_pyte_takes_lines_first():
    """pyte's HistoryScreen(columns, lines) and Screen.resize(lines,
    columns) are REVERSED with respect to each other. This wrapper takes
    (cols, rows) at every door and swaps in one place.

    This asserts on WRAPPING, not on s.size or len(s.rows()): those are
    built from the wrapper's own fields and from a defaultdict that invents
    blank cells for any coordinate asked of it, so they report the size
    they were told regardless of what pyte actually did. Measured
    2026-09-24: with the arguments swapped, the size assertions all still
    passed. Only where the text wraps can see through it.

    Falsify by passing the arguments straight through to pyte.
    """
    s = TerminalScreen(20, 3)
    s.resize(40, 10)
    assert s.size == (40, 10)
    s.feed("x" * 30)
    assert _line(s, 0) == "x" * 30, "wrapped early: the screen is transposed"
    assert _line(s, 1) == "", "the overflow proves only 10 columns exist"


def test_a_split_escape_sequence_is_reassembled_across_feeds():
    """A pty read can end mid-sequence. pyte's Stream is incremental; this
    pins that we rely on that rather than re-parsing each chunk alone."""
    s = TerminalScreen(20, 3)
    s.feed("\x1b[38;2;255;")
    s.feed("128;0mhi")
    assert s.rows()[0][0].fg == "ff8000"
    assert s.rows()[0][0].text == "h"


def test_windows_private_modes_do_not_raise():
    r"""pwsh opens with \x1b[?1004h (focus reporting) and \x1b[?9001h (win32
    input mode). Measured from a real spawn on this box, 2026-09-24."""
    s = TerminalScreen(20, 3)
    s.feed("\x1b[1t\x1b[c\x1b[?1004h\x1b[?9001hPS C:> ")
    assert "PS C:>" in _line(s)


def test_a_degenerate_size_is_clamped_not_crashed():
    """A widget can be 0 px wide for one layout pass. pyte divides by the
    column count, so a zero would raise mid-paint."""
    s = TerminalScreen(0, 0)
    assert s.size == (1, 1)
    s.resize(-5, -5)
    assert s.size == (1, 1)


def test_an_empty_feed_is_a_no_op():
    s = TerminalScreen(20, 3)
    s.feed("")
    assert _line(s) == ""
