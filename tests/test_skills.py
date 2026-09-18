"""/skill, /unskill, /superpowers. The fixture is the real skill names
listed by :8300 on 2026-09-18."""

from ade_desktop.conversation.skills import (
    SUPERPOWERS_PROCESS, attach, detach, resolve_superpowers, skill_list_text,
)

NAMES = ["using-superpowers", "brainstorming", "ade-brainstorming",
         "systematic-debugging", "writing-plans", "ade-writing-plans",
         "executing-plans", "ade-executing-plans",
         "verification-before-completion", "dispatching-parallel-agents",
         "requesting-code-review", "receiving-code-review", "ade-code-review"]
ROWS = [{"name": n, "attachable": True} for n in NAMES] + \
       [{"name": "huge", "attachable": False}]


def test_superpowers_prefers_the_ade_ports():
    """Ray's standing rule: an ade- port is never swapped for its upstream.
    The avatar attached the upstream three."""
    assert resolve_superpowers(ROWS) == [
        "using-superpowers", "ade-brainstorming", "systematic-debugging",
        "ade-writing-plans", "ade-executing-plans",
        "verification-before-completion", "dispatching-parallel-agents",
        "requesting-code-review", "receiving-code-review"]
    assert len(SUPERPOWERS_PROCESS) == 9


def test_an_unattachable_port_falls_back_to_upstream():
    rows = [{"name": "ade-brainstorming", "attachable": False},
            {"name": "brainstorming", "attachable": True}]
    assert resolve_superpowers(rows) == ["brainstorming"]


def test_attach_detach():
    now, msg = attach(ROWS, [], "ade-code-review")
    assert now == ["ade-code-review"] and msg.startswith("Attached ade-code-review")
    same, msg = attach(ROWS, now, "ade-code-review")
    assert same == now and "already" in msg
    _, msg = attach(ROWS, now, "huge")
    assert "too large" in msg
    _, msg = attach(ROWS, now, "nope")
    assert msg.startswith("No skill named nope")
    gone, msg = detach(now, "-ade-code-review")
    assert gone == [] and msg == "Removed ade-code-review."
    _, msg = detach([], "x")
    assert msg == "x is not attached."


def test_list_text():
    text = skill_list_text(ROWS, ["ade-brainstorming"])
    assert text.startswith("Attached: ade-brainstorming")
    assert f"{len(NAMES)} available:" in text
    assert "Too large to attach (over the cap): huge" in text
