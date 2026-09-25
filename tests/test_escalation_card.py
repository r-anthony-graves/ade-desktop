"""Review and approve, for a change Ade cannot make itself.

Ray, 2026-09-25: "it should present as a review and approve."

The read-only ask tier cannot write. When a request needs a change, its prompt
asks Ade for a single `ESCALATE: <task>` line. Two things were wrong. Ade OS
missed near-misses of the word -- live, asked to write a spec file, Ade replied
`ESCAPE: I need to write the spec file at docs/specs/...` and the prose came
back as a finished answer (fixed in Ade OS, 4fa70954). And when the line WAS
recognised, this app answered "Ade would treat this as a change. It stays here
-- nothing was staged" and stopped: `ask_reply`'s own docstring said "An
escalate NEVER dispatches". Ray had to notice and re-issue the request himself.

Ade OS now enters a recognised escalation in the approval registry (d39ec108),
so `ApprovalWatcher` already finds it and a card already appears. What was
missing is everything that makes the card mean anything:

  - it read as a tool gate ("Approval needed: escalate") over raw JSON,
    because `kind` never reached the widget;
  - Allow only RECORDED a decision, so approving dispatched no work -- a
    prettier dead end;
  - the reply still said nothing was staged, which had become untrue.

The click-only invariant is unchanged and retested here: a keystroke meant for
the input box must never approve a change either.
"""

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import QLabel

from ade_desktop.conversation.panel import ConversationPanel
from ade_desktop.conversation.replies import ask_reply
from ade_desktop.conversation.threads import ThreadStore
from ade_desktop.conversation.widgets import ApprovalCard

PROMPT = ("write the spec file at "
          "docs/specs/2026-09-25-ade-self-evaluation-design.md")
ROOT = "C:/Users/ray_g/ade-ai"


def _args(**over):
    payload = {"prompt": PROMPT, "root": ROOT, "task_type": "coding",
               "token": "ESCAPE"}
    payload.update(over)
    return payload


def _escalation(meta_extra=None, **over):
    meta = {"approval": {"id": "e1", "tool": "escalate",
                         "kind": "escalation", "args": _args(**over)}}
    meta.update(meta_extra or {})
    return {"role": "ade", "kind": "approval", "text": "", "meta": meta}


def _tool_approval():
    return {"role": "ade", "kind": "approval", "text": "",
            "meta": {"approval": {"id": "a1", "tool": "write_file",
                                  "kind": "tool",
                                  "args": {"path": "x.txt"}}}}


def _body(card):
    return "\n".join(w.text() for w in card.findChildren(QLabel))


# -- the card ----------------------------------------------------------------

def test_an_escalation_card_reviews_a_change_not_a_tool_call(qapp):
    """What Ray decides is "should Ade do this work", so the card must say
    WHAT would run and WHERE -- not a tool name over a JSON blob."""
    card = ApprovalCard(_escalation())
    body = _body(card)

    assert PROMPT in body
    assert ROOT in body
    assert "Approval needed" not in body, body
    assert card.allow.text() == "Approve"
    assert card.deny.text() == "Decline"


def test_a_tool_approval_card_is_unchanged(qapp):
    """The regression guard: a gated tool call must look exactly as before."""
    card = ApprovalCard(_tool_approval())
    body = _body(card)

    assert "Approval needed: write_file" in body
    assert "x.txt" in body
    assert card.allow.text() == "Allow"
    assert card.deny.text() == "Deny"


def test_an_approval_with_no_kind_reads_as_a_tool(qapp):
    """An older Ade OS sends no `kind`. Every record was a tool approval
    before 2026-09-25, so absence must mean that -- never work to dispatch."""
    msg = _tool_approval()
    del msg["meta"]["approval"]["kind"]

    card = ApprovalCard(msg)

    assert "Approval needed: write_file" in _body(card)
    assert card.allow.text() == "Allow"


def test_an_escalation_card_can_still_only_be_clicked(qapp):
    """Unchanged invariant, restated for the new card: no default button, no
    auto-default, no focus -- Enter in the input box cannot approve work."""
    card = ApprovalCard(_escalation())
    for button in (card.allow, card.deny):
        assert button.isEnabled()
        assert not button.isDefault() and not button.autoDefault()
        assert button.focusPolicy() == Qt.FocusPolicy.NoFocus

    got = []
    card.decided.connect(lambda aid, allow: got.append((aid, allow)))
    card.allow.click()

    assert got == [("e1", True)]
    assert not card.allow.isEnabled() and not card.deny.isEnabled()


def test_a_card_with_no_root_still_reads(qapp):
    """`root` is None when Ade OS has no configured roots."""
    assert PROMPT in _body(ApprovalCard(_escalation(root=None)))


def test_a_card_with_no_prompt_does_not_pretend_to_be_reviewable(qapp):
    """Defensive: a malformed record must not render an empty Approve."""
    card = ApprovalCard(_escalation(prompt=""))
    assert "Approval needed" in _body(card)


# -- the panel ---------------------------------------------------------------

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
        return "r%d" % self._n

    def ask(self, q, skills, history, turn_id=None):
        return self._rid("ask", q)

    def chat(self, text):
        return self._rid("chat", text)

    def task(self, text, t, skills, turn_id=None):
        return self._rid("task", text, t, list(skills))

    def cancel(self, turn_id): return self._rid("cancel", turn_id)
    def shell(self, cmd): return self._rid("shell", cmd)
    def run(self, cmd): return self._rid("run", cmd)
    def kill(self): return self._rid("kill")
    def health(self): return self._rid("health")
    def skills(self): return self._rid("skills")
    def task_types(self): return self._rid("task_types")
    def decide(self, aid, allow): return self._rid("decide", aid, allow)
    def upload(self, files, overwrite): return self._rid("upload")


class FakeWatcher(QObject):
    appeared = Signal(object)
    vanished = Signal(str)


def _panel(tmp_path):
    client, watcher = FakeClient(), FakeWatcher()
    store = ThreadStore(tmp_path / "threads.json")
    return ConversationPanel(client, watcher, store), client, watcher


def _cards(panel):
    return [w for w in panel._widgets.values() if isinstance(w, ApprovalCard)]


def _appear(watcher, aid="e1", **over):
    watcher.appeared.emit({"id": aid, "tool": "escalate",
                           "kind": "escalation", "args": _args(**over)})


def _tasks(client):
    return [c for c in client.calls if c[0] == "task"]


def test_the_kind_reaches_the_card(qapp, tmp_path):
    """Falsify by dropping `kind` from panel._on_appeared's meta -- the card
    falls back to a tool gate and this goes RED."""
    panel, _, watcher = _panel(tmp_path)
    _appear(watcher)

    card = _cards(panel)[0]

    assert PROMPT in _body(card)
    assert card.allow.text() == "Approve"


def test_approving_an_escalation_dispatches_the_task(qapp, tmp_path):
    """THE point of the change. Before it, Allow recorded a decision and
    nothing ran: Ray approved a change that never happened."""
    panel, client, watcher = _panel(tmp_path)
    _appear(watcher)
    card = _cards(panel)[0]

    card.allow.click()
    assert client.calls[-1] == ("decide", "e1", True)
    client.done.emit("r%d" % len(client.calls), {"id": "e1", "allowed": True})

    assert _tasks(client) == [("task", PROMPT, "coding", [])]


def test_the_dispatch_is_visible_in_the_transcript(qapp, tmp_path):
    """Ray must be able to see that approving started work, or the card is a
    button with no consequence he can point at."""
    panel, client, watcher = _panel(tmp_path)
    _appear(watcher)
    card = _cards(panel)[0]
    card.allow.click()
    client.done.emit("r%d" % len(client.calls), {"id": "e1", "allowed": True})

    said = " ".join(m["text"] for m in panel.view_messages("chat"))

    assert PROMPT in said


def test_declining_an_escalation_dispatches_nothing(qapp, tmp_path):
    panel, client, watcher = _panel(tmp_path)
    _appear(watcher)
    card = _cards(panel)[0]

    card.deny.click()
    client.done.emit("r%d" % len(client.calls), {"id": "e1", "allowed": False})

    assert _tasks(client) == []


def test_a_decision_that_failed_dispatches_nothing(qapp, tmp_path):
    """An unreachable Ade OS is not an approval. Dispatching on a failed
    decide would run work whose approval was never recorded."""
    panel, client, watcher = _panel(tmp_path)
    _appear(watcher)
    card = _cards(panel)[0]

    card.allow.click()
    client.done.emit("r%d" % len(client.calls),
                     {"error": "ConnectError: refused"})

    assert _tasks(client) == []
    assert card.allow.isEnabled()          # the buttons come back, as before


def test_an_escalation_decided_elsewhere_dispatches_nothing(qapp, tmp_path):
    """409 already_decided means someone else answered it. Running the work
    here would run it twice."""
    panel, client, watcher = _panel(tmp_path)
    _appear(watcher)
    card = _cards(panel)[0]

    card.allow.click()
    client.done.emit("r%d" % len(client.calls),
                     {"error": {"code": "already_decided"}, "status": 409})

    assert _tasks(client) == []
    assert card.outcome.text() == "Already decided elsewhere"


def test_approving_a_gated_tool_call_dispatches_nothing(qapp, tmp_path):
    """The worst possible regression: a tool approval must never submit a
    task. Only an escalation carries work to run."""
    panel, client, watcher = _panel(tmp_path)
    watcher.appeared.emit({"id": "a1", "tool": "write_file", "kind": "tool",
                           "args": {"path": "x.txt"}})
    card = _cards(panel)[0]

    card.allow.click()
    client.done.emit("r%d" % len(client.calls), {"id": "a1", "allowed": True})

    assert _tasks(client) == []


def test_an_escalation_dispatches_once_however_often_it_is_polled(qapp,
                                                                  tmp_path):
    """The watcher polls every 2 s and re-emits until the record is decided."""
    panel, client, watcher = _panel(tmp_path)
    _appear(watcher)
    _appear(watcher)
    _appear(watcher)
    assert len(_cards(panel)) == 1

    card = _cards(panel)[0]
    card.allow.click()
    client.done.emit("r%d" % len(client.calls), {"id": "e1", "allowed": True})

    assert len(_tasks(client)) == 1


def test_a_restored_escalation_card_is_never_live(qapp, tmp_path):
    """Same rule as a tool card: a card reloaded from the transcript must not
    be clickable, or restarting the app could dispatch old work."""
    store = ThreadStore(tmp_path / "threads.json")
    store.push("chat", "ade", "approval", "",
               {"approval": {"id": "old", "tool": "escalate",
                             "kind": "escalation", "args": _args()}})
    store.save()
    client, watcher = FakeClient(), FakeWatcher()
    panel = ConversationPanel(client, watcher,
                              ThreadStore(tmp_path / "threads.json"))

    card = _cards(panel)[0]

    assert card.allow.isHidden()
    assert card.outcome.text() == "Answered elsewhere"


# -- the dispatch guard itself ----------------------------------------------
#
# Added after falsification: removing the guard in _dispatch_escalation left
# the whole suite green, so it was a guard nothing held. The tests above could
# not reach it -- a tool approval carries no `prompt`, so the early return fired
# first, and _on_card_decided's own "one decision per approval" check already
# stopped a second call. These two drive it directly.

def test_a_tool_approval_that_happens_to_carry_a_prompt_dispatches_nothing(
        qapp, tmp_path):
    """The `kind` half of the guard. `prompt` is not a reserved word in a tool's
    arguments, and dispatching on one would run a tool's own text as a task."""
    panel, client, watcher = _panel(tmp_path)
    watcher.appeared.emit({"id": "t1", "tool": "some_tool", "kind": "tool",
                           "args": {"prompt": "rm -rf /", "path": "x"}})
    card = _cards(panel)[0]

    card.allow.click()
    client.done.emit("r%d" % len(client.calls), {"id": "t1", "allowed": True})

    assert _tasks(client) == []


def test_dispatching_the_same_escalation_twice_submits_one_task(qapp, tmp_path):
    """The `dispatched` half. Called directly, because the paths above cannot
    reach it -- and a guard reachable only in theory is not a guard."""
    panel, client, watcher = _panel(tmp_path)
    _appear(watcher)
    msg = panel._card_message("e1")

    panel._dispatch_escalation(msg)
    panel._dispatch_escalation(msg)

    assert len(_tasks(client)) == 1


# -- the reply text ----------------------------------------------------------

def test_a_staged_escalation_no_longer_claims_nothing_was_staged():
    """It used to end the thread. Now a card is waiting, so "nothing was
    staged" would be false and would send Ray to re-issue the request."""
    reply = ask_reply({
        "answer": "ESCAPE: %s" % PROMPT, "ok": True,
        "escalate": dict(_args(), approval_id="e1")})

    assert "nothing was staged" not in reply.text.lower()
    assert "approve" in reply.text.lower()


def test_an_escalation_ade_os_could_not_stage_still_says_so():
    """No `approval_id` means no card is coming -- an older Ade OS, or a
    registry that failed. Promising a review that never appears is worse than
    the old dead end, because Ray would wait for it."""
    reply = ask_reply({"answer": "ESCALATE: %s" % PROMPT, "ok": True,
                       "escalate": _args()})

    assert "nothing was staged" in reply.text.lower()


def test_an_ordinary_answer_is_untouched():
    assert ask_reply({"answer": "The branch is clean.",
                      "ok": True}).text == "The branch is clean."
