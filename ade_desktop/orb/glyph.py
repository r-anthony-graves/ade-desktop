"""The orb's glyph: a QPainter port of adeos/avatar/glyph.js in AVATAR mode.

Same geometry, same time bases, same camera, same passes in the same order,
same constants -- so the orb Ray sees here is the avatar he already knows.
What avatar mode drops (the cosmic cloud, the starfield, the dust, the
grain, the bloom -- LIGHT is true, so bloom never ran) is dropped here too.

Two deliberate departures, both recorded in the piece-3 spec:
  * depth banding uses 4 bands where the JS uses 9, to keep the Python
    draw-call count down;
  * the idle "ember" is floored at 0 and re-sparks after its 20-40 s
    `ambient` countdown, which is what glyph.js's own comment says it does.
    The JS decrements it without a floor and never reads `ambient`.

Pure apart from QPainter: time comes in as `now` (seconds), so tests pin it.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass

from PySide6.QtCore import QLineF, QPointF, QRectF, Qt
from PySide6.QtGui import (QColor, QImage, QLinearGradient, QPainter, QPen,
                           QPixmap, QPolygonF, QRadialGradient)

TAU = math.pi * 2
CYCLE = 24.0
BANDS = 4

# ------------------------------------------------------------------ utility


def clamp(v, a, b):
    return a if v < a else (b if v > b else v)


def lerp(a, b, t):
    return a + (b - a) * t


def ss(a, b, x):
    t = clamp((x - a) / (b - a), 0.0, 1.0)
    return t * t * (3 - 2 * t)


def ease_out(x):
    k = 1 - x
    return 1 - k * k * k


def _imul(a, b):
    return (a * b) & 0xFFFFFFFF


def rng(seed):
    """mulberry32, bit for bit the JS rng(): same seeds, same scatter."""
    state = [seed & 0xFFFFFFFF]

    def nxt():
        a = (state[0] + 0x6D2B79F5) & 0xFFFFFFFF
        state[0] = a
        t = _imul(a ^ (a >> 15), 1 | a)
        t = ((t + _imul(t ^ (t >> 7), 61 | t)) & 0xFFFFFFFF) ^ t
        return ((t ^ (t >> 14)) & 0xFFFFFFFF) / 4294967296
    return nxt


def mix(a, b, t):
    return (int(a[0] + (b[0] - a[0]) * t), int(a[1] + (b[1] - a[1]) * t),
            int(a[2] + (b[2] - a[2]) * t))


def mul3(c, tt):
    return (clamp(c[0] * tt["r"], 0, 255), clamp(c[1] * tt["g"], 0, 255),
            clamp(c[2] * tt["b"], 0, 255))


def qc(c, a=1.0) -> QColor:
    a = 0.0 if a < 0 else (1.0 if a > 1 else a)
    return QColor(int(c[0]), int(c[1]), int(c[2]), int(round(a * 255)))


# ------------------------------------------------------------------ palette
GOLD, GOLDH, BLUE, BLUEH = (239, 122, 30), (247, 206, 62), (142, 27, 42), (224, 74, 30)
WHITE, CYAN, STEEL = (255, 244, 214), (245, 166, 35), (122, 130, 142)
LISTEN, LISTENH = (86, 196, 214), (176, 240, 248)
ALERT = (178, 18, 43)
BACKING = (203, 209, 217)

MOODS = {
    "dormant":   {"res": 0.05, "hot": STEEL,   "mid": STEEL,  "halo": STEEL,  "breathe": 0.10, "spiral": 0.0},
    "attentive": {"res": 0.35, "hot": LISTENH, "mid": LISTEN, "halo": LISTEN, "breathe": 0.22, "spiral": 0.6},
    "thinking":  {"res": 0.80, "hot": GOLDH,   "mid": GOLD,   "halo": GOLD,   "breathe": 0.28, "spiral": 1.6},
    "speaking":  {"res": 0.62, "hot": GOLDH,   "mid": GOLD,   "halo": GOLD,   "breathe": 0.30, "spiral": 0.6},
    "satisfied": {"res": 0.55, "hot": GOLDH,   "mid": GOLD,   "halo": GOLD,   "breathe": 0.18, "spiral": 0.3},
    "startled":  {"res": 0.90, "hot": WHITE,   "mid": GOLDH,  "halo": WHITE,  "breathe": 0.60, "spiral": 0.9},
    "troubled":  {"res": 0.18, "hot": ALERT,   "mid": STEEL,  "halo": ALERT,  "breathe": 0.30, "spiral": 0.15},
}

# ---------------------------------------------------------- the time bases
FLOW_K, W0 = 0.74, TAU / CYCLE
FLOW_OFF = math.sin(W0 * (-18))
KEYS = [(0, 0.06), (3, 0.14), (7, 0.30), (12, 0.52), (16, 0.86), (18, 1.00),
        (20, 0.93), (22, 0.44), (24, 0.06)]


def flow(t):
    return t / CYCLE + (FLOW_K / TAU) * (math.sin(W0 * (t - 18)) - FLOW_OFF)


def resonance(t):
    for i in range(len(KEYS) - 1):
        if KEYS[i][0] <= t <= KEYS[i + 1][0]:
            return lerp(KEYS[i][1], KEYS[i + 1][1], ss(KEYS[i][0], KEYS[i + 1][0], t))
    return KEYS[0][1]


def assembly(t):
    return min(ss(0, 3, t), 1 - ss(22.4, 24, t))


# ----------------------------------------------------------------- geometry
R, PLANE_TILT, WORLD_R = 1.0, 0.22, 3.3


def rot_x(p, a):
    c, s = math.cos(a), math.sin(a)
    return (p[0], p[1] * c - p[2] * s, p[1] * s + p[2] * c)


def _build_nodes():
    nr = rng(90210)
    out = []

    def push(p, kind, k):
        sc = ((nr() - 0.5) * 2.6, (nr() - 0.5) * 2.6, (nr() - 0.5) * 2.6)
        out.append({"p": rot_x(p, PLANE_TILT), "kind": kind, "k": k, "sc": sc,
                    "delay": nr() * 0.55})
    push((0, 0, 0), "core", -1)
    for k in range(6):
        a = -math.pi / 2 + k * math.pi / 3
        push((math.cos(a) * R, math.sin(a) * R, 0), "inner", k)
    for k in range(6):
        a = -math.pi / 2 + k * math.pi / 3
        push((math.cos(a) * 2 * R, math.sin(a) * 2 * R, 0), "outer", k)
    return out


NODES = _build_nodes()


def IN(k):
    return 1 + ((k % 6) + 6) % 6


def OUT(k):
    return 7 + ((k % 6) + 6) % 6


def _build_edges():
    e = []
    for k in range(6):
        e.append((0, IN(k), 1.00, GOLD))
        e.append((IN(k), OUT(k), 0.92, GOLD))
        e.append((IN(k), IN(k + 1), 0.74, mix(GOLD, BLUE, 0.45)))
        e.append((OUT(k), OUT(k + 1), 0.74, mix(GOLD, BLUE, 0.45)))
        e.append((IN(k), IN(k + 2), 0.52, BLUE))
        e.append((OUT(k), OUT(k + 2), 0.52, BLUE))
        e.append((IN(k), OUT(k + 1), 0.34, BLUE))
        e.append((IN(k), OUT(k - 1), 0.34, BLUE))
        e.append((IN(k), OUT(k + 2), 0.24, BLUE))
        e.append((IN(k), OUT(k - 2), 0.24, BLUE))
    return e


EDGES = _build_edges()


def _build_circles():
    out = []
    for n in NODES:
        cp, pts = n["p"], []
        for s in range(37):
            ang = s / 36 * TAU
            lp = rot_x((math.cos(ang) * R * 0.5, math.sin(ang) * R * 0.5, 0), PLANE_TILT)
            pts.append((cp[0] + lp[0], cp[1] + lp[1], cp[2] + lp[2]))
        out.append(pts)
    return out


CIRCLES = _build_circles()
_o, _c, _m = 1.18, 0.70, 0.88
OCT_V = [(_o, 0, 0), (-_o, 0, 0), (0, _o, 0), (0, -_o, 0), (0, 0, _o), (0, 0, -_o)]
OCT_E = [(0, 2), (0, 3), (0, 4), (0, 5), (1, 2), (1, 3), (1, 4), (1, 5), (2, 4), (2, 5), (3, 4), (3, 5)]
CUB_V = [(_c, _c, _c), (_c, _c, -_c), (_c, -_c, _c), (_c, -_c, -_c),
         (-_c, _c, _c), (-_c, _c, -_c), (-_c, -_c, _c), (-_c, -_c, -_c)]
CUB_E = [(0, 1), (0, 2), (0, 4), (1, 3), (1, 5), (2, 3), (2, 6), (3, 7), (4, 5), (4, 6), (5, 7), (6, 7)]
TET_A = [(_m, _m, _m), (_m, -_m, -_m), (-_m, _m, -_m), (-_m, -_m, _m)]
TET_B = [(-_m, -_m, -_m), (-_m, _m, _m), (_m, -_m, _m), (_m, _m, -_m)]
TET_E = [(0, 1), (0, 2), (0, 3), (1, 2), (1, 3), (2, 3)]

RINGS = [
    {"r": 3.06, "tx": 0.18, "tz": 0.09, "turns": -2, "col": BLUE},
    {"r": 2.62, "tx": -0.58, "tz": 0.30, "turns": 3, "col": mix(BLUE, GOLD, 0.30)},
    {"r": 2.20, "tx": 0.98, "tz": -0.36, "turns": -4, "col": mix(BLUE, GOLD, 0.55)},
    {"r": 1.78, "tx": -1.16, "tz": 0.58, "turns": 5, "col": mix(BLUE, GOLD, 0.75)},
    {"r": 1.42, "tx": 1.34, "tz": -0.22, "turns": -7, "col": GOLD},
]
RING_ANGLES = [si / 108 * TAU for si in range(109)]
for _rr in RINGS:
    _rr["cx"], _rr["sx"] = math.cos(_rr["tx"]), math.sin(_rr["tx"])
    _rr["cz"], _rr["sz"] = math.cos(_rr["tz"]), math.sin(_rr["tz"])


def _build_arcs():
    ar, out, at = rng(31337), [], 0.0
    while at < CYCLE:
        if ar() < 0.06 + 0.62 * resonance(at):
            na, nb = 1 + int(ar() * 12), 1 + int(ar() * 12)
            if na == nb:
                nb = 1 + (nb % 12)
            out.append({"t0": at, "dur": 0.16 + ar() * 0.30, "a": na, "b": nb,
                        "seed": int(ar() * 100000), "hue": ar()})
        at += 0.085
    return out


ARCS = _build_arcs()
TRIPS = 14
_pr2 = rng(24680)
SPOKE_JIT = [(_pr2() * TAU, _pr2() * TAU, _pr2() * TAU) for _ in range(6)]
CHAINS = 6
WAVES = 18


def stage_glow(u, k):
    f = (5 * CHAINS * u) % 5
    d = f - k
    if d > 2.5:
        d -= 5
    if d < -2.5:
        d += 5
    return math.exp(-d * d * 3.0)


def ring_point(rr, a, sc):
    x, z = math.cos(a) * rr["r"] * sc, math.sin(a) * rr["r"] * sc
    y1, z1 = -z * rr["sx"], z * rr["cx"]
    return (x * rr["cz"] - y1 * rr["sz"], x * rr["sz"] + y1 * rr["cz"], z1)


# ---------------------------------------------------------------- the look
@dataclass
class Look:
    """What Ade is doing, as the renderer reads it. `mood` is a Mood.frame()
    dict (None = no mood core wired); speak/hear are TARGET levels 0..1 that
    the renderer smooths itself, exactly as ADE.step does."""
    online: bool = False
    busy: bool = False
    pending: int = 0
    mood: dict | None = None
    speak: float = 0.0
    hear: float = 0.0
    mic_open: bool = False
    breathe: bool = True
    backing: bool = True


class GlyphRenderer:
    def __init__(self, epoch: float | None = None) -> None:
        self.res, self.speaking, self.hearing = 0.10, 0.0, 0.0
        self.alert, self.mic_lit, self.spark = 0.0, 0.0, 0.0
        self.ember, self.ambient = 0.0, 0.0
        self.mood, self.mode, self.burst, self.tint, self.flick = None, "auto", 0.0, None, 0
        self.hot, self.mid, self.halo = GOLDH, GOLD, GOLD
        self.epoch, self.last, self.nows = epoch, None, 0.0
        self.wake_at = -99.0
        self.live_arcs: list[dict] = []
        self.live_waves: list[dict] = []
        self._lr = rng(90909)
        self._rand = random.Random()
        self._sprites: dict = {}
        self.last_core = (GOLDH, GOLD)
        self.last_res = 0.0

    # ---------------------------------------------------------- state
    def wake(self, now: float) -> None:
        self.wake_at = now
        for _ in range(3):
            self._spawn_onset(now)

    def wake_kick(self) -> float:
        k = 1 - (self.nows - self.wake_at) / 0.45
        return k * k if k > 0 else 0.0

    def _spawn_onset(self, now):
        lr = self._lr
        for _ in range(1 + int(lr() * 3)):
            a, b = 1 + int(lr() * 12), 1 + int(lr() * 12)
            if a == b:
                b = 1 + (b % 12)
            self.live_arcs.append({"born": now, "dur": 0.16 + lr() * 0.26, "a": a, "b": b,
                                   "seed": int(lr() * 100000), "hue": lr()})
        self.live_waves.append({"born": now})
        del self.live_arcs[:-28]
        del self.live_waves[:-6]

    def _pull_mood(self, f):
        self.mode = (f or {}).get("mode") or "auto"
        if not f or f.get("mood") not in MOODS:
            self.mood, self.burst, self.tint, self.flick = None, 0.0, None, 0
        else:
            self.mood = f["mood"]
            self.burst = clamp(f.get("burst") or 0, 0, 1)
            self.tint = f.get("tint") or None
            self.flick = 1 if (self.tint and self.tint.get("f")) else 0
        m = MOODS.get(self.mood) if self.mood else None
        if not m or not self.tint:
            self.hot = m["hot"] if m else GOLDH
            self.mid = m["mid"] if m else GOLD
            self.halo = m["halo"] if m else GOLD
            return
        k = self.burst
        self.hot = mul3(mix(m["hot"], WHITE, k * 0.55), self.tint)
        self.mid = mul3(mix(m["mid"], GOLDH, k * 0.35), self.tint)
        self.halo = mul3(mix(m["halo"], WHITE, k * 0.40), self.tint)

    def _step(self, look: Look, dt: float):
        target = (0.04 if not look.online else
                  (MOODS[self.mood]["res"] if self.mood else
                   (0.94 if look.pending > 0 else (0.74 if look.busy else 0.22))))
        self.res += (target - self.res) * (1 - math.exp(-dt / 0.85))
        sp = clamp(float(look.speak or 0), 0.0, 1.0)
        self.speaking += (sp - self.speaking) * (1 - math.exp(-dt / (0.035 if sp > self.speaking else 0.13)))
        self.alert += ((1 if look.pending > 0 else 0) - self.alert) * (1 - math.exp(-dt / 0.35))
        hr = clamp(float(look.hear or 0), 0.0, 1.0)
        self.hearing += (hr - self.hearing) * (1 - math.exp(-dt / (0.030 if hr > self.hearing else 0.16)))
        self.mic_lit += ((1 if look.mic_open else 0) - self.mic_lit) * (1 - math.exp(-dt / 0.10))

    def state(self) -> dict:
        """The smoothed values the drawing reads (the JS _state())."""
        return {"res": self.last_res, "speaking": self.speaking, "hearing": self.hearing,
                "alert": self.alert, "mic_lit": self.mic_lit, "mood": self.mood,
                "ember": self.ember, "core": self.last_core}

    # ------------------------------------------------------ projection
    def _camera(self, t, res):
        ph = TAU * t / CYCLE
        g_rot = ph - 1.0472
        yaw = 0.50 * math.sin(ph)
        pit = 0.17 + 0.115 * math.sin(ph + 2.0)
        roll = 0.022 * math.sin(ph * 2 + 0.7)
        self.cam_d = 9.6 + 0.72 * math.sin(ph + 0.6) - 0.5 * res
        self.sg, self.cg = math.sin(g_rot), math.cos(g_rot)
        self.sy, self.cy = math.sin(yaw), math.cos(yaw)
        self.sp, self.cp = math.sin(pit), math.cos(pit)
        self.sr, self.cr = math.sin(roll), math.cos(roll)
        self.focal = self.PX * self.cam_d / WORLD_R

    def P(self, p, spin=0.0):
        """xf() then proj(): (x, y, s, z, d) with d = 1 nearest the lens."""
        x, y, z = p
        if spin:
            s0, c0 = math.sin(spin), math.cos(spin)
            x, z = x * c0 + z * s0, -x * s0 + z * c0
        x, z = x * self.cg + z * self.sg, -x * self.sg + z * self.cg
        x, z = x * self.cy + z * self.sy, -x * self.sy + z * self.cy
        y, z = y * self.cp - z * self.sp, y * self.sp + z * self.cp
        z += self.cam_d
        z = 0.35 if z < 0.35 else z
        f = self.focal / z
        dx, dy = x * f, -y * f
        if self.sr:
            dx, dy = dx * self.cr - dy * self.sr, dx * self.sr + dy * self.cr
        d = clamp((self.cam_d + WORLD_R - z) / (2 * WORLD_R), 0.0, 1.0)
        return (self.CX + dx, self.CY + dy, f, z, d)

    # ---------------------------------------------------------- drawing
    def _sprite(self, c) -> QPixmap:
        sp = self._sprites.get(c)
        if sp is None:
            img = QImage(64, 64, QImage.Format.Format_ARGB32_Premultiplied)
            img.fill(Qt.GlobalColor.transparent)
            g = QRadialGradient(32, 32, 32)
            g.setColorAt(0, qc(c, 1))
            g.setColorAt(0.16, qc(c, 0.66))
            g.setColorAt(0.42, qc(c, 0.17))
            g.setColorAt(1, qc(c, 0))
            p = QPainter(img)
            p.fillRect(0, 0, 64, 64, g)
            p.end()
            sp = self._sprites[c] = QPixmap.fromImage(img)
        return sp

    def _dot(self, c, x, y, r, a):
        if a <= 0.004 or r <= 0.06:
            return
        g = self.g
        g.setOpacity(1.0 if a > 1 else a)
        g.drawPixmap(QRectF(x - r, y - r, r * 2, r * 2), self._sprite(c), _SRC)

    def _pen(self, col, a, w):
        pen = QPen(qc(col, a), w)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        return pen

    def _stroke_banded(self, pts, col, base_w, base_a, glow):
        """The JS strokes one path of moveTo/lineTo segments per depth band,
        which canvas unions, so a translucent stroke never doubles where two
        segments meet. Consecutive segments in one band become one polyline
        here for the same reason (drawLines would bead at every joint), and
        a polyline is a third of the cost of the separate round-capped
        segments."""
        runs = [[] for _ in range(BANDS)]
        prev_band, cur = -1, None
        for i in range(len(pts) - 1):
            p0, p1 = pts[i], pts[i + 1]
            if p0[3] < 0.5 or p1[3] < 0.5:
                prev_band = -1
                continue
            b = int((p0[4] + p1[4]) * 0.5 * BANDS)
            b = b if b < BANDS else BANDS - 1
            if b != prev_band:
                cur = [QPointF(p0[0], p0[1])]
                runs[b].append(cur)
                prev_band = b
            cur.append(QPointF(p1[0], p1[1]))
        g, S = self.g, self.S
        g.setOpacity(1.0)
        g.setBrush(Qt.BrushStyle.NoBrush)
        for b, polys in enumerate(runs):
            if not polys:
                continue
            dep = 0.22 + 0.78 * ((b + 0.5) / BANDS)
            polys = [QPolygonF(r) for r in polys]
            if glow:
                g.setPen(self._pen(col, base_a * dep * 0.12, base_w * (2.5 + 5.0 * dep) * S))
                for poly in polys:
                    g.drawPolyline(poly)
            g.setPen(self._pen(col, base_a * dep, max(1.5, base_w * (1.45 + 2.45 * dep) * S)))
            for poly in polys:
                g.drawPolyline(poly)

    # ---------------------------------------------------------- passes
    def _draw_field(self, res, backing):
        if not backing:
            return
        rad = min(self.PX * 1.24, min(self.W, self.H) * 0.5 - 1)
        k = 0.62 + 0.22 * res
        bk = QRadialGradient(self.CX, self.CY, rad)
        for stop, m in ((0, 1), (0.26, 0.80), (0.56, 0.34), (0.80, 0.09)):
            bk.setColorAt(stop, qc(BACKING, k * m))
        bk.setColorAt(1, qc(BACKING, 0))
        g = self.g
        g.setOpacity(1.0)
        g.setPen(Qt.PenStyle.NoPen)
        g.setBrush(bk)
        g.drawEllipse(QPointF(self.CX, self.CY), rad, rad)

    def _draw_volumetrics(self, t, res, asm):
        c = self.P((0, 0, 0))
        hv = 0.40
        halo = 300 * self.S * (0.55 + 0.9 * res) * (0.3 + 0.7 * asm) * (self.focal / 900) * 0.82
        h0 = self.halo if self.mood else GOLD
        h1 = mix(self.halo, BLUEH, 0.45) if self.mood else BLUEH
        h2 = mix(self.halo, BLUE, 0.6) if self.mood else BLUE
        hg = QRadialGradient(c[0], c[1], halo)
        hg.setColorAt(0, qc(h0, (0.20 * res + 0.05) * hv))
        hg.setColorAt(0.16, qc(h1, (0.11 * res + 0.03) * hv))
        hg.setColorAt(0.44, qc(h2, (0.055 * res + 0.015) * hv))
        hg.setColorAt(1, qc(BLUE, 0))
        g = self.g
        g.setOpacity(1.0)
        g.setPen(Qt.PenStyle.NoPen)
        g.setBrush(hg)
        g.drawEllipse(QPointF(c[0], c[1]), halo, halo)
        u = flow(t)
        for i in range(26):
            a = i / 26 * TAU + u * TAU * 0.35 + math.sin(i * 2.3) * 0.1
            ln = halo * (0.55 + 0.45 * abs(math.sin(i * 1.7 + u * TAU * 2))) * (0.5 + 0.5 * res)
            wdt = (2.2 + 2.6 * math.sin(i * 3.1)) * self.S
            ca, sa = math.cos(a), math.sin(a)
            cl = self.halo if self.mood else (GOLD if i % 3 == 0 else BLUEH)
            lg = QLinearGradient(c[0], c[1], c[0] + ca * ln, c[1] + sa * ln)
            lg.setColorAt(0, qc(cl, 0.115 * res * asm * hv))
            lg.setColorAt(1, qc(cl, 0))
            g.setBrush(lg)
            g.drawPolygon(QPolygonF([
                QPointF(c[0], c[1]),
                QPointF(c[0] + ca * ln - sa * wdt, c[1] + sa * ln + ca * wdt),
                QPointF(c[0] + ca * ln + sa * wdt, c[1] + sa * ln - ca * wdt)]))

    def _draw_rings(self, t, u, res, asm):
        scale = lerp(1.85, 1, ease_out(asm))
        spin_gate = ss(2.6, 7, t) * 0.55 + 0.45
        spiral = MOODS[self.mood]["spiral"] if self.mood else 0.0
        calm = 0.16 if (self.mode == "ask-first" and not self.mood) else 0.0
        for i, rr in enumerate(RINGS):
            gl = stage_glow(u, i)
            spin = TAU * rr["turns"] * u * spin_gate * (1 + spiral * 0.12)
            pts = [self.P(ring_point(rr, a + spin, scale)) for a in RING_ANGLES]
            a = (0.32 + 0.50 * res + 0.55 * gl) * asm + calm
            self._stroke_banded(pts, rr["col"], 1.05 + 0.9 * gl, a, True)

    def _update_nodes(self, asm):
        self.NW, self.NP = [], []
        for n in NODES:
            p = n["p"]
            if asm < 0.999:
                e = clamp((asm - n["delay"] * 0.4) / (1 - n["delay"] * 0.4), 0.0, 1.0)
                kk = 1 - ease_out(e)
                sc = n["sc"]
                p = tuple(n["p"][j] * (1 + 1.7 * kk) + sc[j] * kk * 3.1 for j in range(3))
            self.NW.append(p)
            self.NP.append(self.P(p))

    def _draw_structure(self, t, u, res, asm):
        g, S = self.g, self.S
        ca = 0.40 * asm * (0.45 + 0.55 * res)
        if ca > 0.01:
            ccol = mix(BLUE, STEEL, 0.4)
            for ci, src in enumerate(CIRCLES):
                nb, ob = self.NW[ci], NODES[ci]["p"]
                off = (nb[0] - ob[0], nb[1] - ob[1], nb[2] - ob[2])
                pr = [self.P((q[0] + off[0], q[1] + off[1], q[2] + off[2])) for q in src]
                self._stroke_banded(pr, ccol, 0.75, ca, False)
        wk = self.wake_kick()
        lis_e = clamp(0.22 * self.mic_lit + 0.70 * self.hearing + 0.85 * wk, 0.0, 1.0)
        g.setOpacity(1.0)
        for ea, eb, w, ecol in EDGES:
            A, B = self.NP[ea], self.NP[eb]
            if A[3] < 0.5 or B[3] < 0.5:
                continue
            dep = 0.20 + 0.80 * ((A[4] + B[4]) * 0.5)
            pulse = 0.5 + 0.5 * math.sin(TAU * (u * 18) - (ea + eb) * 0.55)
            a = w * asm * (0.30 + 0.60 * res) * dep * (0.72 + 0.5 * pulse * res)
            col = mix(ecol, BLUEH, res * 0.35)
            if lis_e > 0.01:
                col = mix(col, LISTEN, lis_e)
            line = QLineF(A[0], A[1], B[0], B[1])
            g.setPen(self._pen(col, a * 0.16, (2.0 + 6.8 * w * res) * dep * S))
            g.drawLine(line)
            g.setPen(self._pen(col, a, max(1.7, (1.40 + 2.70 * w) * dep * S)))
            g.drawLine(line)
            if res > 0.7 and w > 0.85:
                g.setPen(self._pen(GOLDH, a * (res - 0.7) * 2.4, max(1.1, 0.95 * dep * S)))
                g.drawLine(line)
        self._draw_solid(OCT_V, OCT_E, -u * TAU, mix(BLUE, CYAN, 0.5), 0.44 * asm * (0.3 + 0.7 * res))
        self._draw_solid(CUB_V, CUB_E, u * TAU * 0.5, mix(GOLD, GOLDH, 0.3), 0.34 * asm * (0.3 + 0.7 * res))
        mk = ss(0.68, 0.94, res) * asm
        if mk > 0.01:
            self._draw_solid(TET_A, TET_E, u * TAU * 1.5, GOLDH, 0.46 * mk)
            self._draw_solid(TET_B, TET_E, u * TAU * 1.5, BLUEH, 0.46 * mk)

    def _draw_solid(self, V, E2, spin, col, alpha):
        if alpha <= 0.008:
            return
        g, S = self.g, self.S
        pv = [self.P(v, spin) for v in V]
        for i0, i1 in E2:
            A, B = pv[i0], pv[i1]
            if A[3] < 0.5 or B[3] < 0.5:
                continue
            dep = 0.18 + 0.82 * ((A[4] + B[4]) * 0.5)
            line = QLineF(A[0], A[1], B[0], B[1])
            g.setPen(self._pen(col, alpha * dep * 0.14, 5.4 * dep * S))
            g.drawLine(line)
            g.setPen(self._pen(col, alpha * dep, max(1.5, 2.20 * dep * S)))
            g.drawLine(line)

    def _draw_nodes(self, t, u, res, asm):
        g, S, PX = self.g, self.S, self.PX
        wk = self.wake_kick()
        lis = clamp(0.85 * self.mic_lit + 0.85 * self.hearing + 1.0 * wk, 0.0, 1.0)
        for i in range(1, len(NODES)):
            n, sp = NODES[i], self.NP[i]
            if sp[3] < 0.5:
                continue
            outer = n["kind"] == "outer"
            gl = stage_glow(u, n["k"] % 5) if outer else 0.0
            beat = 0.5 + 0.5 * math.sin(TAU * (u * 22) - (n["k"] * 0.9 if outer else n["k"] * 0.5 + 2.0))
            col = GOLD if outer else mix(BLUE, GOLDH, 0.25)
            hot = mix(col, BLUEH, 0.55 * res)
            if lis > 0.004:
                hot = mix(hot, LISTENH, clamp(lis * 0.95, 0.0, 1.0))
                col = mix(col, LISTEN, clamp(lis * 0.75, 0.0, 1.0))
            base = (7.0 if outer else 5.0) * S * (sp[2] / PX) * (0.62 + 0.38 * res) * (0.55 + 0.45 * beat)
            a = asm * (0.30 + 0.70 * res) * (0.35 + 0.65 * sp[4]) * (1 + 0.85 * wk)
            x, y = sp[0], sp[1]
            self._dot(BLUE, x, y, base * 5.4, a * 0.16 * (0.7 if outer else 1))
            self._dot(GOLD if outer else BLUE, x, y, base * 2.7, a * 0.42 * (1 + gl))
            self._dot(WHITE, x, y, base * 0.95, a * (0.62 + 0.38 * gl))
            if lis > 0.004:
                self._dot(LISTEN, x, y, base * 5.4 * (1 + 0.35 * wk), a * 0.34 * lis)
                self._dot(LISTEN, x, y, base * 2.7 * (1 + 0.45 * wk), a * 0.62 * lis * (1 + gl))
            rr5, rot = base * 1.55, u * TAU * (1 if outer else -1.5) + n["k"]
            poly = QPolygonF([QPointF(x + math.cos(rot + f / 6 * TAU) * rr5,
                                      y + math.sin(rot + f / 6 * TAU) * rr5 * 0.92) for f in range(6)])
            g.setOpacity(1.0)
            g.setPen(self._pen(hot, a * 0.62 * (0.4 + 0.6 * gl), max(1.5, 2.4 * S)))
            g.setBrush(qc(col, a * 0.06))
            g.drawPolygon(poly)
            self._dot(WHITE, x - rr5 * 0.34, y - rr5 * 0.40, base * 0.42, a * 0.55)
        g.setOpacity(1.0)

    def _draw_particles(self, t, u, res, asm):
        g, S, PX = self.g, self.S, self.PX
        scale = lerp(1.85, 1, ease_out(asm))
        spin_gate = ss(2.6, 7, t) * 0.55 + 0.45
        for i, rr in enumerate(RINGS):
            gl = stage_glow(u, i)
            cnt = 7 + int(res * 20 + 0.5)
            spin = TAU * rr["turns"] * u * spin_gate
            pturns, dr = 9 + i * 2, (-1 if rr["turns"] < 0 else 1)
            tail = mix(rr["col"], WHITE, 0.4)
            for j in range(cnt):
                ang = ((u * pturns + j / cnt) % 1) * TAU + spin
                sp = self.P(ring_point(rr, ang, scale))
                if sp[3] < 0.5:
                    continue
                r = (1.5 + 2.4 * res) * S * (sp[2] / PX) * (0.55 + 0.45 * sp[4])
                a = asm * (0.25 + 0.75 * res) * (0.30 + 0.70 * sp[4]) * (0.45 + 0.85 * gl)
                self._dot(BLUE, sp[0], sp[1], r * 4.2, a * 0.24)
                self._dot(WHITE, sp[0], sp[1], r * 1.15, a * 0.85)
                sp2 = self.P(ring_point(rr, ang - dr * 0.045, scale))
                g.setOpacity(clamp(a * 0.35, 0.0, 1.0))
                g.setPen(self._pen(tail, 1, max(1.0, r * 0.95)))
                g.drawLine(QLineF(sp2[0], sp2[1], sp[0], sp[1]))
        g.setOpacity(1.0)
        core = self.NW[0]
        for k in range(6):
            on = self.NW[OUT(k)]
            per = 3 + int(res * 6 + 0.5)
            for m in range(per):
                ph2 = (u * TRIPS + m / per + k * 0.07) % 1
                s3 = 1 - ph2
                acc = s3 * s3 * (3 - 2 * s3)
                wob = math.sin(ph2 * TAU * 3 + SPOKE_JIT[k][0]) * 0.075 * acc
                sp3 = self.P((lerp(core[0], on[0], acc) + wob * 0.6, lerp(core[1], on[1], acc) + wob,
                              lerp(core[2], on[2], acc) + wob * 0.8))
                if sp3[3] < 0.5:
                    continue
                r2 = (2.0 + 2.8 * res) * S * (sp3[2] / PX) * (1.05 - 0.45 * acc)
                a2 = asm * (0.35 + 0.65 * res) * (0.30 + 0.70 * sp3[4]) * (0.35 + 0.65 * (1 - acc))
                self._dot(GOLD, sp3[0], sp3[1], r2 * 4.6, a2 * 0.26)
                self._dot(WHITE, sp3[0], sp3[1], r2 * 1.1, a2)
                b2 = min(1, acc + 0.055)
                sp4 = self.P((lerp(core[0], on[0], b2), lerp(core[1], on[1], b2), lerp(core[2], on[2], b2)))
                lg = QLinearGradient(sp4[0], sp4[1], sp3[0], sp3[1])
                lg.setColorAt(0, qc(GOLD, 0))
                lg.setColorAt(1, qc(GOLDH, a2 * 0.7))
                pen = QPen(lg, max(1.1, r2 * 1.00))
                pen.setCapStyle(Qt.PenCapStyle.RoundCap)
                g.setOpacity(1.0)
                g.setPen(pen)
                g.drawLine(QLineF(sp4[0], sp4[1], sp3[0], sp3[1]))
        form = 1 - asm
        if form > 0.01:
            for d2 in range(230):
                seed = d2 * 0.618034
                ang2, elev = (seed * TAU) % TAU, ((seed * 7.13) % 1) * 2 - 1
                rr6 = math.sqrt(1 - elev * elev)
                rad3 = lerp(0.4, 9.0, (seed * 3.77) % 1) * (0.35 + 0.9 * form)
                sp5 = self.P((rr6 * math.cos(ang2 + u * TAU * 2) * rad3, elev * rad3,
                              rr6 * math.sin(ang2 + u * TAU * 2) * rad3))
                if sp5[3] < 0.5:
                    continue
                a3 = form * 0.95 * (0.3 + 0.7 * sp5[4]) * (0.55 + 0.45 * math.sin(seed * 11 + t * 3))
                self._dot(GOLD if d2 % 2 else BLUE, sp5[0], sp5[1],
                          (2.4 + 2 * form) * S * (sp5[2] / PX) * 2.6, a3 * 0.8)
        g.setOpacity(1.0)

    def _paint_arc(self, ar, age, env, res, asm):
        if ar["a"] >= len(self.NP) or ar["b"] >= len(self.NP):
            return
        A, B = self.NP[ar["a"]], self.NP[ar["b"]]
        if A[3] < 0.5 or B[3] < 0.5:
            return
        dx, dy = B[0] - A[0], B[1] - A[1]
        ln = math.sqrt(dx * dx + dy * dy)
        if ln < 1:
            return
        nx3, ny3 = -dy / ln, dx / ln
        rr7 = rng(ar["seed"] + int(age * 36))
        col = GOLDH if ar["hue"] > 0.55 else BLUEH
        amp = ln * 0.10 * (0.4 + 0.6 * res)
        pts = [QPointF(A[0], A[1])]
        for s5 in range(1, 12):
            f2 = s5 / 12
            bend = math.sin(f2 * math.pi) * amp * (rr7() * 2 - 1)
            pts.append(QPointF(A[0] + dx * f2 + nx3 * bend, A[1] + dy * f2 + ny3 * bend))
        pts.append(QPointF(B[0], B[1]))
        poly = QPolygonF(pts)
        g, S = self.g, self.S
        g.setOpacity(1.0)
        g.setBrush(Qt.BrushStyle.NoBrush)
        g.setPen(self._pen(col, 0.09 * env * res * asm, 6.6 * S * env))
        g.drawPolyline(poly)
        g.setPen(self._pen(col, 0.70 * env * asm, max(1.3, 2.30 * S * env)))
        g.drawPolyline(poly)
        g.setPen(self._pen(WHITE, 0.52 * env * asm, max(0.9, 0.95 * S * env)))
        g.drawPolyline(poly)

    def _draw_arcs(self, t, res, asm):
        if asm < 0.2:
            return
        for ar in ARCS:
            lt = t - ar["t0"]
            if lt < 0:
                lt += CYCLE
            if lt > ar["dur"]:
                continue
            self._paint_arc(ar, lt, math.sin(math.pi * (lt / ar["dur"])), res, asm)
        for la in self.live_arcs:
            age = self.nows - la["born"]
            if age < 0 or age > la["dur"]:
                continue
            self._paint_arc(la, age, math.sin(math.pi * (age / la["dur"])), res, asm)

    def _paint_wave(self, rad, alpha):
        if alpha < 0.01:
            return
        for pl in range(3):
            pts = []
            for s6 in range(57):
                ag = s6 / 56 * TAU
                ux, uy = math.cos(ag) * rad, math.sin(ag) * rad
                wp = (ux, uy, 0) if pl == 0 else ((ux, 0, uy) if pl == 1 else (0, ux, uy))
                pts.append(self.P(wp))
            self._stroke_banded(pts, mix(GOLDH, BLUEH, pl / 2), 1.3, alpha * 0.9, True)

    def _draw_core(self, t, u, res, asm, look: Look):
        g, S = self.g, self.S
        c = self.P(self.NW[0] if self.NW else (0, 0, 0))
        pulse = 0.5 + 0.5 * math.sin(TAU * (u * 54))
        HOT = self.hot if self.mood else GOLDH
        MID = self.mid if self.mood else GOLD
        if not look.online:
            HOT, MID = mix(HOT, STEEL, 0.78), mix(MID, STEEL, 0.78)
        if self.hearing > 0.01:
            HOT, MID = mix(HOT, LISTENH, self.hearing * 0.42), mix(MID, LISTEN, self.hearing * 0.52)
        if self.alert > 0.01:
            HOT, MID = mix(HOT, ALERT, self.alert * 0.85), mix(MID, ALERT, self.alert * 0.85)
        self.last_core = (HOT, MID)
        breathe_amp = 0.0 if look.breathe is False else (MOODS[self.mood]["breathe"] if self.mood else 0.20)
        dev_tick = 0.9 + 0.1 * math.sin(self.nows * 6) if self.mode == "dev" else 1.0
        flick_k = 0.85 + 0.15 * math.sin(self.nows * 20) if self.flick else 1.0
        breathe = flick_k * (1 + breathe_amp * pulse * (0.35 + 0.85 * res) * dev_tick)
        base = (14.5 * S * (self.focal / 900) * (0.55 + 0.75 * res) * breathe * (0.25 + 0.75 * asm)
                * (1 + 0.30 * self.wake_kick() + 0.55 * self.burst + 0.40 * self.ember))
        if base <= 0:
            return c
        if res > 0.45:
            w_amp = ss(0.45, 0.9, res) * asm
            for wv in range(3):
                wph = ((u * WAVES) - wv / 3) % 1
                wa = (1 - wph) * (1 - wph) * w_amp * 0.85
                if wa >= 0.01:
                    self._paint_wave(wph * 3.3, wa)
        for lw in self.live_waves:
            ag = (self.nows - lw["born"]) / 0.78
            if 0 <= ag <= 1:
                self._paint_wave(ag * 3.5, (1 - ag) * (1 - ag) * 0.95 * asm)
        rad = base * 7.5
        g0 = QRadialGradient(c[0], c[1], rad)
        g0.setColorAt(0, qc(WHITE, 0.92 * asm))
        g0.setColorAt(0.040, qc(HOT, 0.90 * asm))
        g0.setColorAt(0.115, qc(MID, 0.70 * asm))
        g0.setColorAt(0.230, qc(MID, 0.32 * asm))
        g0.setColorAt(0.400, qc(mix(MID, BLUE, 0.55), 0.15 * asm * (0.4 + 0.6 * res)))
        g0.setColorAt(0.680, qc(BLUE, 0.060 * asm * (0.4 + 0.6 * res)))
        g0.setColorAt(1, qc(BLUE, 0))
        g.setOpacity(1.0)
        g.setPen(Qt.PenStyle.NoPen)
        g.setBrush(g0)
        g.drawEllipse(QPointF(c[0], c[1]), rad, rad)
        self._dot(WHITE, c[0], c[1], base * 1.5, 0.95 * asm)
        st_w, st_h = base * 9.5 * (0.30 + 0.72 * res), max(1.1, base * 0.14)
        lg3 = QLinearGradient(c[0] - st_w, c[1], c[0] + st_w, c[1])
        lg3.setColorAt(0, qc(BLUEH, 0))
        lg3.setColorAt(0.42, qc(BLUEH, 0.26 * res * asm))
        lg3.setColorAt(0.5, qc(GOLDH, 0.30 * res * asm))
        lg3.setColorAt(0.58, qc(BLUEH, 0.26 * res * asm))
        lg3.setColorAt(1, qc(BLUEH, 0))
        g.setOpacity(1.0)
        g.fillRect(QRectF(c[0] - st_w, c[1] - st_h, st_w * 2, st_h * 2), lg3)
        for i in range(8):
            ag2 = i / 8 * TAU + u * TAU * 0.5
            ln = base * (2.6 + 3.4 * pulse) * (0.4 + 0.9 * res)
            ex, ey = c[0] + math.cos(ag2) * ln, c[1] + math.sin(ag2) * ln
            lg4 = QLinearGradient(c[0], c[1], ex, ey)
            lg4.setColorAt(0, qc(HOT, 0.52 * asm * res))
            lg4.setColorAt(1, qc(HOT, 0))
            pen = QPen(lg4, max(1.1, base * 0.24))
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            g.setPen(pen)
            g.drawLine(QLineF(c[0], c[1], ex, ey))
        return c

    # ------------------------------------------------------------ frame
    def paint(self, painter: QPainter, w: int, h: int, now: float, look: Look) -> None:
        """One frame of the glyph onto `painter` (already cleared)."""
        self.g = painter
        self.W, self.H = float(w), float(h)
        self.CX, self.CY = w / 2, h * 0.50
        self.S = clamp(min(w / 1280, h / 820), 0.5, 1.5)
        self.PX = min(w, h) * 0.44
        if self.epoch is None:
            self.epoch = now
        if self.last is None:
            self.last = now
        self.nows = now
        dt = clamp(now - self.last, 0.001, 0.1)
        self.last = now
        t = (now - self.epoch) % CYCLE
        u, res, asm = flow(t), resonance(t), assembly(t)

        self._pull_mood(look.mood)
        self.ember = max(0.0, self.ember - dt)
        self.ambient -= dt
        if (not self.mood and self.mode == "auto" and look.mood is not None and look.online
                and self.ember <= 0 and self.ambient <= 0):
            self.ember, self.ambient = 0.6, 20 + self._rand.random() * 20
        self._step(look, dt)
        res = max(res * 0.35, self.res, self.speaking * 0.92, self.hearing * 0.72)
        res = min(1.0, res + self.burst * 0.15 + self.ember * 0.1)
        if self.alert > 0.55:
            self.spark -= dt
            if self.spark <= 0:
                self._spawn_onset(now)
                self.spark = 0.22 + 0.25 * (1 - self.alert)
        self.last_res = res

        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        self._camera(t, res)
        self._update_nodes(asm)
        self._draw_field(res, look.backing)
        self._draw_volumetrics(t, res, asm)
        self._draw_rings(t, u, res, asm)
        self._draw_structure(t, u, res, asm)
        self._draw_particles(t, u, res, asm)
        self._draw_arcs(t, res, asm)
        self._draw_nodes(t, u, res, asm)
        self._draw_core(t, u, res, asm, look)
        painter.setOpacity(1.0)
        self.g = None

    def render(self, look: Look, size: int, now: float, dpr: float = 1.0) -> QImage:
        """A fresh transparent frame, `size` LOGICAL pixels square. At a
        device pixel ratio above 1 the image carries more pixels and the
        painter scales, as the JS canvas does with setTransform(DPR): the
        figure's line weights are logical, so they do not thin on a
        high-DPI screen."""
        px = max(1, int(round(size * dpr)))
        img = QImage(px, px, QImage.Format.Format_ARGB32_Premultiplied)
        img.setDevicePixelRatio(dpr)
        img.fill(Qt.GlobalColor.transparent)
        p = QPainter(img)
        try:
            self.paint(p, size, size, now, look)
        finally:
            p.end()
        return img


_SRC = QRectF(0, 0, 64, 64)
