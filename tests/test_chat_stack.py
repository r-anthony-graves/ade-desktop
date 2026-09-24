"""Multi-session chat (Ray, 2026-09-24, requirement 7).

The approval fallback is the load-bearing part: a card delivered to a tab
nobody can see is never answered, and an unanswered approval TIMES OUT --
and a timeout denies.
"""

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QLabel

from ade_desktop.conversation.sessions import (GENERAL, ApprovalRouter,
                                               session_for)
from ade_desktop.conversation.stack import ChatStack


# -- session specs ----------------------------------------------------------

def test_session_one_keeps_todays_names():
    """No history may move."""
    general = session_for(GENERAL, 1)
    assert general.threads_file == "threads.json"
    assert general.topic == "u/local/desktop"
    pm = session_for("PM", 1)
    assert pm.threads_file == "threads-pm.json"
    assert pm.topic == "u/local/desktop-pm"
    assert session_for(GENERAL) == session_for(GENERAL, 1)


def test_later_sessions_are_separate_conversations():
    """Separate thread file, separate Ade OS topic, separate terminal --
    so a long /task in one does not land in, or block, another."""
    a, b = session_for("PM", 1), session_for("PM", 2)
    assert a.threads_file != b.threads_file
    assert a.topic != b.topic
    assert a.terminal != b.terminal
    assert b.threads_file == "threads-pm-2.json"
    assert b.topic == "u/local/desktop-pm-2"


def test_general_session_two_does_not_collide_with_a_section():
    assert session_for(GENERAL, 2).topic != session_for("PM", 2).topic
    assert session_for(GENERAL, 2).threads_file == "threads-2.json"


def test_a_nonsense_index_falls_back_to_one():
    assert session_for("PM", 0).threads_file == "threads-pm.json"
    assert session_for("PM", -3).threads_file == "threads-pm.json"


# -- the approval fallback --------------------------------------------------

class FakeSource(QObject):
    """The same shape tests/test_sessions.py uses."""
    appeared = Signal(object)
    vanished = Signal(str)

    def __init__(self):
        super().__init__()
        self.started = self.stopped = 0

    def start(self): self.started += 1
    def stop(self): self.stopped += 1
    def pending_count(self): return 0


class Chat:
    def __init__(self, turn=None):
        self.turn = turn

    def owns_turn(self, turn_id):
        return bool(turn_id) and turn_id == self.turn


def _two_general_sessions():
    """The chats are RETURNED and must be held by the caller: the router
    binds them weakly on purpose, so it can never keep a closed panel
    alive. An inline Chat() is collected before the first emit and its
    turn is then owned by nobody."""
    source = FakeSource()
    router = ApprovalRouter(source)
    got, chats = {}, {}
    for key in (f"{GENERAL}#1", f"{GENERAL}#2"):
        got[key] = []
        router.watcher_for(key).appeared.connect(
            lambda a, k=key: got[k].append(a["id"]))
        chats[key] = Chat()
        router.bind(key, chats[key])
    return source, router, got, chats


def test_an_unowned_approval_goes_to_the_SELECTED_general_session(qapp):
    """Falsify by removing set_default's branch from _owner(): the card
    then lands on session 1 while session 2 is the one on screen."""
    source, router, got, chats = _two_general_sessions()
    router.set_default(f"{GENERAL}#2")
    source.appeared.emit({"id": "w1", "turn_id": None, "tool": "run_shell"})
    assert got[f"{GENERAL}#2"] == ["w1"]
    assert got[f"{GENERAL}#1"] == []


def test_an_owned_approval_still_goes_to_its_own_turn(qapp):
    """The selection must never override ownership."""
    source, router, got, chats = _two_general_sessions()
    chats[f"{GENERAL}#1"].turn = "t-1"      # held by `chats`, see the helper
    router.set_default(f"{GENERAL}#2")
    source.appeared.emit({"id": "a1", "turn_id": "t-1"})
    assert got[f"{GENERAL}#1"] == ["a1"]
    assert got[f"{GENERAL}#2"] == []


def test_with_no_default_set_it_still_delivers_somewhere(qapp):
    """A card with nowhere to go is a card nobody answers."""
    source, router, got, chats = _two_general_sessions()
    source.appeared.emit({"id": "z1", "turn_id": "nobody"})
    assert got[f"{GENERAL}#1"] + got[f"{GENERAL}#2"] == ["z1"]


def test_a_stale_default_does_not_swallow_the_card(qapp):
    """A closed session's key must not become a black hole."""
    source, router, got, chats = _two_general_sessions()
    router.set_default(f"{GENERAL}#9")          # never registered
    source.appeared.emit({"id": "q1", "turn_id": None})
    assert got[f"{GENERAL}#1"] + got[f"{GENERAL}#2"] == ["q1"]


# -- the widget -------------------------------------------------------------

class FakePanel(QLabel):
    approval_needed = Signal(str)
    reply_landed = Signal(str)          # the orb listens through the stack

    def __init__(self, number):
        super().__init__(f"panel {number}")
        self.number = number
        self.stopped = []
        self.client = self
        self.watcher = self
        self.started = 0

    def on_quit(self): self.stopped.append("quit")
    def stop(self): self.stopped.append("stop")
    def start(self): self.started += 1


def _stack(name=GENERAL, router=None):
    return ChatStack(name, FakePanel, router=router)


def test_it_opens_with_one_session(qapp):
    stack = _stack()
    assert stack.session_count() == 1
    assert stack.tabs.count() == 1


def test_plus_opens_another_independent_conversation(qapp):
    stack = _stack()
    first = stack.panels[0]
    second = stack.add_session()
    assert first is not second
    assert stack.session_count() == 2
    assert [stack.tabs.tabText(i) for i in range(2)] == ["Chat 1", "Chat 2"]


def test_numbers_are_not_reused(qapp):
    stack = _stack()
    stack.add_session()
    stack.close_session(1)
    stack.add_session()
    assert [stack.tabs.tabText(i) for i in range(2)] == ["Chat 1", "Chat 3"]


def test_closing_a_session_stops_its_client_and_watcher(qapp):
    """Otherwise a closed chat keeps polling Ade OS forever."""
    stack = _stack()
    second = stack.add_session()
    stack.close_session(1)
    assert second.stopped == ["quit", "stop", "stop"]
    assert stack.session_count() == 1


def test_the_last_session_cannot_be_closed(qapp):
    stack = _stack()
    stack.close_session(0)
    assert stack.session_count() == 1


def test_selecting_a_general_tab_moves_the_approval_default(qapp):
    """Falsify by dropping the router.set_default call from _on_tab."""
    source = FakeSource()
    router = ApprovalRouter(source)
    stack = _stack(GENERAL, router)
    stack.add_session()
    assert router._default == f"{GENERAL}#2"
    stack.tabs.setCurrentIndex(0)
    assert router._default == f"{GENERAL}#1"


def test_a_section_stack_never_claims_the_default(qapp):
    """Only General is the fallback. A PM tab selection must not send
    Ade OS's unowned approvals to PM."""
    source = FakeSource()
    router = ApprovalRouter(source)
    stack = _stack("PM", router)
    stack.add_session()
    assert router._default is None


def test_select_shows_the_tab_holding_a_panel(qapp):
    stack = _stack()
    first = stack.panels[0]
    stack.add_session()
    assert stack.current() is not first
    assert stack.select(first) is True
    assert stack.current() is first
    assert stack.select(QLabel("stranger")) is False


def test_start_starts_every_session_s_watcher(qapp):
    stack = _stack()
    stack.add_session()
    stack.start()
    assert all(p.started == 1 for p in stack.panels)
