"""The terminal widget. No pty is started here -- start() is the only thing
that spawns a process, and these tests drive the view directly."""

from PySide6.QtGui import QColor

from ade_desktop.shell.view import BACKGROUND, FOREGROUND, TerminalView, colour


def _line(view, y=0) -> str:
    return "".join(c.text for c in view.screen.rows()[y]).rstrip()


def _shown(view):
    view.resize(800, 400)
    view.show()
    return view


# -- the colour table -------------------------------------------------------

def test_named_colours_resolve():
    assert colour("red", FOREGROUND) == QColor("#d95757")
    assert colour("brightblue", FOREGROUND) == QColor("#79b4ef")


def test_pyte_calls_ansi_33_brown_not_yellow():
    """A palette keyed on "yellow" renders pyte's brown as the default
    foreground and nobody notices until the output looks flat."""
    assert colour("brown", FOREGROUND) != FOREGROUND


def test_truecolor_hex_resolves():
    assert colour("ff8000", FOREGROUND) == QColor("#ff8000")


def test_default_and_nonsense_fall_back_rather_than_raise():
    """A bad colour must not stop the paint mid-frame."""
    assert colour("default", FOREGROUND) == FOREGROUND
    assert colour("", FOREGROUND) == FOREGROUND
    assert colour("zzzzzz", FOREGROUND) == FOREGROUND
    assert colour("nosuchcolour", BACKGROUND) == BACKGROUND


# -- geometry ---------------------------------------------------------------

def test_it_sizes_the_screen_from_its_pixels(qapp):
    view = _shown(TerminalView())
    qapp.processEvents()
    cols, rows = view.screen.size
    assert cols > 10 and rows > 5


def test_zoom_changes_the_grid_and_tells_the_pty(qapp):
    """Requirement 3 reaches the terminal, but QSS cannot style a QPainter
    surface, so the zoom arrives by signal and MUST be forwarded to
    setwinsize -- a running btop that is not told keeps drawing at the old
    size. Falsify by removing session.resize() from _apply_grid."""
    view = _shown(TerminalView())
    qapp.processEvents()
    sent = []
    view.session.resize = lambda c, r: sent.append((c, r))
    before = view.screen.size
    view.set_font_px(30)
    qapp.processEvents()
    assert view.screen.size != before
    assert sent, "the pty was never told the new size"
    assert sent[-1] == view.screen.size


def test_the_same_font_size_is_a_no_op(qapp):
    view = _shown(TerminalView())
    qapp.processEvents()
    sent = []
    view.session.resize = lambda c, r: sent.append((c, r))
    view.set_font_px(view.font_px())
    assert sent == []


# -- output -----------------------------------------------------------------

def test_output_reaches_the_screen(qapp):
    view = _shown(TerminalView())
    qapp.processEvents()
    view._on_output("hello")
    view.flush()
    assert "hello" in _line(view)


def test_output_is_batched_not_painted_per_chunk(qapp):
    """A command printing 100k lines must not repaint 100k times. The Code
    terminal learned this at FLUSH_MS=50; the same bar applies here."""
    view = _shown(TerminalView())
    qapp.processEvents()
    for i in range(500):
        view._on_output(f"line {i}\r\n")
    assert view.pending_chunks() == 500, "it painted per chunk instead of batching"
    view.flush()
    assert view.pending_chunks() == 0


def test_a_flood_says_so_on_screen(qapp):
    """Dropping output is defensible; dropping it silently is a lie about
    what the command printed. Falsify by removing the marker from flush()."""
    view = _shown(TerminalView())
    qapp.processEvents()
    view._on_output("x" * 400_000)
    view.flush()
    assert view.dropped_bytes() > 0
    text = "\n".join("".join(c.text for c in row) for row in view.screen.rows())
    assert "dropped to keep up" in text


def test_normal_output_reports_nothing_dropped(qapp):
    view = _shown(TerminalView())
    qapp.processEvents()
    view._on_output("a modest amount of output\r\n" * 100)
    view.flush()
    assert view.dropped_bytes() == 0


def test_flush_with_nothing_pending_is_safe(qapp):
    view = _shown(TerminalView())
    view.flush()
    assert view.pending_chunks() == 0


# -- painting ---------------------------------------------------------------

def test_it_paints_without_raising(qapp):
    """Offscreen still exercises paintEvent through render(). A raise here
    would be an exception per frame in the real app."""
    from PySide6.QtGui import QPixmap

    view = _shown(TerminalView())
    qapp.processEvents()
    view._on_output("\x1b[38;2;255;128;0mcolour\x1b[0m \x1b[1mbold\x1b[0m\r\n")
    view.flush()
    pixmap = QPixmap(view.size())
    view.render(pixmap)
    assert not pixmap.isNull()


def test_the_terminal_asks_for_a_real_size(qapp):
    """A bare QWidget has NO sizeHint, and QSplitter's initial split comes
    from sizeHint -- setStretchFactor only distributes EXTRA space on a
    resize. Measured 2026-09-24: without this the shell pane opened 94 px
    tall inside a 756 px column and the terminal got 49 px -- three rows.
    Ray saw a tab strip and a sliver, and reported the shell as not opening.

    Falsify by deleting sizeHint(): this goes red and the pane collapses."""
    view = TerminalView()
    cell_h = view.sizeHint().height() / 24    # the hint IS 24 rows
    hint = view.sizeHint()
    assert hint.width() > 400, hint
    assert hint.height() >= 20 * cell_h, hint
    floor = view.minimumSizeHint()
    assert floor.height() >= 4 * cell_h, floor    # never squashed to nothing
    assert floor.height() < hint.height(), "a floor at the hint cannot shrink"


def test_the_hint_follows_the_font(qapp):
    """Zoom in and the terminal should ask for more room, not the same."""
    view = TerminalView()
    small = view.sizeHint().height()
    view.set_font_px(30)
    assert view.sizeHint().height() > small
