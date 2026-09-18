"""A remembered position from a monitor that is no longer there must not
open the window where nobody can see it -- the avatar shipped exactly that
bug."""

from ade_desktop.geometry import (
    Rect, centred_on, clamp_to_screens, load_state, rect_from_state,
    save_state, state_dir,
)

PRIMARY = Rect(0, 0, 1920, 1040)
LEFT = Rect(-2560, 0, 2560, 1400)


def test_a_rectangle_on_a_screen_is_kept():
    r = Rect(100, 100, 1360, 860)
    assert clamp_to_screens(r, [PRIMARY]) == r


def test_a_rectangle_on_the_second_screen_is_kept():
    r = Rect(-2400, 100, 1360, 860)
    assert clamp_to_screens(r, [PRIMARY, LEFT]) == r


def test_a_rectangle_on_a_vanished_monitor_moves_to_the_primary():
    r = Rect(-2400, 100, 1360, 860)  # the left monitor is gone
    moved = clamp_to_screens(r, [PRIMARY])
    assert moved == Rect(280, 90, 1360, 860)


def test_a_sliver_is_not_enough():
    r = Rect(1880, 100, 1360, 860)  # 40 px on screen: less than 100
    assert clamp_to_screens(r, [PRIMARY]) == Rect(280, 90, 1360, 860)


def test_a_window_bigger_than_the_screen_is_shrunk_to_fit():
    small = Rect(0, 0, 1280, 720)
    moved = clamp_to_screens(Rect(5000, 5000, 1360, 860), [small])
    assert moved == Rect(0, 0, 1280, 720)


def test_no_screens_means_unchanged():
    r = Rect(5, 5, 10, 10)
    assert clamp_to_screens(r, []) == r


def test_centred_on():
    assert centred_on(PRIMARY, 1360, 860) == Rect(280, 90, 1360, 860)


def test_state_round_trips(tmp_path):
    path = tmp_path / "sub" / "window.json"
    save_state(path, {"x": 1, "y": 2, "w": 3, "h": 4, "section": "Trader"})
    assert load_state(path)["section"] == "Trader"
    assert rect_from_state(load_state(path)) == Rect(1, 2, 3, 4)


def test_a_corrupt_file_gives_defaults(tmp_path):
    path = tmp_path / "window.json"
    path.write_text("{not json", encoding="utf-8")
    assert load_state(path) == {}
    path.write_text("[1, 2]", encoding="utf-8")
    assert load_state(path) == {}
    assert load_state(tmp_path / "missing.json") == {}


def test_rect_from_state_rejects_partial_or_bad_values():
    assert rect_from_state({}) is None
    assert rect_from_state({"x": 1, "y": 2, "w": 3}) is None
    assert rect_from_state({"x": "a", "y": 2, "w": 3, "h": 4}) is None


def test_state_dir_override_and_default(monkeypatch, tmp_path):
    monkeypatch.setenv("ADE_DESKTOP_STATE_DIR", str(tmp_path))
    assert state_dir() == tmp_path
    monkeypatch.delenv("ADE_DESKTOP_STATE_DIR")
    monkeypatch.setenv("APPDATA", str(tmp_path / "roaming"))
    assert state_dir() == tmp_path / "roaming" / "ade-desktop"
