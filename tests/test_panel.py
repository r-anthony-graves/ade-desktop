"""The conversation panel, offscreen, with the client and the watcher faked
through their real signal shapes and a real ThreadStore."""

import gc
import weakref

from PySide6.QtCore import QObject, Signal

from ade_desktop.conversation.panel import BUSY_NOTE, ConversationPanel
from ade_desktop.conversation.threads import ThreadStore
from ade_desktop.conversation.widgets import ApprovalCard


class FakeClient(QObject):
    done = Signal(str, object)
    line = Signal(str, str)

    def __init__(self):
        super().__init__()
        self.calls = []
        self.turn_ids = []      # the turn_id each ask / task carried
        self._n = 0

    def _rid(self, *call):
        self._n += 1
        self.calls.append(call)
        return f"r{self._n}"

    def ask(self, q, skills, history, turn_id=None):
        self.turn_ids.append(turn_id)
        return self._rid("ask", q, list(skills), list(history))

    def chat(self, text): return self._rid("chat", text)
    def task(self, text, t, skills, turn_id=None):
        self.turn_ids.append(turn_id)
        return self._rid("task", text, t, list(skills))

    def cancel(self, turn_id): return self._rid("cancel", turn_id)
    def shell(self, cmd): return self._rid("shell", cmd)
    def run(self, cmd): return self._rid("run", cmd)
    def kill(self): return self._rid("kill")
    def health(self): return self._rid("health")
    def skills(self): return self._rid("skills")
    def task_types(self): return self._rid("task_types")
    def decide(self, aid, allow): return self._rid("decide", aid, allow)
    def upload(self, files, overwrite): return self._rid("upload", len(files), overwrite)


class FakeWatcher(QObject):
    appeared = Signal(object)
    vanished = Signal(str)


def _panel(tmp_path, store=None):
    client, watcher = FakeClient(), FakeWatcher()
    store = store or ThreadStore(tmp_path / "threads.json")
    return ConversationPanel(client, watcher, store), client, watcher, store


def texts(panel, tab="chat"):
    return [m["text"] for m in panel.view_messages(tab)]


def test_an_ask_turn(qapp, tmp_path):
    panel, client, _, _ = _panel(tmp_path)
    panel.send("hello")
    assert client.calls == [("ask", "hello", [], [])]
    assert panel.busy is True
    assert "hello" in texts(panel)
    client.done.emit("r1", {"answer": "hi Ray"})
    assert panel.busy is False
    assert texts(panel)[-1] == "hi Ray"


def test_the_busy_gate_puts_the_line_back_and_sends_nothing(qapp, tmp_path):
    panel, client, _, _ = _panel(tmp_path)
    panel.send("hello")
    panel.send("again")
    assert len(client.calls) == 1
    assert panel.input.text() == "again"
    assert texts(panel)[-1] == BUSY_NOTE
    panel.send("/help")                 # /help runs while busy
    assert "/clear" in texts(panel)[-1]


def test_a_failure_restages_the_exact_line(qapp, tmp_path):
    panel, client, _, _ = _panel(tmp_path)
    panel.send("hello")
    client.done.emit("r1", {"error": "ConnectError: refused"})
    last = panel.view_messages("chat")[-1]
    assert last["kind"] == "error"
    assert "Call failed: Ade OS unreachable: ConnectError: refused" in last["text"]
    assert panel.input.text() == "hello"
    assert panel.busy is False


def test_a_bang_command_on_chat_stays_on_chat(qapp, tmp_path):
    """Found live, 2026-09-18: '!echo' on Chat switched the panel to the Shell
    tab, where PLAIN TEXT runs as PowerShell, ungated -- the next question
    ran as a command ('what : The term ... is not recognized'). A prose line
    like 'start the build' would run the `start` alias. You reach the Shell
    tab only by choosing it."""
    panel, client, _, _ = _panel(tmp_path)
    panel.send("!echo hi")
    assert panel.current_tab() == "chat"
    assert client.calls == [("shell", "echo hi")]
    client.done.emit("r1", {"ok": True, "output": "hi"})
    assert texts(panel)[-2:] == ["! echo hi", "hi"]
    panel.send("what time is it")
    assert client.calls[-1][0] == "ask"


def test_bang_still_routes_to_ade_os_s_terminal(qapp, tmp_path):
    """The Shell TAB left on 2026-09-24 (requirement 1), but `!` did not:
    `!` means "Ade, run this" on Ade OS's box, while the new shell pane is
    Ray's own keyboard on this one. Collapsing them would quietly move
    Ade's shell onto whichever machine the app is running on.

    Its answer now lands in Chat, since that is the only tab there is."""
    panel, client, _, _ = _panel(tmp_path)
    panel.send("!dir")
    assert client.calls == [("shell", "dir")]
    client.done.emit("r1", {"ok": True, "output": "a.txt"})
    assert texts(panel)[-1] == "a.txt"


def test_there_is_no_shell_tab_any_more(qapp, tmp_path):
    """Requirement 1. Falsify by restoring TABS = ("chat", "shell")."""
    import ade_desktop.conversation.panel as panel_mod
    panel, _, _, _ = _panel(tmp_path)
    assert panel_mod.TABS == ("chat",)
    assert not hasattr(panel_mod, "SHELL_LABEL")
    assert not hasattr(panel, "tabs")
    assert panel.current_tab() == "chat"


def test_a_bare_command_streams_into_chat(qapp, tmp_path):
    panel, client, _, _ = _panel(tmp_path)
    panel.send("git status")
    assert client.calls == [("run", "git status")]
    assert panel.stop_button.isVisibleTo(panel)
    client.line.emit("r1", '{"type":"out","text":"On branch main"}')
    client.line.emit("r1", '{"type":"exit","code":0}')
    client.done.emit("r1", {"ok": True})
    assert texts(panel)[-2:] == ["$ git status", "On branch main"]
    assert not panel.busy and not panel.stop_button.isVisibleTo(panel)


def test_stop_kills_the_session_and_says_so(qapp, tmp_path):
    panel, client, _, _ = _panel(tmp_path)
    panel.send("ping -t 1.1.1.1")
    client.line.emit("r1", '{"type":"out","text":"Reply"}')
    panel.stop_button.click()
    assert client.calls[-1] == ("kill",)
    client.done.emit("r1", {"ok": True, "stopped": True})
    assert texts(panel)[-1] == "Reply\n[stopped]"


def test_an_unknown_task_type_lists_the_real_ones(qapp, tmp_path):
    panel, client, _, _ = _panel(tmp_path)
    panel.send("/gpu status")
    assert client.calls == [("task", "status", "gpu", [])]
    client.done.emit("r1", {"error": {"code": "unknown_task_type",
                                      "message": "'gpu' is not a task type",
                                      "detail": {"task_types": ["coding", "qa"]}},
                            "status": 400})
    last = texts(panel)[-1]
    assert "HTTP 400: unknown_task_type" in last and "Types: coding, qa" in last
    assert panel.input.text() == "/gpu status"


def _cards(panel):
    return [w for w in panel._widgets.values() if isinstance(w, ApprovalCard)]


def test_approval_lifecycle(qapp, tmp_path):
    panel, client, watcher, _ = _panel(tmp_path)
    raised = []
    panel.approval_needed.connect(raised.append)
    panel.set_tab("shell")
    watcher.appeared.emit({"id": "a1", "tool": "write_file", "args": {"p": 1}})
    watcher.appeared.emit({"id": "a1", "tool": "write_file", "args": {"p": 1}})
    assert raised == ["write_file"]            # once, however often it polls
    assert panel.current_tab() == "chat"
    card = _cards(panel)[0]
    card.allow.click()
    assert client.calls[-1] == ("decide", "a1", True)
    client.done.emit(f"r{len(client.calls)}", {"id": "a1", "allowed": True})
    assert card.outcome.text() == "Allowed a1" and card.allow.isHidden()

    watcher.appeared.emit({"id": "a2", "tool": "run_shell", "args": {}})
    card2 = [c for c in _cards(panel) if c.approval_id == "a2"][0]
    card2.deny.click()
    client.done.emit(f"r{len(client.calls)}",
                     {"error": {"code": "already_decided"}, "status": 409})
    assert card2.outcome.text() == "Already decided elsewhere"

    watcher.appeared.emit({"id": "a3", "tool": "db_write", "args": {}})
    card3 = [c for c in _cards(panel) if c.approval_id == "a3"][0]
    card3.allow.click()
    client.done.emit(f"r{len(client.calls)}", {"error": "ConnectError: refused"})
    assert card3.allow.isEnabled()             # the buttons come back
    watcher.vanished.emit("a3")
    assert card3.outcome.text() == "Answered elsewhere"


def test_restored_approval_cards_are_never_live(qapp, tmp_path):
    store = ThreadStore(tmp_path / "threads.json")
    store.push("chat", "ade", "approval", "",
               {"approval": {"id": "old", "tool": "write_file", "args": {}}})
    store.save()
    panel, _, _, _ = _panel(tmp_path, ThreadStore(tmp_path / "threads.json"))
    card = _cards(panel)[0]
    assert card.allow.isHidden() and card.outcome.text() == "Answered elsewhere"


def test_the_render_window_and_show_earlier(qapp, tmp_path):
    store = ThreadStore(tmp_path / "threads.json")
    for i in range(350):
        store.push("chat", "user", "ask", f"q{i}")
    panel, _, _, _ = _panel(tmp_path, store)
    assert panel.rendered_count() == 300
    assert panel.earlier.text() == "Show earlier (50)"
    panel.earlier.click()
    assert panel.rendered_count() == 350
    assert panel.earlier.isHidden()


def test_superpowers_attaches_the_ade_ports(qapp, tmp_path):
    panel, client, _, store = _panel(tmp_path)
    panel.send("/superpowers")
    rows = [{"name": n, "attachable": True} for n in
            ("brainstorming", "ade-brainstorming", "writing-plans",
             "ade-writing-plans", "using-superpowers")]
    client.done.emit("r1", {"skills": rows})
    assert store.skills == ["using-superpowers", "ade-brainstorming",
                            "ade-writing-plans"]
    assert [b.property("skill") for b in panel.chips.chip_buttons()] == store.skills


def test_search_sends_no_history(qapp, tmp_path):
    panel, client, _, store = _panel(tmp_path)
    store.push("chat", "user", "ask", "earlier question")
    store.push("chat", "ade", "ask", "earlier answer")
    panel.send("/search what is QVM")
    assert client.calls == [("ask", "what is QVM", [], [])]


def test_quit_mid_turn_leaves_a_note(qapp, tmp_path):
    panel, _, _, store = _panel(tmp_path)
    panel.send("hello")
    panel.on_quit()
    saved = ThreadStore(tmp_path / "threads.json")
    assert "still running when the app quit" in saved.chat[-1]["text"]


def _live_cards(panel):
    return [m for m in panel.view_messages("chat") if m["kind"] == "approval"
            and not m["meta"].get("decided") and not m["meta"].get("moot")]


def test_nothing_clears_away_a_pending_approval(qapp, tmp_path):
    """Review finding (HIGH): /clear, a clear-like line and an escalate-clear
    archived the card, and the approval then timed out into a denial."""
    panel, client, watcher, _ = _panel(tmp_path)
    watcher.appeared.emit({"id": "a9", "tool": "write_file", "args": {}})
    panel.send("/clear")
    panel.send("new chat")
    panel.send("please clear it all")
    client.done.emit(f"r{len(client.calls)}",
                     {"answer": "", "escalate": {"prompt": "clear the chat"}})
    assert [m["meta"]["approval"]["id"] for m in _live_cards(panel)] == ["a9"]
    assert _cards(panel) and _cards(panel)[0].allow.isEnabled()


def test_a_decision_in_flight_survives_a_rerender(qapp, tmp_path):
    """Review finding: switching tabs rebuilt the card with live buttons,
    so one approval could be answered twice."""
    panel, client, watcher, _ = _panel(tmp_path)
    watcher.appeared.emit({"id": "a1", "tool": "write_file", "args": {}})
    _cards(panel)[0].allow.click()
    panel.set_tab("shell")
    panel.set_tab("chat")
    card = _cards(panel)[0]
    assert card.allow.isHidden() and card.deny.isHidden()
    assert "Sending" in card.outcome.text()
    decides = [c for c in client.calls if c[0] == "decide"]
    assert decides == [("decide", "a1", True)]
    client.done.emit(f"r{len(client.calls)}", {"id": "a1", "allowed": True})
    assert _cards(panel)[0].outcome.text() == "Allowed a1"


def test_a_failed_decision_brings_the_buttons_back_even_after_a_rerender(qapp, tmp_path):
    panel, client, watcher, _ = _panel(tmp_path)
    watcher.appeared.emit({"id": "a1", "tool": "write_file", "args": {}})
    _cards(panel)[0].deny.click()
    panel.set_tab("shell")
    panel.set_tab("chat")
    client.done.emit(f"r{len(client.calls)}", {"error": "ConnectError: refused"})
    card = _cards(panel)[0]
    assert card.allow.isEnabled() and card.deny.isEnabled()


def test_a_failure_keeps_a_draft_typed_during_the_turn(qapp, tmp_path):
    panel, client, _, _ = _panel(tmp_path)
    panel.send("hello")
    panel.input.setText("my next thought")
    client.done.emit("r1", {"error": "ConnectError: refused"})
    assert panel.input.text() == "my next thought"
    assert "hello" in texts(panel)[-1]      # the failed line is still shown


def test_ask_history_keeps_an_earlier_unanswered_question(qapp, tmp_path):
    """The avatar pushes the question, THEN drops the trailing user line.
    Building history first dropped an EARLIER unanswered question instead."""
    panel, client, _, store = _panel(tmp_path)
    store.push("chat", "user", "ask", "q-old")
    panel.send("new q")
    assert client.calls[0][3] == [{"role": "user", "content": "q-old"}]


def test_a_failed_stop_is_reported(qapp, tmp_path):
    panel, client, _, _ = _panel(tmp_path)
    panel.send("ping -t 1.1.1.1")
    panel.stop_button.click()
    kill_rid = f"r{len(client.calls)}"
    client.done.emit(kill_rid, {"error": "ConnectError: refused"})
    assert any("Stop failed" in t for t in texts(panel))


def test_a_stream_without_an_exit_frame_says_so(qapp, tmp_path):
    panel, client, _, _ = _panel(tmp_path)
    panel.send("git log")
    client.line.emit("r1", '{"type":"out","text":"abc"}')
    client.done.emit("r1", {"ok": True})
    assert texts(panel)[-1] == "abc\n[stream ended without an exit code]"


def test_a_stream_error_after_output_is_marked(qapp, tmp_path):
    panel, client, _, _ = _panel(tmp_path)
    panel.send("git log")
    client.line.emit("r1", '{"type":"out","text":"abc"}')
    client.done.emit("r1", {"error": "RemoteProtocolError: peer closed"})
    assert texts(panel)[-1].startswith("abc\n[stream ended: ")


def test_a_stream_error_before_any_output_restages(qapp, tmp_path):
    panel, client, _, _ = _panel(tmp_path)
    panel.send("git status")
    client.done.emit("r1", {"error": "ConnectError: refused"})
    kinds = [m["kind"] for m in panel.view_messages("chat")]
    assert "inline" not in kinds and kinds[-1] == "error"
    assert panel.input.text() == "git status"


def test_a_shell_reply_that_reports_an_error_is_a_reply(qapp, tmp_path):
    """/v1/terminal answers 200 {ok:false, error:...} for a command that
    failed -- that is the command's answer, not a failed call."""
    panel, client, _, _ = _panel(tmp_path)
    panel.send("!sleep 99")
    client.done.emit("r1", {"ok": False, "output": "", "error": "timed out after 30s"})
    assert texts(panel)[-1] == "timed out after 30s"
    assert panel.view_messages("chat")[-1]["kind"] == "shell"
    assert panel.input.text() == ""


def test_an_upload_waits_for_the_turn(qapp, tmp_path):
    panel, client, _, _ = _panel(tmp_path)
    f = tmp_path / "a.txt"
    f.write_text("x")
    panel.send("hello")
    panel.upload_paths([str(f)])
    assert [c[0] for c in client.calls] == ["ask"]
    assert texts(panel)[-1] == BUSY_NOTE


def test_a_dropped_panel_is_freed_at_once(qapp, tmp_path):
    """The piece-1 lesson: no lambda may capture the panel, or it becomes
    garbage the collector tears down at a random moment."""
    client, watcher = FakeClient(), FakeWatcher()
    store = ThreadStore(tmp_path / "threads.json")
    gc.collect()
    gc.disable()
    try:
        panel = ConversationPanel(client, watcher, store)
        panel.send("hello")
        watcher.appeared.emit({"id": "z", "tool": "write_file", "args": {}})
        ref = weakref.ref(panel)
        del panel
        assert ref() is None, "the panel survived its last reference"
    finally:
        gc.enable()



def test_a_real_task_reply_is_not_a_failure(qapp, tmp_path):
    """Ade OS's /v1/tasks reply ALWAYS carries `error` -- null on success.
    Reading the key's presence as failure made every /type task a
    "Call failed" (found by the piece-5 review)."""
    panel, client, _, _ = _panel(tmp_path)
    panel.send("/test run the unit tests")
    client.done.emit("r1", {"task_id": "t-1", "ok": True, "summary": "All 40 passed.",
                            "artifacts": [], "tool_calls": 3, "error": None,
                            "mission_id": "m", "state": "complete", "progress": 1.0,
                            "confidence": 0.95, "degraded": False})
    msgs = panel.view_messages("chat")
    assert msgs[-1]["kind"] == "task" and msgs[-1]["text"] == "All 40 passed."
    assert not any("Call failed" in (m.get("text") or "") for m in msgs)


def test_a_task_that_ran_and_failed_says_so_without_restaging(qapp, tmp_path):
    panel, client, _, _ = _panel(tmp_path)
    panel.send("/test run the unit tests")
    client.done.emit("r1", {"task_id": "t-2", "ok": False, "summary": "stopped early",
                            "error": "max rounds", "degraded": True})
    msg = panel.view_messages("chat")[-1]
    assert msg["kind"] == "error" and "did not succeed: max rounds" in msg["text"]
    assert panel.input.text() == ""


# -- Cancel (Ray, 2026-09-18: "add a cancel chat request") ---------------------

def test_an_ask_can_be_cancelled_and_ade_is_told_to_stop(qapp, tmp_path):
    panel, client, _, _ = _panel(tmp_path)
    panel.send("summarise the repo")
    tid = client.turn_ids[-1]
    assert tid and panel.owns_turn(tid)
    assert panel.stop_button.isVisibleTo(panel) and panel.stop_button.text() == "Cancel"
    panel.stop_button.click()
    assert client.calls[-1] == ("cancel", tid)
    assert not panel.busy and not panel.stop_button.isVisibleTo(panel)
    assert not panel.owns_turn(tid)
    assert "Cancelled" in texts(panel)[-1] and "next step" in texts(panel)[-1]
    client.done.emit("r1", {"answer": "the late answer", "ok": True})
    assert "the late answer" not in texts(panel)          # the reply is dropped


def test_a_task_can_be_cancelled_too(qapp, tmp_path):
    panel, client, _, _ = _panel(tmp_path)
    panel.send("/coding fix the build")
    tid = client.turn_ids[-1]
    panel.stop_button.click()
    assert client.calls[-1] == ("cancel", tid) and not panel.busy


def test_every_ask_has_its_own_turn(qapp, tmp_path):
    panel, client, _, _ = _panel(tmp_path)
    panel.send("one")
    client.done.emit("r1", {"answer": "a", "ok": True})
    panel.send("two")
    assert len(set(client.turn_ids)) == 2 and None not in client.turn_ids


def test_a_plain_chat_cancel_only_stops_waiting_and_says_so(qapp, tmp_path):
    panel, client, _, _ = _panel(tmp_path)
    panel.send("?what brain are you on")
    panel.stop_button.click()
    assert not any(c[0] == "cancel" for c in client.calls)
    assert not panel.busy
    assert "may still finish" in texts(panel)[-1]


def test_a_new_question_can_follow_a_cancel_at_once(qapp, tmp_path):
    panel, client, _, _ = _panel(tmp_path)
    panel.send("first")
    panel.stop_button.click()
    panel.send("second")
    assert client.calls[-1][:2] == ("ask", "second") and panel.busy


def test_a_cancel_that_cannot_reach_ade_says_it_may_still_run(qapp, tmp_path):
    panel, client, _, _ = _panel(tmp_path)
    panel.send("first")
    panel.stop_button.click()
    client.done.emit(f"r{len(client.calls)}", {"error": "ConnectError: refused"})
    assert "may still be running" in texts(panel)[-1]


def test_a_streamed_command_still_stops_with_stop(qapp, tmp_path):
    panel, client, _, _ = _panel(tmp_path)
    panel.send("ping -t 1.1.1.1")
    assert panel.stop_button.text() == "Stop"


def test_an_upload_has_no_cancel(qapp, tmp_path):
    panel, client, _, _ = _panel(tmp_path)
    f = tmp_path / "a.txt"
    f.write_text("x")
    panel.upload_paths([str(f)])
    assert panel.busy and not panel.stop_button.isVisibleTo(panel)


# -- the spinner, in the chat itself (Ray, 2026-09-18: "return the spinners to chat area") --

def _spinners(panel, tab="chat"):
    return [m for m in panel.store.tab_messages(tab) if m.get("kind") == "working"]


def test_a_turn_shows_a_spinner_in_the_chat_until_the_reply_lands(qapp, tmp_path):
    from ade_desktop.conversation.spin import WORDS
    panel, client, _, _ = _panel(tmp_path)
    panel.send("summarise the repo")
    spin = _spinners(panel)
    assert len(spin) == 1 and spin[0]["id"] in panel._widgets          # drawn in the thread
    word = spin[0]["text"].split("…")[0]
    assert word in WORDS
    client.done.emit("r1", {"answer": "Here it is.", "ok": True})
    assert _spinners(panel) == [] and "Here it is." in texts(panel)
    assert spin[0]["id"] not in panel._widgets


def test_the_spinner_counts_the_seconds_and_changes_word_as_the_avatar_did(
        qapp, tmp_path, monkeypatch):
    from ade_desktop.conversation import panel as panel_module
    from ade_desktop.conversation.spin import ROTATE_S
    clock = [1000.0]
    monkeypatch.setattr(panel_module.time, "monotonic", lambda: clock[0])
    panel, client, _, _ = _panel(tmp_path)
    panel.send("long question")
    first = _spinners(panel)[0]["text"]
    clock[0] += 12
    panel._on_tick()
    text = _spinners(panel)[0]["text"]
    assert text.startswith(first.split("…")[0]) and text.endswith("… 12 s")
    assert panel._widgets[_spinners(panel)[0]["id"]].text() == text     # redrawn
    clock[0] += ROTATE_S
    panel._on_tick()
    assert _spinners(panel)[0]["text"].split("…")[0] != first.split("…")[0]


def test_cancel_takes_the_spinner_away(qapp, tmp_path):
    panel, client, _, _ = _panel(tmp_path)
    panel.send("long question")
    panel.stop_button.click()
    assert _spinners(panel) == []


def test_the_spinner_is_never_saved_or_sent_as_history(qapp, tmp_path):
    import json
    panel, client, _, store = _panel(tmp_path)
    panel.send("first question")
    store.save()
    saved = json.loads((tmp_path / "threads.json").read_text(encoding="utf-8"))
    assert not any(m.get("kind") == "working" for m in saved["chat"])
    client.done.emit("r1", {"answer": "answer one", "ok": True})
    panel.send("second question")
    history = client.calls[-1][3]
    assert [h["content"] for h in history] == ["first question", "answer one"]


def test_the_working_line_below_the_thread_is_gone(qapp, tmp_path):
    panel, client, _, _ = _panel(tmp_path)
    panel.send("a question")
    assert not hasattr(panel, "working_label")
    assert panel.stop_button.isVisibleTo(panel)            # Cancel stays below
