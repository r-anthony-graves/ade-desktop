"""The panel's commands: ONE table, and /help is generated from it.

The avatar kept a table AND a hand-written if/else chain; the two drifted
until a guard (commands-table.test.js) held them equal. Here there is only
the table. And only commands that do real work are in it: the avatar's
placeholders and false-text commands (/gpu "no dedicated GPU" on a two-RTX
machine, /task and /plan reciting its own September build, and the rest --
see the piece-2 spec) are gone. A dropped name typed now routes as a task
type and fails loudly at Ade OS.
"""

from __future__ import annotations

from dataclasses import dataclass

from ade_desktop.conversation.threads import COMPACT_KEEP


@dataclass(frozen=True)
class Command:
    name: str
    hint: str
    while_busy: bool = False   # may run while a turn is in flight


COMMANDS = (
    Command("help", "list these commands", True),
    Command("clear", "move this tab to session memory"),
    Command("compact", f"keep the last {COMPACT_KEEP}, archive the rest"),
    Command("restore", "bring back the newest archived batch"),
    Command("reset", "archive both tabs and detach skills; pending approvals stay"),
    Command("cancel", "explains what cancel can and cannot do"),
    Command("health", "ask Ade OS how every subsystem is", True),
    Command("search", "a fresh question to Ade, without this thread's history"),
    Command("research", "a fresh question to Ade, without this thread's history"),
)
COMMAND_NAMES = frozenset(c.name for c in COMMANDS)
BY_NAME = {c.name: c for c in COMMANDS}


def help_text() -> str:
    width = max(len(c.name) for c in COMMANDS) + 1
    lines = [f"/{c.name.ljust(width)} {c.hint}" for c in COMMANDS]
    lines += [
        "",
        "/skill <name> · /unskill <name> · /superpowers · /skill (list)",
        "/upload · /upload folder · /upload overwrite · or drop files here",
        "! <command>  the shell -- NOT gated by Permission.check()",
        "? <question> plain chat, no files read",
        "/<task type> <text>  an agent does the work (gated)",
        "A bare command line (git status, get-process) runs and streams here.",
    ]
    return "\n".join(lines)


def _live_approval(m) -> bool:
    meta = m.get("meta") or {}
    return (m.get("kind") == "approval" and not meta.get("decided")
            and not meta.get("moot"))


def run_local(verb, store, tab):
    """The commands that need no network. Returns the system note, or None
    for a command the panel must send through the client (health, search,
    research) or render itself (help)."""
    if verb == "clear":
        n = store.clear(tab)
        return (f"Cleared {n} from {tab} - saved to session memory. "
                "/restore brings it back." if n else f"Nothing to clear in {tab}.")
    if verb == "compact":
        n = store.compact(tab)
        if n is None:
            return (f"{tab} has {len(store.tab_messages(tab))} messages - "
                    f"nothing to compact (keeps {COMPACT_KEEP}).")
        return (f"Compacted {tab}: moved {n} to session memory, kept "
                f"{COMPACT_KEEP}. /restore brings them back.")
    if verb == "restore":
        got = store.restore()
        if got is None:
            return "Session memory is empty - nothing to restore."
        return f"Restored {got[1]} to {got[0]}."
    if verb == "reset":
        # The avatar's /reset threw, and meant to hide pending approvals --
        # which would have let them time out into denials. A live card
        # survives a reset: it still needs a decision.
        live = [m for m in store.chat if _live_approval(m)]
        store.chat[:] = [m for m in store.chat if not _live_approval(m)]
        moved = store.clear("chat") + store.clear("shell")
        store.chat[:0] = live
        store.skills = []
        note = (f"Reset: archived {moved} messages from both tabs and "
                "detached all skills.")
        if live:
            note += (f" {len(live)} pending approval(s) kept - they still "
                     "need a decision.")
        return note
    if verb == "cancel":
        return ("Nothing to cancel. A staged draft sits in the input box - "
                "clear the box instead. A running shell command has its own "
                "Stop button.")
    return None
