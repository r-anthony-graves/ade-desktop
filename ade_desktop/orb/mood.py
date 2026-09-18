"""The orb's mood decision core: a verbatim port of adeos/avatar/mood.js.

Raw inputs become a mood FRAME the glyph renders every frame:
  feed(state)  every Ade OS poll picks the resting mood (offline -> dormant,
               pending -> attentive, busy -> thinking, quiet idle -> None).
  event(type)  one-shot impulses: approved -> satisfied, failed -> troubled,
               wake -> startled.
  tint(inp,ms) the sentiment of a reply about to be spoken; colour only,
               held for the speech window.
  frame(now)   the live {mood, mode, burst, tint} the glyph reads.
Pure: the clock is injected (milliseconds), so tests drive time.
"""

from __future__ import annotations

import math
import re
import time

MODE_DEFAULT = "auto"
BURST_MS = {"approved": 1400, "failed": 2000, "wake": 700}
SHAPE_OF = {"startled": "linear", "satisfied": "swell", "troubled": "linear"}
MOOD_OF = {"approved": "satisfied", "failed": "troubled", "wake": "startled"}
POS = {"good": 1, "great": 2, "nice": 1, "thanks": 1, "thank": 1, "love": 2,
       "happy": 1, "glad": 1, "awesome": 2, "perfect": 2, "done": 1,
       "ready": 0.8, "welcome": 1, "works": 1, "okay": 0.8, "fine": 0.6,
       "sure": 0.8, "please": 0.4, "yes": 1, "yep": 0.8, "help": 0.6,
       "better": 0.8, "solved": 1, "fixed": 1, "excellent": 2, "best": 1.5,
       "loved": 2, "amazing": 2, "relaxing": 1}
NEG = {"no": -1, "nope": -1, "bad": -1.2, "wrong": -1, "error": -1,
       "failed": -1, "fail": -1, "sorry": -1, "crash": -1, "down": -1,
       "deny": -0.8, "denied": -0.8, "cannot": -0.8, "cant": -0.8,
       "stop": -0.6, "stuck": -1, "broken": -1, "unavailable": -0.8,
       "worried": -0.8, "troubled": -0.8, "worse": -1, "awful": -1.5,
       "lost": -1, "missing": -0.8}
NEGATE = {"not", "never", "cannot", "cant"}


def _clamp(v, a, b):
    return a if v < a else (b if v > b else v)


def sentiment(text) -> dict:
    """A deliberately small lexicon: enough to tint a speech window, cheap
    enough to run on every reply. A negator flips and halves the next 3
    tokens."""
    src = "" if text is None else str(text)
    hot = bool(re.search(r"[A-Z]{3,}|!{2,}", src))
    words = [w for w in re.sub(r"[^a-z' ]", " ", src.lower()).split() if w]
    total, from_neg = 0.0, 0
    for w in words[:120]:
        hit = POS.get(w, NEG.get(w, 0))
        if hit != 0 and from_neg > 0:
            hit = -hit * 0.5
        total += hit
        from_neg = 3 if w in NEGATE else max(0, from_neg - 1)
    return {"score": float(round(_clamp(total / 3, -1.0, 1.0), 3)), "hot": hot}


class Mood:
    def __init__(self, clock=None) -> None:
        self._clock = clock or (lambda: time.monotonic() * 1000.0)
        self._s = {"online": False, "busy": False, "pending": 0, "brain": ""}
        self._mode = MODE_DEFAULT
        self._burst_mood = None
        self._burst_until = 0.0
        self._burst_ms = 0.0
        self._tint = None
        self._tint_until = 0.0

    def now(self) -> float:
        return self._clock()

    def _base(self):
        if not self._s["online"]:
            return "dormant"
        if self._s["pending"] > 0:
            return "attentive"
        if self._s["busy"]:
            return "thinking"
        return None

    def feed(self, st, mode=None) -> None:
        st = st or {}
        self._s["online"] = bool(st.get("online"))
        self._s["busy"] = bool(st.get("busy"))
        self._s["pending"] = int(st.get("pending") or 0)
        self._s["brain"] = st.get("brain") or ""
        if isinstance(mode, str) and mode:
            self._mode = mode
        if isinstance(st.get("mode"), str) and st.get("mode"):
            self._mode = st["mode"]

    def event(self, kind, t=None) -> None:
        if kind not in MOOD_OF:
            return
        at = self.now() if t is None else t
        self._burst_mood = MOOD_OF[kind]
        self._burst_ms = BURST_MS[kind]
        self._burst_until = at + self._burst_ms

    def tint(self, inp, ms=None, t=None) -> None:
        obj = inp if isinstance(inp, dict) else {"score": float(inp or 0), "hot": False}
        try:
            sc = float(obj.get("score"))
        except (TypeError, ValueError):
            sc = float("nan")
        hot = bool(obj.get("hot"))
        if not math.isfinite(sc) or (abs(sc) < 0.08 and not hot):
            self._tint = None
            return
        dur = max(0.0, min(4000.0 if ms is None else float(ms), 8000.0))
        if sc < -0.08:
            self._tint = {"r": 0.92, "g": 0.64, "b": 0.64, "f": 0}
        elif sc > 0.08:
            self._tint = {"r": 1, "g": 0.99, "b": 0.87, "f": 1 if hot else 0}
        else:
            self._tint = {"r": 1, "g": 0.86, "b": 0.55, "f": 1}
        self._tint_until = (self.now() if t is None else t) + dur

    def frame(self, t=None) -> dict:
        at = self.now() if t is None else t
        base = self._base()
        mood, burst = base, 0.0
        if self._burst_mood and self._burst_until > at and base != "dormant":
            mood = self._burst_mood
            u = _clamp((self._burst_until - at) / self._burst_ms, 0, 1)
            burst = math.sin(math.pi * u) if SHAPE_OF[self._burst_mood] == "swell" else u
        else:
            self._burst_mood = None
        tint = None
        if self._tint and at < self._tint_until:
            tint = self._tint
        else:
            self._tint = None
        return {"mood": mood, "mode": self._mode, "burst": round(burst, 3), "tint": tint}
