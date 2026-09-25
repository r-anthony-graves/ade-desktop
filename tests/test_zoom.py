"""Ctrl+= / Ctrl+- / Ctrl+0 rescale the whole app (Ray, 2026-09-24, req 3).

theme.py already stated the rule -- "the app's text sizes live in ONE
place" -- and two files broke it by importing the derived constants and
baking them into inline stylesheets that no rescale could reach. These
tests pin the rule, not just the feature.
"""

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QLabel

from ade_desktop.app import DesktopWindow
from ade_desktop.sections import Section
from ade_desktop.theme import BASE_FONT_PX, clamp_zoom, stylesheet


class FakeStatus(QObject):
    health = Signal(dict)
    settings = Signal(dict)

    def start(self): pass
    def stop(self): pass


def _win(tmp_path):
    return DesktopWindow([Section("Trader", QLabel("t"))], FakeStatus(),
                         state_path=tmp_path / "window.json",
                         tray_available=False, quit_fn=lambda: None)


def test_clamp_holds_the_range():
    assert clamp_zoom(1.0) == 1.0
    assert clamp_zoom(99) == 2.5
    assert clamp_zoom(0.01) == 0.6
    assert clamp_zoom("nonsense") == 1.0
    assert clamp_zoom(None) == 1.0


def test_the_sheet_scales_every_size():
    small = stylesheet(None, 1.0)
    big = stylesheet(None, 2.0)
    assert f"font-size: {BASE_FONT_PX}px" in small
    assert f"font-size: {BASE_FONT_PX * 2}px" in big
    assert small != big


def test_the_two_formerly_inline_labels_scale_with_it():
    """conversation/panel.py:196 and sections/path/panel.py:361 used to bake
    these into inline stylesheets. Falsify by re-inlining either one: this
    test goes red."""
    big = stylesheet(None, 2.0)
    assert "QLabel#chatHint" in big
    assert "QLabel#pathStage" in big
    assert f"font-size: {round(BASE_FONT_PX * 0.8 * 2)}px" in big    # hint
    assert f"font-size: {round(BASE_FONT_PX * 0.93 * 2)}px" in big   # small


def test_no_module_level_size_constants_remain_importable():
    """A constant that can be imported is a constant that can be inlined
    again, which is exactly how the rule was broken the first time."""
    import ade_desktop.theme as theme
    for gone in ("TITLE_FONT_PX", "SMALL_FONT_PX", "HINT_FONT_PX"):
        assert not hasattr(theme, gone), f"{gone} can still be imported and inlined"


def test_the_default_sheet_is_unchanged_at_scale_one():
    """The blast-radius fence: nobody's app looks different until they zoom."""
    assert stylesheet(None) == stylesheet(None, 1.0)
    assert stylesheet("TRADER {}", 1.0).startswith("TRADER {}")


def test_the_window_remembers_its_zoom(tmp_path, qapp):
    win = _win(tmp_path)
    win.set_zoom(1.5)
    assert win.zoom() == 1.5
    win.save_state()
    assert _win(tmp_path).zoom() == 1.5


def test_zoom_is_clamped_not_rejected(tmp_path, qapp):
    win = _win(tmp_path)
    win.set_zoom(99)
    assert win.zoom() == 2.5


def test_zoom_actually_reaches_the_applied_stylesheet(tmp_path, qapp):
    win = _win(tmp_path)
    before = win.styleSheet()
    win.set_zoom(2.0)
    assert win.styleSheet() != before
    assert f"font-size: {BASE_FONT_PX * 2}px" in win.styleSheet()


def test_zoom_changed_is_emitted_for_the_terminal(tmp_path, qapp):
    """QSS cannot style a QPainter surface, so the shell learns the new size
    from this signal. Falsify by dropping the emit: the shell then keeps its
    font while the rest of the app moves."""
    win = _win(tmp_path)
    seen = []
    win.zoom_changed.connect(seen.append)
    win.set_zoom(1.4)
    assert seen == [1.4]
    win.set_zoom(1.4)
    assert seen == [1.4], "an unchanged zoom must not re-emit"


def test_the_splitter_handles_are_visible_and_grabbable():
    """Ray, 2026-09-24: "all the areas ... need to be resizable". Two of the
    three already WERE -- theme.py just had no QSplitter rule at all, so a
    4 px handle was drawn in the default grey on a #17191d background and
    read as a gap rather than a grip.

    Falsify by deleting the QSplitter block from DESKTOP_QSS."""
    sheet = stylesheet(None)
    assert "QSplitter::handle" in sheet
    assert "QSplitter::handle:horizontal" in sheet
    assert "QSplitter::handle:vertical" in sheet
    # hover is what says "draggable" BEFORE you try to drag it
    assert "QSplitter::handle:hover" in sheet


def test_the_handle_rules_survive_a_zoom():
    """The handles are styled in DESKTOP_QSS, which is concatenated after
    the size block -- a zoom must not drop them."""
    assert "QSplitter::handle" in stylesheet(None, 2.0)
    assert "QSplitter::handle" in stylesheet("TRADER {}", 0.6)
