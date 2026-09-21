"""The Day tab's text, from The Path's /api/day. Pure: no Qt, no calls."""

from __future__ import annotations


def next_step(s: dict) -> int | None:
    day = s.get("day") or {}
    if not day or day.get("state") in ("reflected", "mirrored"):
        return None
    return len(day.get("steps") or {}) + 1


def can_ask_mirror(s: dict) -> bool:
    return (s.get("day") or {}).get("state") == "reflected"


def _src(label: str, src: dict) -> str:
    return (f"{label} — {src.get('attribution', '')} · standpoint: "
            f"{src.get('standpoint', '')}\n{src.get('passage') or ''}")


def day_text(s: dict) -> str:
    state = s.get("state")
    if state == "criteria_unmarked":
        return ("This cycle's charter has no marked criteria yet, so no day can be "
                "composed. Mark its goal and criteria below — that is yours to do, "
                "and it needs your token.\n\n" + str(s.get("message") or ""))
    if state in ("no_cycle", "none"):
        return str(s.get("message") or "Nothing today.")
    o, d = s.get("orientation") or {}, s.get("day") or {}
    ch, pv = o.get("chain") or {}, d.get("preview") or {}
    est = pv.get("estimate") or {}
    parts = [f"TODAY'S LESSON\nTopic: {pv.get('topic', '')}",
             f"Estimated deep-dive time: {est.get('total', '?')} minutes "
             f"(reading ~{est.get('reading')} · refract ~{est.get('refract')} · "
             f"four reflections ~{est.get('reflect')})",
             str(pv.get("text") or ""),
             "\nWHY TODAY",
             f"  Path goal   {ch.get('path_goal', '')}",
             f"  Stage       {ch.get('stage', '')} · {ch.get('stage_number')} of "
             f"{ch.get('stages_total')} · attempt {ch.get('attempt')}",
             f"  Cycle goal  {ch.get('cycle_goal', '')}",
             f"  Criterion   {(d.get('criterion') or {}).get('body', '')}",
             f"  Today       {d.get('objective', '')}",
             "\nWHERE YOU ARE",
             f"  day {o.get('day_number')} of {o.get('of')} "
             f"({o.get('mirrored', 0)} mirrored, {o.get('legacy', 0)} legacy)"]
    parts += [f"  {c.get('body', '')} — {c.get('days', 0)} day(s)"
              for c in o.get("coverage") or []]
    parts.append("\n1 · READ\n" + _src("", d.get("read") or {}))
    parts.append("\n2 · REFRACT\na) across traditions")
    across = d.get("across") or []
    parts += [_src("  •", a) for a in across] or \
        ["  The library holds no other tradition on this."]
    if d.get("split"):
        parts.append(f"  Where they split ({d['split'].get('cause')}): "
                     f"{d['split'].get('text')}")
    parts.append("b) through lenses (Ade's reading)")
    parts += [f"  {k}: {v}" for k, v in (d.get("lenses") or {}).items()]
    life = d.get("life") or []
    if life:
        parts.append("c) through your life")
        parts += [f"  You wrote: {l.get('quote')} — {l.get('charter_claim')}"
                  for l in life]
    parts.append("\n3 · REFLECT")
    steps = d.get("steps") or {}
    for n, q in sorted((d.get("questions") or {}).items(), key=lambda kv: int(kv[0])):
        parts.append(f"  {n}. {q}")
        if str(n) in steps:
            parts.append(f"     You wrote: {steps[str(n)]}")
    if d.get("mirror"):
        parts.append("\nADE'S MIRROR (a reading, never a grade)")
        parts += [f"  {m}" for m in d["mirror"]]
    elif d.get("state") == "reflected":
        parts.append("\nAll four written. Ask Ade for the mirror to close the day.")
    return "\n".join(parts)
