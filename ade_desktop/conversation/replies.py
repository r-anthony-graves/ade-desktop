"""Reply text: ported from the avatar's readReply(), applyAskResult() and its
/health formatter (adeos/avatar/chat.js). Pure."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from ade_desktop.conversation.router import looks_like_clear

_KEYS = ("output", "result", "answer", "reply", "message", "summary",
         "detail", "error")
LOW_CONFIDENCE = 0.5


def failed(result) -> bool:
    """Did the CALL fail? A truthy `error`, not the key's presence: a
    /v1/tasks reply ALWAYS carries `error`, null on success (the mission
    runner) or "" (the fast path) -- measured by the piece-5 review, where
    every real task reply rendered as "Call failed"."""
    return not isinstance(result, dict) or bool(result.get("error"))


def task_report(d) -> tuple[str, bool]:
    """(text, needs_a_look) for a /v1/tasks reply: {task_id, ok, summary,
    error, degraded, confidence, ...}. `ok` and the summary are Ade's own
    claim -- it has reported success with zero files changed -- so a
    degraded or low-confidence result says so under the summary."""
    summary = str(d.get("summary") or "").strip()
    if d.get("ok") is False or d.get("error"):
        head = "The task did not succeed" + (f": {d['error']}" if d.get("error") else ".")
        return (head + ("\n\n" + summary if summary else "")), True
    flags = []
    if d.get("degraded"):
        flags.append("degraded")
    conf = d.get("confidence")
    if isinstance(conf, (int, float)) and not isinstance(conf, bool) and conf < LOW_CONFIDENCE:
        flags.append(f"confidence {conf:.2f}")
    text = summary or read_reply(d)
    if flags:
        text += ("\n\nCheck the work: Ade reports this done but marked it "
                 + " and ".join(flags) + ".")
    return text, bool(flags)


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


_TRANSPORT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(Error|Exception|Timeout)$")


def error_cause(result) -> str:
    """Why a call failed, worded apart: an Ade OS error envelope, a status
    with a plain message, no answer in time, no answer at all -- and Ade OS
    reporting an error in a normal reply. Only a transport exception (net.py
    words those "<ExceptionClass>: <message>") is 'unreachable': a 409
    'session busy' came FROM Ade OS (review finding, 2026-09-18)."""
    err = result.get("error") if isinstance(result, dict) else result
    status = result.get("status") if isinstance(result, dict) else None
    if isinstance(err, dict):
        code = err.get("code") or "error"
        message = err.get("message") or ""
        head = f"HTTP {status}: {code}" if status else code
        return f"{head} - {message}".rstrip(" -")
    text = str(err or "no reply")
    if text.startswith("HTTP "):
        return text
    head = text.split(":", 1)[0].strip()
    if _TRANSPORT.match(head):
        if "Timeout" in head:
            return f"no answer in time: {text}"
        return f"Ade OS unreachable: {text}"
    if status:
        return f"HTTP {status}: {text}"
    return f"Ade OS said: {text}"


def task_types_from(result) -> list[str]:
    """The task types Ade OS lists in its 400 unknown_task_type envelope
    (detail.task_types), or [] when it did not say."""
    err = result.get("error") if isinstance(result, dict) else None
    detail = err.get("detail") if isinstance(err, dict) else None
    types = detail.get("task_types") if isinstance(detail, dict) else None
    return [str(t) for t in types] if isinstance(types, list) else []


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
