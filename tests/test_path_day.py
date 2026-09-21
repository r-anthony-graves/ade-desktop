"""The Day tab's pure parts and its calls. The token rides only on Ray's
verbs -- now three."""
from ade_desktop.sections.path.client import TOKEN_HEADER, PathClient
from ade_desktop.sections.path.day import can_ask_mirror, day_text, next_step
from ade_desktop.sections.path.mirror import mirror_body

STATUS = {"state": "reflecting", "message": "", "charter": None,
          "orientation": {"chain": {"path_goal": "Standing rightly.", "stage": "awareness",
                                    "stage_number": 1, "stages_total": 10, "attempt": 1,
                                    "cycle_goal": "below the chop"},
                          "day_number": 3, "of": 30, "legacy": 2, "mirrored": 0,
                          "coverage": [{"body": "hold then release", "days": 0},
                                       {"body": "the estuary", "days": 1}]},
          "day": {"day_id": "D-1", "state": "reflecting",
                  "preview": {"topic": "Holding, then Releasing", "text": "Today looks…",
                              "estimate": {"reading": 4, "refract": 4, "reflect": 12,
                                           "total": 20}},
                  "objective": "Notice one moment.", "criterion": {"body": "hold then release"},
                  "read": {"attribution": "Ellis (1894)", "standpoint": "outsider",
                           "passage": "Olokun holds…"},
                  "across": [{"attribution": "Goetia", "standpoint": "insider_tradition",
                              "passage": "Vepar raises…"}],
                  "split": {"text": "One restrains.", "cause": "different_context"},
                  "lenses": {"literal": "a", "symbolic": "b", "psychological": "c",
                             "practical": "d"},
                  "life": [{"quote": "held my tongue", "charter_claim": "#9"}],
                  "questions": {"1": "What does the text say?", "2": "Which?",
                                "3": "Where?", "4": "One act?"},
                  "steps": {"1": "It says…"}, "mirror": None}}


def test_the_preview_comes_first_and_the_time_is_shown():
    text = day_text(STATUS)
    assert text.index("Holding, then Releasing") < text.index("WHY TODAY")
    assert "20 minutes" in text and "reading ~4" in text


def test_the_chain_and_map_are_shown():
    text = day_text(STATUS)
    for s in ("Standing rightly.", "below the chop", "hold then release",
              "day 3 of 30", "2 legacy"):
        assert s in text


def test_the_next_step_and_the_mirror_button():
    assert next_step(STATUS) == 2
    assert not can_ask_mirror(STATUS)
    done = {**STATUS, "state": "reflected",
            "day": {**STATUS["day"], "state": "reflected",
                    "steps": {"1": "a", "2": "b", "3": "c", "4": "d"}}}
    assert next_step(done) is None and can_ask_mirror(done)


def test_an_unmarked_charter_says_what_to_do():
    text = day_text({"state": "criteria_unmarked", "message": "criteria_unmarked: …",
                     "orientation": None, "day": None,
                     "charter": {"charter_id": "T-1", "claims": []}})
    assert "mark" in text.lower()


def test_the_mirror_goes_to_the_companion():
    body = mirror_body("D-1")
    assert body["agent"] == "companion" and "the-path-mirror" in body["description"]
    assert "D-1" in body["description"]


def test_mark_criteria_carries_the_token_and_reflect_does_not(qapp, pump):
    """FALSIFY: remove `gated=True` from mark_criteria's `_post` call in
    client.py; this fails (`gated` comes back empty)."""
    calls = []

    def request(method, url, body, timeout, headers=None):
        calls.append((url, body, headers))
        return {"ok": True, "message": "x"}

    c = PathClient("http://path", request=request)
    c.set_token("fedcba9876543210")
    c.day(); c.reflect(1, " typed "); c.mark_criteria("T-1", "CL-g", ["CL-1", "CL-2"])
    assert pump(lambda: len(calls) == 3)
    gated = [u for u, b, h in calls if h]
    assert gated == ["http://path/api/charter/criteria"]
    assert calls[1][1] == {"step": "1", "body": " typed "}
    assert calls[2][2] == {TOKEN_HEADER: "fedcba9876543210"}
