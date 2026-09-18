"""The Path section: a client of The Path's JSON face that owns none of its
rules. The token is Ray's -- held only after he pastes it, in memory,
sent only on his two verbs, never on a read, never persisted or logged."""

import gc
import json
import logging
import weakref

import pytest
from PySide6.QtCore import QObject, Signal

from ade_desktop.sections.path.client import TOKEN_HEADER, PathClient, path_base
from ade_desktop.sections.path.panel import DOWN_NOTE, PathPanel, today_text

TOKEN = "fedcba9876543210"

# ------------------------------------------------------------------ client


def _recording():
    calls = []

    def request(method, url, body, timeout, headers=None):
        calls.append((method, url, body, headers))
        return {"message": "x", "ok": True}

    return calls, request


def test_the_token_goes_only_on_ray_s_two_verbs(qapp, pump):
    calls, request = _recording()
    c = PathClient("http://path", request=request)
    assert c.set_token("  " + TOKEN + "  ") is True
    c.today(); c.read_entries(); c.diary(); c.stage(); c.study(); c.catalogue()
    c.teaching("t 1")
    c.write_entry("hello"); c.write_diary("d", "reflection"); c.offer()
    c.record_prompt("mine", "cit-1", "awareness", "o"); c.draft_teaching("T", "S")
    c.add_claim("t 1", "interpretation", "b", ["c1"], ["d1", "d2"])
    c.set_stage("wisdom"); c.confirm("t 1")
    assert pump(lambda: len(calls) == 15)
    with_token = sorted(u for m, u, b, h in calls if h)
    assert with_token == ["http://path/api/stage", "http://path/api/teaching/t%201/confirm"]
    assert all(h == {TOKEN_HEADER: TOKEN} for m, u, b, h in calls if h)
    assert all(m == "GET" and h is None for m, u, b, h in calls if m == "GET")
    claim = next(b for m, u, b, h in calls if u.endswith("/claim"))
    assert claim == {"category": "interpretation", "body": "b", "cites": ["c1"],
                     "drawn_from": ["d1", "d2"]}


def test_a_gated_verb_with_no_token_carries_no_header(qapp, pump):
    calls, request = _recording()
    c = PathClient("http://path", request=request)
    c.set_stage("wisdom")
    assert pump(lambda: bool(calls))
    assert calls[0][3] is None


def test_forget_clears_it_and_it_is_never_in_a_repr(qapp):
    c = PathClient("http://path")
    c.set_token(TOKEN)
    assert c.has_token() and TOKEN not in repr(c)
    assert c.set_token("t\u00f6ken") is False and c.has_token()   # not a token: kept the old
    c.forget_token()
    assert not c.has_token()


def test_the_base_is_the_path_s_own_port_or_the_override(monkeypatch):
    monkeypatch.delenv("ADE_DESKTOP_PATH_URL", raising=False)
    assert path_base() == "http://127.0.0.1:8412"
    monkeypatch.setenv("ADE_DESKTOP_PATH_URL", "http://127.0.0.1:9999/")
    assert path_base() == "http://127.0.0.1:9999"

# ------------------------------------------------------------------- panel


class FakeClient(QObject):
    done = Signal(str, object)

    def __init__(self):
        super().__init__()
        self.calls = []
        self.token = ""
        self.base = "http://path"

    def _rid(self, *call):
        self.calls.append(call)
        return f"p{len(self.calls)}"

    def answer(self, verb, result):
        idx = max(i for i, c in enumerate(self.calls) if c[0] == verb)
        self.done.emit(f"p{idx + 1}", result)

    def set_token(self, t): self.token = (t or "").strip()
    def forget_token(self): self.token = ""
    def has_token(self): return bool(self.token)
    def stop(self): pass
    def today(self): return self._rid("today")
    def read_entries(self): return self._rid("read")
    def diary(self): return self._rid("diary")
    def stage(self): return self._rid("stage")
    def study(self): return self._rid("study")
    def catalogue(self): return self._rid("catalogue")
    def teaching(self, tid): return self._rid("teaching", tid)
    def write_entry(self, body, kind=""): return self._rid("entry", body)
    def write_diary(self, body, kind=""): return self._rid("diary_write", body, kind)
    def offer(self): return self._rid("offer")
    def record_prompt(self, *a): return self._rid("prompt", *a)
    def draft_teaching(self, t, s): return self._rid("draft", t, s)
    def add_claim(self, *a): return self._rid("claim", *a)
    def set_stage(self, s): return self._rid("set_stage", s)
    def confirm(self, tid): return self._rid("confirm", tid)


TODAY = {"stage": "awareness", "summary": "a quiet day", "prompt": None,
         "source": {"stage": "awareness", "citation_id": "cit-9",
                    "attribution": "Johnson, The History of the Yorubas (1921)",
                    "passage": "The first paragraph.", "passage_2": "The second.",
                    "occasion": "o", "kind": "writing_prompt"},
         "entries": [{"written_at": "2026-09-18T09:00:00", "kind": "reflection",
                      "body": "morning"}],
         "lesson": None, "cycle": None, "answered": 0, "of": 30, "thought": None,
         "thought_source": None, "offer_open": True}


@pytest.fixture
def rig(qapp):
    c = FakeClient()
    panel = PathPanel(c)
    panel.refresh()
    c.answer("today", TODAY)
    c.answer("stage", {"stage": "awareness", "stages": ["awareness", "wisdom"], "is_ray": False})
    return panel, c


def test_a_server_that_does_not_answer_says_how_to_start_it(qapp):
    c = FakeClient()
    panel = PathPanel(c)
    panel.refresh()
    c.answer("today", {"error": "ConnectError: [WinError 10061] refused"})
    assert panel.status.text() == DOWN_NOTE and not panel.tabs.isEnabled()
    assert "thepath serve" in DOWN_NOTE and "never starts it" in DOWN_NOTE


def test_today_is_the_path_s_answer_as_plain_text(rig):
    panel, c = rig
    text = panel.today_view.toPlainText()
    assert "Stage: awareness" in text and "Johnson, The History of the Yorubas (1921)" in text
    assert "The first paragraph." in text and "The second." in text
    assert panel.record_button.isVisibleTo(panel) and not panel.offer_button.isEnabled()


def test_the_source_s_attribution_is_never_dropped():
    text = today_text({**TODAY, "source": {**TODAY["source"], "passage": None}})
    assert "Johnson" in text and "we do not hold its text" in text


def test_an_entry_writes_then_rereads_today_and_read(rig):
    panel, c = rig
    panel.entry_box.setPlainText("What I noticed.")
    panel.entry_button.click()
    assert c.calls[-1] == ("entry", "What I noticed.")
    c.answer("entry", {"message": "Written. It is immutable now.", "ok": True})
    assert panel.message.text() == "Written. It is immutable now."
    assert [x[0] for x in c.calls[-2:]] == ["today", "read"]


def test_recording_rests_the_prompt_on_the_offered_citation(rig):
    panel, c = rig
    panel.prompt_box.setPlainText("In my words")
    panel.record_button.click()
    assert c.calls[-1] == ("prompt", "In my words", "cit-9", "awareness", "o")


def test_the_stage_is_not_sent_without_a_token(rig):
    panel, c = rig
    panel.stage_combo.setCurrentText("wisdom")
    panel.stage_button.click()
    assert not any(x[0] == "set_stage" for x in c.calls)
    assert "is yours" in panel.message.text()


def test_with_a_token_the_stage_is_sent_and_the_path_s_refusal_shown(rig):
    panel, c = rig
    panel.token_box.setText(TOKEN)
    panel.use_token.click()
    assert c.token == TOKEN and panel.token_box.text() == ""       # not left in the widget
    panel.stage_combo.setCurrentText("wisdom")
    panel.stage_button.click()
    assert c.calls[-1] == ("set_stage", "wisdom")
    c.answer("set_stage", {"error": "Advancing the stage is Ray's (spec §46)", "status": 403})
    assert "§46" in panel.message.text()
    panel.forget.click()
    assert c.token == "" and panel.token_state.text() == "no token"


def test_the_token_travels_only_where_it_must_and_is_logged_nowhere(qapp, pump, caplog,
                                                                    tmp_path, monkeypatch):
    """The REAL client and the real HTTP stack against a local server that
    records what arrives: the header only on the two gated POSTs, and no
    log line anywhere (httpx included, at DEBUG) carrying the token. The
    desktop's own window.json never holds it either."""
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    seen = []

    class H(BaseHTTPRequestHandler):
        def _answer(self):
            n = int(self.headers.get("Content-Length") or 0)
            if n:
                self.rfile.read(n)
            seen.append((self.command, self.path, self.headers.get(TOKEN_HEADER)))
            data = b'{"message": "ok", "ok": true}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        do_GET = do_POST = _answer

        def log_message(self, *a):
            pass

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    caplog.set_level(logging.DEBUG)
    monkeypatch.setenv("ADE_DESKTOP_STATE_DIR", str(tmp_path))
    try:
        c = PathClient("http://127.0.0.1:%d" % srv.server_address[1])
        c.set_token(TOKEN)
        c.today(); c.stage(); c.write_entry("x"); c.set_stage("wisdom"); c.confirm("t1")
        assert pump(lambda: len(seen) == 5, timeout=10)
    finally:
        srv.shutdown()
        srv.server_close()
    carried = sorted(p for m, p, h in seen if h)
    assert carried == ["/api/stage", "/api/teaching/t1/confirm"]
    assert all(h in (None, TOKEN) for _, _, h in seen)
    assert all(m == "POST" for m, p, h in seen if h)
    assert TOKEN not in caplog.text
    assert not any(TOKEN in f.read_text(errors="ignore") for f in tmp_path.rglob("*")
                   if f.is_file())


def test_quit_forgets_the_token(qapp):
    c = FakeClient()
    panel = PathPanel(c)
    panel.token_box.setText(TOKEN)
    panel.use_token.click()
    panel.stop_clients()
    assert c.token == ""


def test_a_teaching_opens_takes_a_claim_and_confirm_is_gated(rig):
    panel, c = rig
    c.answer("study", {"guide": {"stage": "awareness", "turn": 1},
                       "teachings": [{"teaching_id": "t1", "title": "On thresholds",
                                      "status": "draft"}]})
    panel.teaching_list.setCurrentRow(0)
    assert c.calls[-1] == ("teaching", "t1")
    c.answer("teaching", {"teaching": {"teaching_id": "t1", "title": "On thresholds",
                                       "subject": "s", "status": "draft", "version": 1,
                                       "claims": []},
                          "categories": ["interpretation", "attested"], "is_ray": False})
    panel.claim_body.setText("A claim")
    panel.claim_cites.setText("c1, c2")
    panel.claim_button.click()
    assert c.calls[-1] == ("claim", "t1", "interpretation", "A claim", ["c1", "c2"], [])
    panel.confirm_button.click()
    assert not any(x[0] == "confirm" for x in c.calls)


def test_a_dropped_panel_is_freed_at_once(qapp):
    panel = PathPanel(FakeClient())
    ref = weakref.ref(panel)
    gc.disable()
    try:
        del panel
        assert ref() is None
    finally:
        gc.enable()



# -- the review's findings (2026-09-18) --------------------------------------------

@pytest.mark.parametrize("error", [
    {"error": "The Path's database is not answering: x", "status": 503},
    {"error": "no teaching 'T-x'", "status": 404}])
def test_a_running_path_that_answers_an_error_is_not_called_down(rig, error):
    panel, c = rig
    panel.refresh()
    c.answer("today", error)
    assert panel.status.text() != DOWN_NOTE and panel.tabs.isEnabled()
    assert "Could not read Today" in panel.today_view.toPlainText()


def test_only_no_answer_at_all_is_down(qapp):
    from ade_desktop.sections.path.panel import _unreachable
    assert _unreachable({"error": "ConnectError: [WinError 10061] refused"})
    assert _unreachable({"error": "ReadTimeout: timed out"})
    assert not _unreachable({"error": "UnicodeEncodeError: 'ascii' codec"})
    assert not _unreachable({"error": "x", "status": 503})


def test_a_failed_write_keeps_what_was_typed(rig):
    panel, c = rig
    panel.entry_box.setPlainText("Keep me.")
    panel.entry_button.click()
    assert panel.entry_box.toPlainText() == "Keep me."          # not cleared on send
    c.answer("entry", {"error": "The Path's database is not answering: x", "status": 503})
    assert panel.entry_box.toPlainText() == "Keep me."
    panel.entry_button.click()
    c.answer("entry", {"message": "Written. It is immutable now.", "ok": True})
    assert panel.entry_box.toPlainText() == ""


def test_a_refused_write_keeps_it_too(rig):
    panel, c = rig
    panel.diary_box.setPlainText("   x")
    panel.diary_button.click()
    c.answer("diary_write", {"message": "Nothing to write.", "ok": False})
    assert panel.diary_box.toPlainText() == "   x"


def test_record_and_offer_follow_the_page_s_rule(qapp):
    c = FakeClient()
    panel = PathPanel(c)
    panel.refresh()
    # a source (the lesson's) and no prompt: record it, no Offer -- even
    # with no live offer, as views.today does
    c.answer("today", {**TODAY, "offer_open": False})
    assert panel.record_button.isVisibleTo(panel) and not panel.offer_button.isEnabled()
    panel.refresh()                              # each answer to its own read
    c.answer("today", {**TODAY, "source": None, "offer_open": False})
    assert not panel.record_button.isVisibleTo(panel) and panel.offer_button.isEnabled()
    panel.refresh()
    c.answer("today", {**TODAY, "prompt": {"text": "mine"}})
    assert not panel.record_button.isVisibleTo(panel) and not panel.offer_button.isEnabled()


def test_the_attribution_is_the_page_s_plain_reading():
    text = today_text({**TODAY, "source_plain": "Johnson, The History of the Yorubas, p. 12",
                       "source": {**TODAY["source"],
                                  "attribution": "Johnson, The History [ed-99] p. 12 "
                                                 "(insider, primary)"}})
    assert "Johnson, The History of the Yorubas, p. 12" in text
    assert "[ed-99]" not in text and "(insider, primary)" not in text


def test_the_path_s_words_are_shown_as_text_never_as_markup(rig):
    panel, c = rig
    from PySide6.QtCore import Qt
    for label in (panel.message, panel.status, panel.stage_label, panel.token_state):
        assert label.textFormat() == Qt.TextFormat.PlainText
    panel.entry_box.setPlainText("x")
    panel.entry_button.click()
    c.answer("entry", {"message": "Offered from <b>Bold</b>", "ok": True})
    assert panel.message.text() == "Offered from <b>Bold</b>"


def test_a_pasted_non_token_is_refused_and_says_why(qapp):
    panel = PathPanel(PathClient("http://path"))
    panel.token_box.setText("t\u00f6ken")
    panel.use_token.click()
    assert not panel.client.has_token() and "not a token" in panel.message.text()
