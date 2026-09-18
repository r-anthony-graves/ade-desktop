"""/skill, /unskill, /superpowers. Pure: the rows come from GET /v1/skills.

Attached skills travel with ask and /type task turns, as in the avatar.
"""

from __future__ import annotations

SUPERPOWERS_PROCESS = (
    "using-superpowers", "brainstorming", "systematic-debugging",
    "writing-plans", "executing-plans", "verification-before-completion",
    "dispatching-parallel-agents", "requesting-code-review",
    "receiving-code-review",
)


def _attachable(rows) -> dict[str, bool]:
    return {r.get("name"): bool(r.get("attachable"))
            for r in rows or [] if isinstance(r, dict) and r.get("name")}


def resolve_superpowers(rows) -> list[str]:
    """Each process skill as its ade- port when one exists and can be
    attached -- Ray's rule: an ade- port is LOCALISED and is never swapped
    for its upstream (the avatar attached the upstream three) -- else the
    upstream name, else nothing."""
    ok = _attachable(rows)
    out = []
    for name in SUPERPOWERS_PROCESS:
        for candidate in (f"ade-{name}", name):
            if ok.get(candidate):
                out.append(candidate)
                break
    return out


def attach(rows, attached, name) -> tuple[list[str], str]:
    ok = _attachable(rows)
    name = str(name).strip().lstrip("-")
    if name not in ok:
        return list(attached), (f"No skill named {name}. /skill lists what "
                                "is available.")
    if not ok[name]:
        return list(attached), f"{name} is too large to attach (over the cap)."
    if name in attached:
        return list(attached), f"{name} is already attached."
    return list(attached) + [name], (f"Attached {name}. Asks and /type tasks "
                                     f"will follow it. /unskill {name} removes it.")


def detach(attached, name) -> tuple[list[str], str]:
    name = str(name).strip().lstrip("-")
    if name not in attached:
        return list(attached), f"{name} is not attached."
    return [a for a in attached if a != name], f"Removed {name}."


def skill_list_text(rows, attached) -> str:
    ok = _attachable(rows)
    names = sorted(n for n, a in ok.items() if a)
    big = sorted(n for n, a in ok.items() if not a)
    head = f"Attached: {', '.join(attached)}\n\n" if attached else ""
    text = (head + "/skill <name> to attach, /unskill <name> to remove, "
            "/superpowers for the process set.\n\n"
            f"{len(names)} available:\n" + ", ".join(names))
    if big:
        text += "\n\nToo large to attach (over the cap): " + ", ".join(big)
    return text
