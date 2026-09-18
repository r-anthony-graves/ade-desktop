"""The Chat thread as /v1/ask history. A verbatim port of the avatar's
threadHistory(): the server sanitises to the same 40 turns x 4000 characters
(adeos/avatar 17fa3e0), so sending more would only be thrown away."""

from __future__ import annotations

MAX_TURNS = 40
MAX_CHARS = 4000


def thread_history(messages) -> list[dict]:
    out = []
    for m in messages or []:
        if not isinstance(m, dict):
            continue
        if m.get("role") == "system" or m.get("kind") == "working":
            continue
        text = str(m.get("text") or "").strip()
        if not text:
            continue
        role = {"user": "user", "ade": "assistant"}.get(m.get("role"))
        if role is None:
            continue
        if len(text) > MAX_CHARS:
            text = text[:MAX_CHARS] + "…"
        out.append({"role": role, "content": text})
    # The last user line is the question being asked: drop it so it is not
    # sent twice.
    if out and out[-1]["role"] == "user":
        out.pop()
    return out[-MAX_TURNS:]
