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
    def __init__(self) -> None:
        self._buf: list[float] = []
        self._hearing = False
        self._quiet_ms = 0.0
        self._voiced_ms = 0.0
        self.last_rms = 0.0

    def feed(self, block, rate: int) -> list[list[float]]:
        """One block of float samples at `rate`. Returns finished utterances
        (each the samples from the first voiced block through the
        hangover)."""
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
            self._voiced_ms += ms
            self._buf.extend(block)
        elif self._hearing:
            self._buf.extend(block)
            self._quiet_ms += ms
            if self._quiet_ms >= HANG_MS:
                out += self._finish(rate)
        if self._hearing and len(self._buf) * 1000.0 / rate > MAX_MS:
            cut = int(rate * MAX_MS / 1000)
            head, self._buf = self._buf[:cut], []
            self._hearing = False
            self._quiet_ms = self._voiced_ms = 0.0
            out.append(head)
        return out

    def _finish(self, rate: int) -> list[list[float]]:
        samples, voiced = self._buf, self._voiced_ms
        self._buf, self._hearing = [], False
        self._quiet_ms = self._voiced_ms = 0.0
        return [samples] if voiced >= MIN_MS else []

    def reset(self) -> None:
        self._buf, self._hearing = [], False
        self._quiet_ms = self._voiced_ms = 0.0
