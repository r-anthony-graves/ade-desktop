"""What a heard utterance becomes. Speech may ASK or STAGE -- never more.

    not woken      whisper: typed into the input, unsent. Any other engine:
                   ignored (the Windows fallback's closed grammar maps room
                   tone onto stock phrases -- the avatar's finding).
    "Ade"          the wake event, and the window opens on the input. The
                   avatar's WAKE needs text after the word, so a trimmed
                   "Hey Ade." never matched it and was typed in as dictation;
                   WAKE_ONLY catches the bare word -- from an open-vocabulary
                   engine only, for the same room-tone reason as below.
    "Ade, <line>"  the wake event, then: a line Chat would route as a plain
                   ask is sent as one (panel.voice_ask), unless the panel is
                   busy. Anything else -- a shell line, a task, a command, a
                   skill, an upload, a clear, a bare yes/allow/deny -- is
                   STAGED in the input for Enter.

Approvals are click-only (VoiceInterface.can_approve() is False in Ade OS
too): nothing here can reach decide, task, shell, run or upload. The panel
methods this calls are the whole of what speech can touch.
"""

from __future__ import annotations

import base64
import logging
import re

from PySide6.QtCore import QObject, Signal

from ade_desktop.ade_status import ade_base
from ade_desktop.asyncclient import AsyncClient
from ade_desktop.conversation.commands import COMMAND_NAMES
from ade_desktop.conversation.router import route
from ade_desktop.net import post_json
from ade_desktop.voice.wake import strip_wake
from ade_desktop.voice.wav import downsample, encode_wav

log = logging.getLogger("ade_desktop.voice.controller")

LISTEN_TIMEOUT_S = 30.0
WAKE_ONLY = re.compile(r"^\s*(?:hey\s+|ok\s+)?ad[ae]y?\s*[,.!?:-]?\s*$", re.I)
# A bare decision word is someone answering a card out loud. Sent as an ask
# it would read as a reply to Ade; staged, the note says where the buttons are.
_DECISION = re.compile(
    r"^(yes|yeah|yep|no|nope|ok(ay)?|sure|allow|deny|approve|reject|confirm|"
    r"cancel|go ahead|do it)( it| that| this)?( please)?[.!?]*$", re.I)
DECISION_NOTE = ("Heard: {cmd} — approvals are click-only. Use Allow or Deny on "
                 "the card; the line is in the box if you meant to send it.")
STAGED_NOTE = "Heard: {cmd} — press Enter to run it."
# "Ade, stop" silences Ade's own voice; it is never staged or sent.
_HUSH = re.compile(r"^(stop|quiet|be quiet|shush|hush|stop (talking|speaking)|"
                   r"that's enough)[.!]*$", re.I)
BUSY_NOTE = "Heard: {cmd} — Ade is still working; press Enter to send it after."


class VoiceController(QObject):
    """panel needs: busy, voice_ask(text) -> bool, stage(text, note, quiet)
    -> bool, focus_input(), note(text). SIGNALS, not callbacks, for the
    orb: a callback into the OrbController would make it and this a
    reference cycle, and a connection does not pin its receiver."""

    wake_heard = Signal()        # the orb's wake: mood event + glyph arcs
    open_requested = Signal()    # show Ade with the panel open
    hush_requested = Signal()    # "Ade, stop": silence the reply being spoken

    def __init__(self, panel, *, base=None, listen=post_json, parent=None) -> None:
        super().__init__(parent)
        self.panel = panel
        self.base = (base or ade_base()).rstrip("/")
        self._listen = listen
        self._inflight = False
        self._queued = None
        self._reported: set[str] = set()
        self._gen = 0
        self._gen_of: dict[str, int] = {}
        # Recognition runs through the relay client: no worker ever holds
        # this controller (review, 2026-09-18).
        self._calls = AsyncClient(self)
        self._calls.done.connect(self._on_done)

    def discard(self) -> None:
        """Mute: speech captured before it is never acted on -- neither the
        utterance waiting nor the recognition in flight (review finding: it
        used to pop the window up after the mic was off)."""
        self._gen += 1
        self._queued = None

    # -- utterance -> text ------------------------------------------------------

    def on_utterance(self, utt) -> None:
        """From MicListener: {"samples", "rate"}. One recognition at a time;
        a newer utterance waiting replaces an older one."""
        if self._inflight:
            self._queued = utt
            return
        self._inflight = True
        listen, url = self._listen, self.base + "/v1/voice/listen"

        def work():
            wav = encode_wav(downsample(utt["samples"], int(utt["rate"]), 16000), 16000)
            return listen(url, {"audio": base64.b64encode(wav).decode("ascii")},
                          LISTEN_TIMEOUT_S)

        self._gen_of[self._calls.call(work)] = self._gen

    def _on_done(self, rid: str, result) -> None:
        gen = self._gen_of.pop(rid, None)
        if gen is None:
            return
        self._inflight = False
        queued, self._queued = self._queued, None
        try:
            if gen != self._gen:
                return                          # captured before a mute
            if not isinstance(result, dict) or "error" in result:
                self._report(result)
            else:
                self._reported.clear()
                self.on_text(result.get("text"), result.get("engine"))
        finally:
            if queued is not None:
                self.on_utterance(queued)

    def stop(self) -> None:
        self.discard()
        self._calls.stop()

    def _report(self, result) -> None:
        err = result.get("error") if isinstance(result, dict) else result
        kind = str(err.get("code")) if isinstance(err, dict) else str(err).split(":", 1)[0]
        log.warning("listen failed: %s", err)
        if kind in self._reported:
            return
        self._reported.add(kind)
        text = (f"{err.get('code')}: {err.get('message') or ''}".rstrip(": ")
                if isinstance(err, dict) else str(err))
        self.panel.note(f"Could not hear that — speech recognition failed ({text}). "
                        "Not repeated for the same fault.")

    # -- text -> action ------------------------------------------------------------

    def on_text(self, text, engine) -> str:
        """What was done with a transcript: ignored, typed, opened, asked,
        staged."""
        text = str(text or "").strip()
        if not text:
            return "ignored"
        cmd = strip_wake(text)
        if cmd is None and WAKE_ONLY.match(text) and engine != "windows":
            cmd = ""
        if cmd is None:
            # Overheard dictation lands in the box only if Chat would send it
            # as a plain ask, and it never takes focus: an overheard "git push
            # --force" must not be one stray Enter from running (review).
            if engine == "whisper" and route(text, "chat", COMMAND_NAMES).kind == "ask":
                return "typed" if self.panel.stage(text, quiet=True) else "ignored"
            return "ignored"
        self.wake_heard.emit()
        self.open_requested.emit()
        if not cmd:
            self.panel.focus_input()
            return "opened"
        if _HUSH.match(cmd):
            self.hush_requested.emit()
            return "hushed"
        if _DECISION.match(cmd):
            self.panel.stage(cmd, DECISION_NOTE.format(cmd=cmd))
            return "staged"
        if self.panel.busy:
            self.panel.stage(cmd, BUSY_NOTE.format(cmd=cmd))
            return "staged"
        if self.panel.voice_ask(cmd):
            return "asked"
        self.panel.stage(cmd, STAGED_NOTE.format(cmd=cmd))
        return "staged"
