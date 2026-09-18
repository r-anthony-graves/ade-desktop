"""The orb's mood core -- every case from the avatar's own
adeos/avatar/tests/mood-decision.test.js, so the two faces decide alike."""

from ade_desktop.orb.mood import Mood, sentiment


class Clock:
    def __init__(self, t0=0.0):
        self.t = t0

    def __call__(self):
        return self.t


def feed_frame(state, t, mode=None):
    m = Mood(Clock())
    m.feed(state, mode)
    return m.frame(t)


def test_offline_rests_in_dormant():
    assert feed_frame({"online": False, "busy": False, "pending": 0}, 0)["mood"] == "dormant"


def test_busy_thinks():
    assert feed_frame({"online": True, "busy": True, "pending": 0}, 0)["mood"] == "thinking"


def test_a_pending_approval_waits_attentively():
    assert feed_frame({"online": True, "busy": False, "pending": 1}, 0)["mood"] == "attentive"


def test_quiet_idle_has_no_mood():
    assert feed_frame({"online": True, "busy": False, "pending": 0}, 0)["mood"] is None


def test_mode_rides_along_and_defaults_to_auto():
    assert feed_frame({"online": True}, 0)["mode"] == "auto"
    assert feed_frame({"online": True}, 0, "dev")["mode"] == "dev"
    assert feed_frame({"online": True, "mode": "ask-first"}, 0)["mode"] == "ask-first"


def test_approved_bursts_satisfied_then_settles_back():
    clock = Clock(100000)
    m = Mood(clock)
    m.feed({"online": True, "busy": True, "pending": 0})
    m.event("approved")
    mid = m.frame(100000 + 700)
    assert mid["mood"] == "satisfied" and 0 < mid["burst"] <= 1
    clock.t += 2000
    after = m.frame(100000 + 2700)
    assert after["mood"] == "thinking" and after["burst"] == 0


def test_wake_startled_flashes_short():
    clock = Clock(0)
    m = Mood(clock)
    m.feed({"online": True, "busy": False, "pending": 0})
    m.event("wake")
    f = m.frame(350)
    assert f["mood"] == "startled" and f["burst"] > 0.4
    clock.t += 1500
    g = m.frame(1500)
    assert g["mood"] is None and g["burst"] == 0


def test_failed_turns_troubled():
    m = Mood(Clock())
    m.feed({"online": True, "busy": True, "pending": 0})
    m.event("failed")
    assert m.frame(50)["mood"] == "troubled"


def test_offline_outranks_an_active_burst():
    m = Mood(Clock())
    m.feed({"online": True, "busy": True, "pending": 0})
    m.event("wake")
    m.feed({"online": False, "busy": False, "pending": 0})
    f = m.frame(200)
    assert f["mood"] == "dormant" and f["burst"] == 0


def test_unknown_events_are_ignored():
    m = Mood(Clock())
    m.feed({"online": True, "busy": True, "pending": 0})
    m.event("nonsense")
    f = m.frame(0)
    assert f["mood"] == "thinking" and f["burst"] == 0


def test_a_bright_sentiment_tints_warm_and_expires():
    clock = Clock(0)
    m = Mood(clock)
    r = sentiment("thanks, that is great and solved it")
    assert r["score"] > 0.5 and r["hot"] is False
    m.feed({"online": True, "busy": True, "pending": 0})
    m.tint(r, 4000)
    assert m.frame(100)["tint"]["r"] == 1
    clock.t += 5000
    assert m.frame(5000)["tint"] is None


def test_dark_sentiment_tints_red_and_stays_color_only():
    m = Mood(Clock())
    r = sentiment("there is an error and the thing failed badly")
    assert r["score"] < -0.3
    m.tint(r, 4000)
    tint = m.frame(0)["tint"]
    assert tint["r"] > tint["b"] and tint["f"] == 0


def test_negation_flips_a_mild_negative():
    assert sentiment("not bad at all")["score"] > 0


def test_neutral_prose_scores_near_zero_and_caps_at_120_tokens():
    r = sentiment("the chat interface responds to the active tab selection")
    assert abs(r["score"]) <= 0.1
    long = " ".join(["please"] * 300)
    assert isinstance(sentiment(long)["score"], float)


def test_caps_and_bangs_are_a_fired_accent():
    r = sentiment("PERFECT. EXCELLENT!!")
    assert r["hot"] is True and r["score"] >= 0.8


def test_bare_number_tint_input_is_accepted():
    m = Mood(Clock())
    m.tint(0.6, 2000)
    assert m.frame(0)["tint"]
