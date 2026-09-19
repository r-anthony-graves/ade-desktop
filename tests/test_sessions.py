"""A chat per section (Ray, 2026-09-18: "create chat sessions for each so
chats dont overlap"): each section's chat has its own thread file, Ade OS
topic and terminal session, and an approval reaches only the chat whose
turn raised it -- General gets the rest."""

import gc
import weakref

from PySide6.QtCore import QObject, Signal

from ade_desktop.conversation.client import SESSION, TOPIC
from ade_desktop.conversation.sessions import GENERAL, ApprovalRouter, session_for


def test_general_keeps_today_s_thread_topic_and_terminal():
    g = session_for(GENERAL)
    assert (g.threads_file, g.topic, g.terminal) == ("threads.json", TOPIC, SESSION)


def test_every_section_has_a_chat_of_its_own():
    specs = [session_for(n) for n in ("Trader", "PM", "QA", "Path", "Code")]
    assert len({s.threads_file for s in specs} | {"threads.json"}) == 6
    assert len({s.topic for s in specs} | {TOPIC}) == 6
    assert len({s.terminal for s in specs} | {SESSION}) == 6
    pm = session_for("PM")
    assert (pm.threads_file, pm.topic, pm.terminal) == (
        "threads-pm.json", "u/local/desktop-pm", "ade-desktop-chat-pm")


def test_the_code_chat_never_shares_the_code_terminal_pane_s_session():
    from ade_desktop.sections.code.client import SESSION as CODE_PANE
    assert session_for("Code").terminal != CODE_PANE


def test_a_name_becomes_a_safe_slug():
    assert session_for("My Section / 2").slug == "my-section-2"


class FakeSource(QObject):
    appeared = Signal(object)
    vanished = Signal(str)

    def __init__(self):
        super().__init__()
        self.started = self.stopped = 0

    def start(self): self.started += 1
    def stop(self): self.stopped += 1
    def pending_count(self): return 7


class Chat:
    def __init__(self, turn=None):
        self.turn = turn

    def owns_turn(self, turn_id):
        return bool(turn_id) and turn_id == self.turn


def _router():
    source = FakeSource()
    router = ApprovalRouter(source)
    chats = {GENERAL: Chat(), "PM": Chat("t-pm"), "QA": Chat("t-qa")}
    got = {}
    for name, chat in chats.items():
        w = router.watcher_for(name)
        got[name] = []
        w.appeared.connect(lambda a, n=name: got[n].append(("appeared", a["id"])))
        w.vanished.connect(lambda i, n=name: got[n].append(("vanished", i)))
        router.bind(name, chat)
    return source, router, chats, got


def test_an_approval_reaches_only_the_chat_whose_turn_raised_it():
    source, router, chats, got = _router()
    source.appeared.emit({"id": "a1", "turn_id": "t-pm", "tool": "write_file"})
    assert got == {GENERAL: [], "PM": [("appeared", "a1")], "QA": []}
    source.vanished.emit("a1")
    assert got["PM"] == [("appeared", "a1"), ("vanished", "a1")] and got[GENERAL] == []


def test_anything_no_chat_owns_goes_to_general_once():
    source, router, chats, got = _router()
    source.appeared.emit({"id": "w1", "turn_id": None, "tool": "run_shell"})
    source.appeared.emit({"id": "x1", "turn_id": "someone-elses", "tool": "run_shell"})
    source.appeared.emit({"id": "old", "tool": "run_shell"})          # an older Ade OS
    assert got[GENERAL] == [("appeared", "w1"), ("appeared", "x1"), ("appeared", "old")]
    assert got["PM"] == got["QA"] == []


def test_a_vanish_follows_where_the_card_went_even_after_the_turn_ends():
    source, router, chats, got = _router()
    source.appeared.emit({"id": "a1", "turn_id": "t-qa"})
    chats["QA"].turn = None                                  # its turn ended meanwhile
    source.vanished.emit("a1")
    assert got["QA"] == [("appeared", "a1"), ("vanished", "a1")]


def test_the_one_source_is_started_and_stopped_once_and_counts_for_all():
    source, router, chats, got = _router()
    for name in chats:
        router.watcher_for(name).start()
    assert source.started == 1
    for name in chats:
        router.watcher_for(name).stop()
    assert source.stopped == 1
    assert router.watcher_for("PM").pending_count() == 7


def test_the_router_never_keeps_a_chat_alive(qapp):
    from PySide6.QtWidgets import QLabel

    source = FakeSource()
    router = ApprovalRouter(source)

    class Panel(QLabel):
        def owns_turn(self, turn_id):
            return False

    panel = Panel("chat")
    panel.watcher = router.watcher_for("PM")
    router.bind("PM", panel)
    ref = weakref.ref(panel)
    gc.disable()
    try:
        del panel
        assert ref() is None
    finally:
        gc.enable()
    source.appeared.emit({"id": "late", "turn_id": "t"})     # goes to General, no crash


# -- the chats really do not overlap ------------------------------------------------

class _Client(QObject):
    done = Signal(str, object)
    line = Signal(str, str)

    def __init__(self, tag):
        super().__init__()
        self.tag, self.calls, self.turn_ids, self._n = tag, [], [], 0

    def _rid(self, *call):
        self._n += 1
        self.calls.append(call)
        return f"{self.tag}{self._n}"

    def ask(self, q, skills, history, turn_id=None):
        self.turn_ids.append(turn_id)
        return self._rid("ask", q, list(history))

    def cancel(self, turn_id): return self._rid("cancel", turn_id)


def _two_chats(tmp_path):
    from ade_desktop.conversation.panel import ConversationPanel
    from ade_desktop.conversation.threads import ThreadStore

    source = FakeSource()
    router = ApprovalRouter(source)
    chats = {}
    for name in (GENERAL, "PM"):
        spec = session_for(name)
        client = _Client(spec.slug)
        chat = ConversationPanel(client, router.watcher_for(name),
                                 ThreadStore(tmp_path / spec.threads_file))
        router.bind(name, chat)
        chats[name] = (chat, client)
    return source, router, chats


def _texts(chat):
    return [m["text"] for m in chat.view_messages("chat")]


def test_two_chats_run_at_once_and_each_answer_lands_in_its_own(qapp, tmp_path):
    source, router, chats = _two_chats(tmp_path)
    (general, gclient), (pm, pclient) = chats[GENERAL], chats["PM"]
    general.send("what is the weather")
    pm.send("list the open risks")
    assert general.busy and pm.busy                       # neither blocks the other
    pclient.done.emit("pm1", {"answer": "Three risks are open.", "ok": True})
    gclient.done.emit("general1", {"answer": "Sunny.", "ok": True})
    assert "Three risks are open." in _texts(pm) and "Three risks are open." not in _texts(general)
    assert "Sunny." in _texts(general) and "Sunny." not in _texts(pm)
    general.store.save()
    pm.store.save()
    assert (tmp_path / "threads.json").exists() and (tmp_path / "threads-pm.json").exists()
    assert "list the open risks" not in (tmp_path / "threads.json").read_text(encoding="utf-8")


def test_a_chat_s_history_is_its_own(qapp, tmp_path):
    source, router, chats = _two_chats(tmp_path)
    (general, gclient), (pm, pclient) = chats[GENERAL], chats["PM"]
    general.send("remember the word banana")
    gclient.done.emit("general1", {"answer": "Noted.", "ok": True})
    pm.send("what word?")
    sent_history = pclient.calls[-1][2]
    assert not any("banana" in str(m) for m in sent_history)


def test_an_approval_card_shows_in_the_chat_that_asked_and_nowhere_else(qapp, tmp_path):
    source, router, chats = _two_chats(tmp_path)
    (general, _), (pm, pclient) = chats[GENERAL], chats["PM"]
    pm.send("write the charter")
    tid = pclient.turn_ids[-1]
    source.appeared.emit({"id": "ap1", "tool": "write_file", "args": {"path": "x"},
                          "turn_id": tid})
    assert any(m.get("kind") == "approval" for m in pm.store.chat)
    assert not any(m.get("kind") == "approval" for m in general.store.chat)


def test_cancelling_one_chat_leaves_the_other_running(qapp, tmp_path):
    source, router, chats = _two_chats(tmp_path)
    (general, gclient), (pm, pclient) = chats[GENERAL], chats["PM"]
    general.send("long question")
    pm.send("another long question")
    pm.stop_button.click()
    assert not pm.busy and general.busy
    assert pclient.calls[-1] == ("cancel", pclient.turn_ids[-1])
    assert not any(c[0] == "cancel" for c in gclient.calls)
