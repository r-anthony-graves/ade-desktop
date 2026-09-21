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


# -- the Day tab (Task 15) ----------------------------------------------------------

from PySide6.QtCore import QObject, Qt, Signal  # noqa: E402

from ade_desktop.sections.path.panel import DOWN_NOTE, PathPanel  # noqa: E402
from tests.test_path import FakeClient as _BaseFake  # noqa: E402


class FakeClient(_BaseFake):
    """test_path's fake, plus the day's three verbs."""
    def day(self): return self._rid("day")
    def reflect(self, step, body): return self._rid("reflect", step, body)
    def mark_criteria(self, charter_id, goal, claims):
        return self._rid("mark_criteria", charter_id, goal, list(claims))


class FakeMirror(QObject):
    done = Signal(str, object)

    def __init__(self):
        super().__init__()
        self.asked = []
        self.stopped = False

    def ask(self, day_id):
        self.asked.append(day_id)
        return f"m{len(self.asked)}"

    def stop(self): self.stopped = True


REFLECTED = {**STATUS, "state": "reflected",
             "day": {**STATUS["day"], "state": "reflected",
                     "steps": {"1": "a", "2": "b", "3": "c", "4": "d"}}}


def test_the_day_tab_is_first(qapp):
    p = PathPanel(FakeClient(), mirror_client=FakeMirror())
    assert p.tabs.tabText(0) == "Day"


def test_saving_a_step_sends_it_verbatim_and_rereads(qapp):
    c = FakeClient()
    p = PathPanel(c, mirror_client=FakeMirror())
    p._got_day(STATUS)
    assert p.day_step_button.text() == "Save step 2"
    p.day_box.setPlainText("  mine \n")
    p._on_day_step()
    assert c.calls[-1] == ("reflect", 2, "  mine \n")
    c.answer("reflect", {"ok": True, "message": "Kept."})
    assert c.calls[-1] == ("day",) and p.day_box.toPlainText() == ""


def test_the_mirror_button_only_when_reflected(qapp):
    """FALSIFY: replace `can_ask_mirror(result) and` in `_got_day` with
    `True and`; the first assert fails (enabled while still reflecting)."""
    p = PathPanel(FakeClient(), mirror_client=FakeMirror())
    p._got_day(STATUS)
    assert not p.mirror_button.isEnabled()
    p._got_day(REFLECTED)
    assert p.mirror_button.isEnabled()
    q = PathPanel(FakeClient())                      # no Ade to ask: never enabled
    q._got_day(REFLECTED)
    assert not q.mirror_button.isEnabled()


def test_mark_needs_the_token_and_sends_ticked_claims(qapp):
    """FALSIFY: delete the `if not self.client.has_token(): ... return` block
    at the top of `_on_mark`; the token-message assert fails, and the claims
    would have been sent without a token."""
    c = FakeClient()
    p = PathPanel(c, mirror_client=FakeMirror())
    p._got_day({"state": "criteria_unmarked", "message": "", "orientation": None,
                "day": None, "charter": {"charter_id": "T-1", "claims": [
                    {"claim_id": "CL-1", "ordinal": 1, "category": "p", "body": "a"},
                    {"claim_id": "CL-2", "ordinal": 2, "category": "p", "body": "b"}]}})
    assert p.criteria_box.isVisibleTo(p)
    p._on_mark()
    assert "token" in p.message.text().lower()            # no token: not sent
    assert not any(x[0] == "mark_criteria" for x in c.calls)
    c.set_token("fedcba9876543210")
    p.goal_combo.setCurrentIndex(0)
    p.criteria_list.item(1).setCheckState(Qt.CheckState.Checked)
    p._on_mark()
    assert c.calls[-1] == ("mark_criteria", "T-1", "CL-1", ["CL-2"])


def test_a_mirror_ade_did_not_finish_does_not_call_the_path_down(qapp):
    c, m = FakeClient(), FakeMirror()
    p = PathPanel(c, mirror_client=m)
    p._got_day(REFLECTED)
    p._on_mirror()
    assert m.asked == ["D-1"] and not p.mirror_button.isEnabled()
    m.done.emit("m1", {"error": "ConnectError: [WinError 10061] refused"})
    assert p.status.text() != DOWN_NOTE
    assert "did not finish the mirror" in p.message.text()
    assert c.calls[-1] == ("day",)                        # the day is re-read


def test_stopping_the_panel_stops_the_mirror_client_too(qapp):
    m = FakeMirror()
    PathPanel(FakeClient(), mirror_client=m).stop_clients()
    assert m.stopped
