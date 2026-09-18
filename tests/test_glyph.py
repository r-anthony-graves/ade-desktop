"""The glyph port: its geometry and randomness match glyph.js exactly, it
paints only inside the orb, and its colours carry offline, an approval
waiting, and the open microphone."""

import time

import pytest

from ade_desktop.orb import glyph
from ade_desktop.orb.glyph import GlyphRenderer, Look

SIZE = 380


@pytest.fixture(autouse=True)
def _qt(qapp):
    """QPixmap needs a QGuiApplication; without one the process dies silently."""
    return qapp


def test_rng_is_bit_for_bit_the_js_mulberry32():
    # reference values printed by node from glyph.js's own rng()
    r = glyph.rng(90210)
    assert [round(r(), 12) for _ in range(5)] == [
        0.281729944982, 0.736178235151, 0.921530475374, 0.171728212619, 0.761466322932]
    a = glyph.rng(31337)
    assert [round(a(), 12) for _ in range(3)] == [0.694489517715, 0.207240189891, 0.583780789515]


def test_the_figure_is_metatrons_cube():
    assert len(glyph.NODES) == 13
    assert len(glyph.EDGES) == 60
    assert len({(min(a, b), max(a, b)) for a, b, _, _ in glyph.EDGES}) == 60
    assert len(glyph.CIRCLES) == 13 and all(len(c) == 37 for c in glyph.CIRCLES)
    assert [r["turns"] for r in glyph.RINGS] == [-2, 3, -4, 5, -7]


def test_the_time_bases_close_the_loop():
    assert glyph.flow(0) == pytest.approx(0, abs=1e-12)
    assert glyph.flow(24) == pytest.approx(1, abs=1e-12)
    assert glyph.resonance(18) == pytest.approx(1.0)
    assert glyph.resonance(0) == pytest.approx(0.06)
    assert glyph.assembly(0) == 0 and glyph.assembly(10) == 1


def _frame(look, t=10.0, frames=1, dt=0.04):
    """Render with the storyboard pinned at t seconds (fully assembled)."""
    r = GlyphRenderer(epoch=1000.0 - t)
    img = None
    for i in range(frames):
        img = r.render(look, SIZE, 1000.0 + i * dt)
    return r, img


def _alpha(img, x, y):
    return img.pixelColor(x, y).alpha()


def test_it_paints_the_centre_and_leaves_the_corners_clear():
    for backing in (True, False):
        _, img = _frame(Look(online=True, backing=backing))
        for x, y in ((0, 0), (SIZE - 1, 0), (0, SIZE - 1), (SIZE - 1, SIZE - 1), (8, 8)):
            assert _alpha(img, x, y) == 0, (backing, x, y)
        assert _alpha(img, SIZE // 2, SIZE // 2) > 48


def test_the_backing_glow_fades_out_before_the_window_edge():
    _, img = _frame(Look(online=True, backing=True), t=0.0)   # nothing assembled: backing only
    assert _alpha(img, SIZE // 2, 1) == 0 and _alpha(img, 1, SIZE // 2) == 0
    assert _alpha(img, SIZE // 2, SIZE // 2) > 100


def test_offline_turns_the_core_steel():
    on, _ = _frame(Look(online=True))
    off, _ = _frame(Look(online=False))
    hot_on, hot_off = on.state()["core"][0], off.state()["core"][0]
    assert hot_on == glyph.GOLDH
    assert hot_off == glyph.mix(glyph.GOLDH, glyph.STEEL, 0.78)


def test_a_waiting_approval_turns_it_crimson_and_throws_arcs():
    r, _ = _frame(Look(online=True, pending=1), frames=40)
    hot = r.state()["core"][0]
    assert r.state()["alert"] > 0.9
    assert hot[0] > hot[1] + 100                     # crimson, not gold
    assert r.live_arcs                               # the alert sparks


def test_the_open_microphone_cools_the_figure():
    r, _ = _frame(Look(online=True, mic_open=True), frames=20)
    assert r.state()["mic_lit"] > 0.9
    r2, _ = _frame(Look(online=True, mic_open=False), frames=20)
    assert r2.state()["mic_lit"] < 0.01


def test_hearing_lifts_resonance_and_cools_the_core():
    quiet, _ = _frame(Look(online=True), frames=10)
    heard, _ = _frame(Look(online=True, hear=1.0), frames=10)
    assert heard.state()["hearing"] > 0.9
    assert heard.state()["res"] > quiet.state()["res"]
    assert heard.state()["core"][0] != quiet.state()["core"][0]


def test_the_mouth_attacks_fast_and_releases_slower():
    r, _ = _frame(Look(online=True, speak=1.0), frames=3)
    up = r.state()["speaking"]
    assert up > 0.6                                   # 3 frames at 40 ms, 35 ms attack
    for i in range(3):
        r.render(Look(online=True, speak=0.0), SIZE, 1000.12 + i * 0.04)
    down = r.state()["speaking"]
    assert up - down < up * 0.7                       # the 130 ms release keeps some


def test_a_mood_frame_sets_the_palette():
    r, _ = _frame(Look(online=True, mood={"mood": "troubled", "mode": "auto", "burst": 0.5, "tint": None}))
    assert r.state()["mood"] == "troubled"
    assert r.state()["core"][0] == glyph.ALERT


def test_the_idle_ember_is_floored_and_waits_its_ambient_turn():
    r = GlyphRenderer(epoch=990.0)
    idle = Look(online=True, mood={"mood": None, "mode": "auto", "burst": 0, "tint": None})
    sparks = 0
    prev = 0.0
    for i in range(495):                              # 19.8 s: under the shortest wait
        r.render(idle, 64, 1000.0 + i * 0.04)
        e = r.state()["ember"]
        assert e >= 0.0
        if e > prev + 0.3:
            sparks += 1
        prev = e
    assert sparks == 1                                # once, then 20-40 s of quiet
    busy = Look(online=True, mood={"mood": "thinking", "mode": "auto", "burst": 0, "tint": None})
    for i in range(300):
        r.render(busy, 64, 1030.0 + i * 0.04)
    assert r.state()["ember"] == 0.0                  # never runs negative under a mood


def test_wake_kicks_and_spawns_arcs():
    r, _ = _frame(Look(online=True))
    r.wake(1000.05)
    r.render(Look(online=True), SIZE, 1000.06)
    assert r.wake_kick() > 0.9 and len(r.live_arcs) >= 3


def test_a_whole_cycle_renders_and_a_frame_is_fast_enough():
    r = GlyphRenderer(epoch=0.0)
    looks = [Look(online=True), Look(online=True, busy=True, mic_open=True, hear=0.5),
             Look(online=True, pending=2, speak=0.8), Look(online=False)]
    times = []
    for i in range(48):
        t0 = time.perf_counter()
        r.render(looks[i % 4], SIZE, i * 0.5)         # 48 frames across the 24 s cycle
        times.append(time.perf_counter() - t0)
    times.sort()
    median = times[len(times) // 2]
    print(f"glyph frame: median {median * 1000:.1f} ms, worst {times[-1] * 1000:.1f} ms")
    assert median < 0.040
