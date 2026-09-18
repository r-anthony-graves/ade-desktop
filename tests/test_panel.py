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
        self._n = 0

    def _rid(self, *call):
        self._n += 1
        self.calls.append(call)
        return f"r{self._n}"

    def ask(self, q, skills, history): return self._rid("ask", q, list(skills), list(history))
    def chat(self, text): return self._rid("chat", text)
    def task(self, text, t, skills): return self._rid("task", text, t, list(skills))
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


def test_the_shell_tab_is_labelled_and_routes_to_the_terminal(qapp, tmp_path):
    panel, client, _, _ = _panel(tmp_path)
    panel.set_tab("shell")
    assert "NOT gated" in panel.route_label.text()
    panel.send("dir")
    assert client.calls == [("shell", "dir")]
    client.done.emit("r1", {"ok": True, "output": "a.txt"})
    assert texts(panel, "shell")[-1] == "a.txt"


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
