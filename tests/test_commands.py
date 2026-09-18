"""One command table, /help generated from it, only commands that do real
work, and /reset fixed to keep pending approvals."""

from ade_desktop.conversation.commands import (
    COMMAND_NAMES, COMMANDS, help_text, run_local,
)
from ade_desktop.conversation.router import SKILL_VERBS, UPLOAD_VERBS
from ade_desktop.conversation.threads import ThreadStore


def test_one_table_no_duplicates_no_overlap():
    names = [c.name for c in COMMANDS]
    assert len(names) == len(set(names)) == len(COMMAND_NAMES)
    assert not (COMMAND_NAMES & (SKILL_VERBS | UPLOAD_VERBS))
    assert COMMAND_NAMES == {"help", "clear", "compact", "restore", "reset",
                             "cancel", "health", "search", "research"}


def test_help_lists_exactly_the_table():
    text = help_text()
    for c in COMMANDS:
        assert f"/{c.name}" in text and c.hint in text
    for extra in ("/skill", "/upload", "! <command>", "? <question>",
                  "NOT gated"):
        assert extra in text


def test_dropped_commands_are_gone():
    """Placeholders and false text in the avatar -- e.g. /gpu said 'no
    dedicated GPU' on a machine with two RTX 4000 Ada cards."""
    for gone in ("gpu", "task", "plan", "steps", "progress", "review",
                 "memory", "recall", "remember", "forget", "dev", "summarize",
                 "cite", "context", "status", "system", "agent"):
        assert gone not in COMMAND_NAMES


def test_thread_commands(tmp_path):
    s = ThreadStore(tmp_path / "t.json")
    assert run_local("clear", s, "chat") == "Nothing to clear in chat."
    s.push("chat", "user", "ask", "q")
    assert run_local("clear", s, "chat") == (
        "Cleared 1 from chat - saved to session memory. "
        "/restore brings it back.")
    assert run_local("restore", s, "chat") == "Restored 1 to chat."
    assert run_local("restore", s, "chat") == \
        "Session memory is empty - nothing to restore."
    assert run_local("compact", s, "chat") == \
        "chat has 1 messages - nothing to compact (keeps 20)."
    for i in range(30):
        s.push("chat", "user", "ask", f"q{i}")
    assert run_local("compact", s, "chat") == (
        "Compacted chat: moved 11 to session memory, kept 20. "
        "/restore brings them back.")
    assert run_local("cancel", s, "chat").startswith("Nothing to cancel.")
    assert run_local("health", s, "chat") is None   # needs the network


def test_reset_archives_both_tabs_but_keeps_a_live_approval(tmp_path):
    """The avatar's /reset threw (it called .map on an object) and meant to
    hide pending approvals -- which would let them time out into denials."""
    s = ThreadStore(tmp_path / "t.json")
    s.push("chat", "user", "ask", "q")
    s.push("shell", "user", "shell", "ls")
    live = s.push("chat", "ade", "approval", "",
                  {"approval": {"id": "a1", "tool": "write_file"}})
    done = s.push("chat", "ade", "approval", "",
                  {"approval": {"id": "a0"}, "decided": "Allowed a0"})
    s.skills = ["ade-brainstorming"]
    note = run_local("reset", s, "chat")
    assert s.shell == [] and s.skills == []
    assert s.chat == [live]
    assert done in s.archive[-2]["messages"] or done in s.archive[-1]["messages"]
    assert "1 pending approval(s) kept" in note
