"""Ade's spoken replies: /v1/voice/speak -> a WAV -> Windows' own player.

Whole replies are spoken now (Ray, 2026-09-24: "make the char limit
unlimited"). The first-sentence-at-160-characters rule this module carried
until then was Maya1's: 9x realtime WITH re-rolls, which turned a 600-char
reply into eight segments times five re-rolls and a 180s client-side abort
that produced silence (2026-09-07). The sidecar's current model
(Chatterbox) does not re-roll; see SPEAK_TIMEOUT_S below for what a real
reply through it measures. The mouth is the WAV's own loudness envelope,
read at (now - start).

A new reply stops the old one. Each failure KIND is reported once (a TTS
that is down must not write a note under every reply), and reported again
only after a success in between.
"""

from __future__ import annotations

import logging
import os
import re
import tempfile
import time
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from ade_desktop.ade_status import ade_base
from ade_desktop.asyncclient import AsyncClient
from ade_desktop.net import post_bytes
from ade_desktop.voice.wav import rms_envelope

log = logging.getLogger("ade_desktop.voice.speaker")

# 0 means "no cap" -- removed 2026-09-24, see the module docstring. Named
# and kept rather than deleted so a future limit is one value, not restored
# code.
MAX_SPOKEN_CHARS = 0
# Measured 2026-09-24 against the sidecar's Chatterbox model on CPU, through
# this exact endpoint (POST /v1/voice/speak): 349 chars -> 28.5s audio in
# 85.2s wall (2.99x realtime); 629 chars -> 50.6s audio in 148.6s wall
# (2.94x). That is ~0.23s of wall time per character of input, close to
# linear, so 300s gives the longer measured point (629 chars) 2x headroom
# without being unbounded. This is a real, checked boundary, not a round
# number: a 1,500-char reply tried directly still did not finish inside it
# (it hit own_tts.py's inner sidecar-call timeout, at 240s on the old
# default and again at 330s on the raised one below) -- a long enough reply
# still times out by design, on this CPU-bound sidecar, rather than the cap
# growing to cover it.
SPEAK_TIMEOUT_S = 300.0
FRAME_MS = 20
_NARRATION = re.compile(
    r"^(we have (a |the )?(massive )?(search|tool|fetch)|the search results"
    r"|the list_files tool|the user asks)", re.I)


def clip_for_speech(text) -> str:
    """The line Ade speaks. Empty means do not speak.

    No first-sentence truncation and no length cap by default
    (MAX_SPOKEN_CHARS falsy skips it) -- both were Maya1's. The narration
    filter (_NARRATION) stays: it stops Ade reading its own scratchpad
    aloud, which has nothing to do with length.
    """
    raw = re.sub(r"\s+", " ", str(text or "")).strip()
    if not raw or _NARRATION.match(raw):
        return ""
    if MAX_SPOKEN_CHARS and len(raw) > MAX_SPOKEN_CHARS:
        raw = re.sub(r"\s+\S*$", "", raw[:MAX_SPOKEN_CHARS])
        raw = re.sub(r"[.,;:]+$", "", raw) + "."
    return raw


def _failure_kind(result) -> tuple[str, str]:
    err = result.get("error")
    if isinstance(err, dict):
        code = str(err.get("code") or "error")
        return code, f"{code}: {err.get('message') or ''}".rstrip(": ")
    text = str(err)
    if text.startswith("HTTP "):
        return "http", text
    return "unreachable", text


class WinsoundPlayer:
    """winsound.PlaySound, asynchronous. PlaySound(None, 0) is what stops an
    async sound -- SND_PURGE is documented as unsupported on modern
    Windows."""

    def play(self, path: str) -> None:
        import winsound
        winsound.PlaySound(path, winsound.SND_FILENAME | winsound.SND_ASYNC
                           | winsound.SND_NODEFAULT)

    def stop(self) -> None:
        import winsound
        winsound.PlaySound(None, 0)


class Speaker(QObject):
    failed = Signal(str)          # one note per failure kind
    started = Signal(float)       # seconds of audio now playing

    def __init__(self, base=None, *, post=post_bytes, player=None,
                 clock=time.monotonic, tmpdir=None, parent=None) -> None:
        super().__init__(parent)
        self.base = (base or ade_base()).rstrip("/")
        self._post = post
        self._player = player or WinsoundPlayer()
        self._clock = clock
        self._tmpdir = Path(tmpdir or tempfile.gettempdir())
        self._gen = 0
        self._env: list[float] = []
        self._start = 0.0
        self._file: Path | None = None
        self._reported: set[str] = set()
        # The fetch runs through the relay client: no worker ever holds the
        # speaker, so it can never be freed off the UI thread.
        self._calls = AsyncClient(self)
        self._calls.done.connect(self._on_done)
        self._gen_of: dict[str, int] = {}

    # -- speaking -------------------------------------------------------------

    def speak(self, text) -> bool:
        """Fetch and play the clipped reply. False if nothing was speakable."""
        spoken = clip_for_speech(text)
        self.hush()
        if not spoken:
            return False
        self._gen += 1
        post, url = self._post, self.base + "/v1/voice/speak"
        rid = self._calls.call(lambda: post(url, {"text": spoken}, SPEAK_TIMEOUT_S))
        self._gen_of[rid] = self._gen
        return True

    def _on_done(self, rid: str, result) -> None:
        gen = self._gen_of.pop(rid, None)
        if gen is not None:
            self._on_fetched(result, gen)

    def _on_fetched(self, result, gen: int) -> None:
        if gen != self._gen:
            return                      # superseded, or hushed meanwhile
        result = result if isinstance(result, dict) else {"error": "non-dict reply"}
        if "wav" not in result:
            self._report(*_failure_kind(result))
            return
        wav = result["wav"]
        try:
            env = rms_envelope(wav, FRAME_MS)
        except Exception as exc:  # noqa: BLE001 -- not a WAV
            self._report("bad_audio", f"not a WAV: {exc}")
            return
        path = self._tmpdir / f"ade-desktop-speak-{os.getpid()}-{gen}.wav"
        try:
            path.write_bytes(wav)
            self._player.play(str(path))
        except Exception as exc:  # noqa: BLE001 -- no audio device
            self._report("playback", f"{type(exc).__name__}: {exc}")
            self._remove(path)
            return
        self._remove(self._file)
        self._file, self._env, self._start = path, env, self._clock()
        self._reported.clear()
        self.started.emit(len(env) * FRAME_MS / 1000.0)

    def _report(self, kind: str, message: str) -> None:
        log.warning("speak failed (%s): %s", kind, message)
        if kind in self._reported:
            return
        self._reported.add(kind)
        self.failed.emit(f"Could not speak the reply — {message}. Replies stay "
                         "in text; this note is not repeated for the same fault.")

    # -- the mouth --------------------------------------------------------------

    def level(self, now: float | None = None) -> float:
        if not self._env:
            return 0.0
        at = (self._clock() if now is None else now) - self._start
        i = int(at * 1000 / FRAME_MS)
        if i < 0:
            return 0.0
        if i >= len(self._env):
            self._env = []
            return 0.0
        return self._env[i]

    def speaking(self) -> bool:
        return self.level() > 0.0 or bool(self._env)

    # -- stopping ---------------------------------------------------------------

    def hush(self) -> None:
        """Stop what is playing and forget what is in flight."""
        self._gen += 1
        if self._env:
            try:
                self._player.stop()
            except Exception:  # noqa: BLE001
                log.exception("stopping playback failed")
        self._env = []

    def close(self) -> None:
        self.hush()
        self._calls.stop()
        self._remove(self._file)
        self._file = None

    @staticmethod
    def _remove(path) -> None:
        if path is None:
            return
        try:
            Path(path).unlink(missing_ok=True)
        except OSError:
            pass
