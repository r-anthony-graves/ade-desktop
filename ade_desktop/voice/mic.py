"""The orb's microphone: one PortAudio input stream (sounddevice), cut into
utterances by the avatar's Segmenter.

Mute STOPS the stream -- the device is released and the OS microphone
indicator goes out. A mute that kept capturing would be a lie told by a
checkbox, so running() reports the stream, not a flag.

RawInputStream, not InputStream: the numpy-free one. Blocks arrive on
PortAudio's thread, are segmented THERE, and cross to the UI thread only as
queued signals. The callback holds a weak reference: a stream must never be
what keeps a Qt object alive, and no Qt object may be freed on the audio
thread.
"""

from __future__ import annotations

import array
import logging
import math
import threading
import time
import weakref

from PySide6.QtCore import QObject, Signal

from ade_desktop.voice.segmenter import Segmenter

log = logging.getLogger("ade_desktop.voice.mic")

LEVEL_EVERY_S = 0.05     # the level signal, at most 20 times a second
BLOCK_S = 0.02           # 20 ms blocks, the segmenter's granularity


def open_default_stream(callback):
    """(stream, rate) on the default input device, already started."""
    import sounddevice as sd

    rate = int(sd.query_devices(kind="input")["default_samplerate"])
    stream = sd.RawInputStream(samplerate=rate, channels=1, dtype="float32",
                               blocksize=max(1, int(rate * BLOCK_S)),
                               callback=callback)
    stream.start()
    return stream, rate


def _floats(indata) -> list[float]:
    raw = bytes(indata)
    usable = len(raw) - len(raw) % 4
    return array.array("f", raw[:usable]).tolist()


class MicListener(QObject):
    utterance = Signal(object)   # {"samples": [float], "rate": int}
    level = Signal(float)        # 0..1 (RMS x 5, capped)
    failed = Signal(str)         # the device could not be opened

    def __init__(self, open_stream=open_default_stream, clock=time.monotonic,
                 parent=None) -> None:
        super().__init__(parent)
        self._open = open_stream
        self._clock = clock
        self._stream = None
        self._rate = 0
        self._lock = threading.Lock()
        self._seg = Segmenter()
        self._last_level = 0.0

    def running(self) -> bool:
        stream = self._stream
        return stream is not None and bool(getattr(stream, "active", True))

    def start(self) -> bool:
        if self._stream is not None:
            return True
        wself = weakref.ref(self)

        def callback(indata, frames, time_info, status):
            me = wself()
            if me is not None:
                me._on_block(_floats(indata))
                del me

        try:
            stream, rate = self._open(callback)
        except Exception as exc:  # noqa: BLE001 -- no microphone is a state
            log.warning("microphone unavailable: %s", exc)
            self.failed.emit(f"{type(exc).__name__}: {exc}")
            return False
        with self._lock:
            self._seg.reset()
            self._stream, self._rate = stream, int(rate)
        log.info("microphone open at %s Hz", rate)
        return True

    def stop(self) -> None:
        """Close the stream: the device is released, not merely ignored."""
        with self._lock:
            stream, self._stream = self._stream, None
            self._seg.reset()
        if stream is None:
            return
        for step in ("stop", "close"):
            try:
                getattr(stream, step)()
            except Exception:  # noqa: BLE001 -- releasing must finish
                log.exception("microphone %s failed", step)
        self.level.emit(0.0)
        log.info("microphone closed")

    def _on_block(self, samples: list[float]) -> None:
        """On PortAudio's thread."""
        with self._lock:
            if self._stream is None or not samples:
                return
            done = self._seg.feed(samples, self._rate)
            rate = self._rate
        now = self._clock()
        if now - self._last_level >= LEVEL_EVERY_S:
            self._last_level = now
            rms = math.sqrt(sum(s * s for s in samples) / len(samples))
            self.level.emit(min(1.0, rms * 5))
        for utt in done:
            self.utterance.emit({"samples": utt, "rate": rate})
