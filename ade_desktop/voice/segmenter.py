"""Utterance segmentation: the avatar's live-mic constants (ptt.js), so the
orb hears the same way. Silence is measured and discarded, never sent.

    SPEECH_RMS  below this is room tone, not speech
    HANG_MS     silence that ends an utterance
    MIN_MS      shorter than this is a cough, not a word
    MAX_MS      a hard ceiling so one noise cannot grow forever

Pure and thread-agnostic: MicListener calls feed() from the audio thread.
"""

from __future__ import annotations

import math

SPEECH_RMS = 0.020
HANG_MS = 400
MIN_MS = 300
MAX_MS = 12000


class Segmenter:
    """ptt.js's live loop, rule for rule (review, 2026-09-18): MIN_MS is
    measured on the WHOLE segment, hangover included, so a short word
    followed by the 400 ms hang is sent, never dropped; past MAX_MS the
    segment is sent whole and listening starts over."""

    def __init__(self) -> None:
        self._buf: list[float] = []
        self._hearing = False
        self._quiet_ms = 0.0
        self.last_rms = 0.0

    def feed(self, block, rate: int) -> list[list[float]]:
        """One block of float samples at `rate`. Returns finished
        utterances."""
        block = list(block)
        if not block:
            return []
        out = []
        ms = len(block) * 1000.0 / rate
        rms = math.sqrt(sum(s * s for s in block) / len(block))
        self.last_rms = rms
        if rms >= SPEECH_RMS:
            self._hearing = True
            self._quiet_ms = 0.0
            self._buf.extend(block)
        elif self._hearing:
            self._quiet_ms += ms
            self._buf.extend(block)
            if self._quiet_ms >= HANG_MS:
                self._hearing, self._quiet_ms = False, 0.0
                out += self._send(rate)
        if self._hearing and len(self._buf) * 1000.0 / rate > MAX_MS:
            self._hearing, self._quiet_ms = False, 0.0
            out += self._send(rate)
        return out

    def _send(self, rate: int) -> list[list[float]]:
        samples, self._buf = self._buf, []
        return [samples] if len(samples) * 1000.0 / rate >= MIN_MS else []

    def reset(self) -> None:
        self._buf, self._hearing, self._quiet_ms = [], False, 0.0
