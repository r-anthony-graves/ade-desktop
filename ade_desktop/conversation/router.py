"""A typed line plus the active tab -> what to do with it. Pure.

Ported from the avatar's classify() / routePlain() (adeos/avatar/chat.js).
A slash word that is not a command, skill verb or upload verb is a TASK TYPE
-- including every placeholder command the avatar used to answer with
invented text. Ade OS then refuses an unknown type loudly (400
unknown_task_type), which beats printing a fake status.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ade_desktop.conversation.detect import detect

SKILL_VERBS = frozenset({"skill", "skills", "unskill", "superpowers"})
UPLOAD_VERBS = frozenset({"upload", "uploads"})

_CLEAR_1 = re.compile(
    r"^(please\s+)?(clear|reset|wipe|forget)\s+(the\s+)?(current\s+)?"
    r"(context|chat|thread|conversation|task|history)\b")
_CLEAR_2 = re.compile(r"^(new|start a new)\s+(chat|conversation|thread)\b")
_CLEAR_3 = re.compile(r"^user requested to clear\b")


@dataclass(frozen=True)
class Route:
    kind: str       # empty ask chat task shell inline_shell clear command skill upload
    text: str
    type: str = ""  # task type
    verb: str = ""  # command / skill / upload verb


def looks_like_clear(text) -> bool:
    """The avatar's looksLikeClear(), verbatim."""
    v = str("" if text is None else text).strip().lower()
    v = re.sub(r"^escalate:\s*", "", v)
    return bool(_CLEAR_1.search(v) or _CLEAR_2.search(v) or _CLEAR_3.search(v)
                or v in ("clear", "clear context"))


def route(raw, tab: str, commands: frozenset[str]) -> Route:
    v = str("" if raw is None else raw).strip()
    if not v:
        return Route("empty", "")
    if v[0] == "!":
        return Route("shell", v[1:].strip())
    if v[0] == "?":
        return Route("chat", v[1:].strip())
    if v[0] == "/":
        m = re.match(r"^(\S+)\s*([\s\S]*)$", v[1:])
        word = (m.group(1) if m else "").lower()
        body = (m.group(2) if m else "").strip()
        if word in SKILL_VERBS:
            return Route("skill", body, verb=word)
        if word in UPLOAD_VERBS:
            return Route("upload", body, verb=word)
        if word in commands:
            return Route("command", body, verb=word)
        return Route("task", body, type=word)
    if tab == "shell":
        return Route("shell", v)
    if looks_like_clear(v):
        return Route("clear", v)
    if detect(v)[0]:
        return Route("inline_shell", v)
    return Route("ask", v)
