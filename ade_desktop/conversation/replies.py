"""Reply text: ported from the avatar's readReply(), applyAskResult() and its
/health formatter (adeos/avatar/chat.js). Pure."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from ade_desktop.conversation.router import looks_like_clear

_KEYS = ("output", "result", "answer", "reply", "message", "summary",
         "detail", "error")


def read_reply(d) -> str:
    if d is None:
        return ""
    if isinstance(d, str):
        return d
    if isinstance(d, dict):
        try:
            return d["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError):
            pass
        for key in _KEYS:
            v = d.get(key)
            if isinstance(v, str) and v.strip():
                return v
        if d.get("task_id"):
            return f"task {d['task_id']} accepted"
    try:
        return json.dumps(d, indent=2)
    except (TypeError, ValueError):
        return str(d)


@dataclass(frozen=True)
class AskReply:
    text: str
    cleared: bool = False


def ask_reply(result) -> AskReply:
    """The one place a /v1/ask reply becomes text. An escalate NEVER
    dispatches: the answer stays on Chat and says nothing was staged."""
    result = result if isinstance(result, dict) else {}
    text = result.get("answer") or ""
    cited = result.get("roots_cited") or []
    if cited:
        text = (text + "\n\n" if text else "") + "From: " + ", ".join(map(str, cited))
    esc = result.get("escalate")
    if not esc:
        return AskReply(text or "(no output)")
    esc = esc if isinstance(esc, dict) else {}
    prompt = str(esc.get("prompt") or "")
    if looks_like_clear(prompt) or looks_like_clear(text):
        return AskReply("Cleared.", cleared=True)
    cleaned = re.sub(r"^\s*ESCALATE:\s*", "", str(text), flags=re.I | re.M).strip()
    if re.match(r"^(greet|say hello|say hi)\b", prompt, re.I) or \
            re.fullmatch(r"(hi|hello|hey)[.!\s]*", cleaned, re.I):
        return AskReply("Hello, Ray.")
    where = f" in {esc['root']}" if esc.get("root") else ""
    return AskReply((cleaned + "\n\n" if cleaned else "")
                    + f"Ade would treat this as a change{where}. "
                    "It stays here — nothing was staged.")


def health_text(payload) -> str:
    """Every subsystem Ade OS names, up or down -- never one word. The
    avatar's version replaced a literal that said 'all systems nominal'
    unconditionally."""
    if not isinstance(payload, dict) or "error" in payload:
        err = payload.get("error") if isinstance(payload, dict) else payload
        if isinstance(err, dict):
            err = f"{err.get('code', 'error')}: {err.get('message', '')}"
        return (f"Ade OS did not answer /v1/health - {err or 'no reply'}. "
                "That IS the health answer: the API is unreachable.")
    lines = [f"Ade OS: {payload.get('status') or 'unknown'}"]
    for name, sub in (payload.get("subsystems") or {}).items():
        sub = sub if isinstance(sub, dict) else {}
        lines.append(f"  {name}: {'up' if sub.get('up') else 'DOWN'}"
                     + (f" - {sub['detail']}" if sub.get("detail") else ""))
    if payload.get("may_execute_tools") is False:
        lines.append("  tools BLOCKED: "
                     + (payload.get("blocking_reason") or "no reason given"))
    return "\n".join(lines)
