"""Files and folders dropped or picked for /v1/upload.

Walked within the avatar's limits (adeos/avatar/main.js walkUpload /
adeUpload) and trimmed BEFORE anything is sent, so the report is accurate
rather than discovered halfway through. Paths are kept relative to the
dropped item's PARENT, joined with '/': that is the `relpath` Ade OS
validates on its side.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

MAX_FILES = 500
MAX_TOTAL = 50 * 1024 * 1024
MAX_DEPTH = 16
SKIP_DIRS = frozenset({".git", "node_modules", "__pycache__", ".venv", "venv"})


@dataclass(frozen=True)
class UploadFile:
    full: Path
    rel: str
    size: int


@dataclass
class UploadPlan:
    send: list[UploadFile] = field(default_factory=list)
    skipped: list[tuple[str, str]] = field(default_factory=list)
    found: int = 0


def walk(paths) -> UploadPlan:
    wanted: list[UploadFile] = []
    plan = UploadPlan()
    for p in paths or []:
        if not p:
            continue
        root = Path(p)
        base = root.parent
        stack = [(root, 0)]
        while stack:
            current, depth = stack.pop()
            rel = current.relative_to(base).as_posix()
            try:
                is_dir = current.is_dir()
                is_file = current.is_file()
            except OSError as exc:
                plan.skipped.append((rel, type(exc).__name__))
                continue
            if is_dir:
                if current.name in SKIP_DIRS:
                    plan.skipped.append((rel, "skipped by name"))
                    continue
                if depth >= MAX_DEPTH:
                    plan.skipped.append((rel, f"deeper than {MAX_DEPTH}"))
                    continue
                try:
                    children = sorted(os.listdir(current), reverse=True)
                except OSError as exc:
                    plan.skipped.append((rel, type(exc).__name__))
                    continue
                stack.extend((current / name, depth + 1) for name in children)
            elif is_file:
                try:
                    size = current.stat().st_size
                except OSError as exc:
                    plan.skipped.append((rel, type(exc).__name__))
                    continue
                wanted.append(UploadFile(current, rel, size))
            else:
                plan.skipped.append((rel, "not a regular file"))
    wanted.sort(key=lambda f: f.rel)
    plan.found = len(wanted)
    total = 0
    for f in wanted:
        if len(plan.send) >= MAX_FILES:
            plan.skipped.append((f.rel, f"over {MAX_FILES} files"))
            continue
        if total + f.size > MAX_TOTAL:
            plan.skipped.append((f.rel, "over the 50 MB drop limit"))
            continue
        plan.send.append(f)
        total += f.size
    return plan


def report(sent, bytes_, found, skipped, failed) -> str:
    lines = [f"Sent {sent} of {found} files ({bytes_ / 1024:.1f} KB)."]
    if skipped:
        lines.append("Skipped: " + "; ".join(f"{p} ({why})" for p, why in skipped))
    if failed:
        lines.append("Failed: " + "; ".join(f"{p} ({why})" for p, why in failed))
    return "\n".join(lines)
