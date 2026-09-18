"""Ade's spoken replies: /v1/voice/speak -> a WAV -> Windows' own player.

The clip rule is the avatar's (adeos/avatar/main.js clipForSpeech): the
first sentence, cut to 160 characters, because a long reply became a minute
of silence that looked like a broken voice. The mouth is the WAV's own
loudness envelope, read at (now - start).

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

MAX_SPOKEN_CHARS = 160
SPEAK_TIMEOUT_S = 180.0      # the avatar's: Maya1 renders at tens of seconds
FRAME_MS = 20
_NARRATION = re.compile(
    r"^(we have (a |the )?(massive )?(search|tool|fetch)|the search results"
    r"|the list_files tool|the user asks)", re.I)


def clip_for_speech(text) -> str:
    raw = re.sub(r"\s+", " ", str(text or "")).strip()
    if not raw or _NARRATION.match(raw):
        return ""
    m = re.match(r"^(.+?[.!?])(?:\s|$)", raw)
    spoken = m.group(1) if m else raw
    if len(spoken) > MAX_SPOKEN_CHARS:
        spoken = re.sub(r"\s+\S*$", "", spoken[:MAX_SPOKEN_CHARS])
        spoken = re.sub(r"[.,;:]+$", "", spoken) + "."
    return spoken


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
