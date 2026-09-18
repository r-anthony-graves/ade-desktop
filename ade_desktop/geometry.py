"""Remembered window state that cannot open the window off-screen.

The avatar's saved position went stale when the monitor layout changed and
the window opened where nobody could see it. A remembered rectangle is kept
only if a usable piece of it (100 x 50 px) lands on a screen that exists
now; otherwise it is centred on the primary screen.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

MIN_VISIBLE_W = 100
MIN_VISIBLE_H = 50


@dataclass(frozen=True)
class Rect:
    x: int
    y: int
    w: int
    h: int


def _overlap(a: Rect, b: Rect) -> tuple[int, int]:
    w = min(a.x + a.w, b.x + b.w) - max(a.x, b.x)
    h = min(a.y + a.h, b.y + b.h) - max(a.y, b.y)
    return max(0, w), max(0, h)


def centred_on(screen: Rect, w: int, h: int) -> Rect:
    w = min(w, screen.w)
    h = min(h, screen.h)
    return Rect(screen.x + (screen.w - w) // 2,
                screen.y + (screen.h - h) // 2, w, h)


def clamp_to_screens(rect: Rect, screens: list[Rect]) -> Rect:
    """`screens[0]` is the primary screen."""
    if not screens:
        return rect
    for screen in screens:
        w, h = _overlap(rect, screen)
        if w >= MIN_VISIBLE_W and h >= MIN_VISIBLE_H:
            return rect
    return centred_on(screens[0], rect.w, rect.h)


def state_dir() -> Path:
    """ADE_DESKTOP_STATE_DIR, or %APPDATA%\\ade-desktop. Tests and --smoke
    set the variable so they never touch the real window.json."""
    override = os.environ.get("ADE_DESKTOP_STATE_DIR")
    if override:
        return Path(override)
    base = os.environ.get("APPDATA") or str(Path.home())
    return Path(base) / "ade-desktop"


def load_state(path: Path) -> dict:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def save_state(path: Path, state: dict) -> None:
    """Best effort: a window that cannot remember its size is a nuisance,
    one that crashes on close is a bug."""
    path = Path(path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
        os.replace(tmp, path)
    except OSError:
        pass


def rect_from_state(state: dict) -> Rect | None:
    try:
        return Rect(int(state["x"]), int(state["y"]),
                    int(state["w"]), int(state["h"]))
    except (KeyError, TypeError, ValueError):
        return None
