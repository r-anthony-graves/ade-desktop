"""OrbController: what the orb shows, and what its menu does.

It owns one Mood and feeds it:

    /v1/health          online (reachable: UP, DEGRADED or BLOCKED)
    /v1/activity        busy -- or the panel has a turn in flight
    the approval watcher  pending = live approval ids
    an approval decided   event("approved")
    a failed turn         event("failed")
    the wake word         event("wake"), and the glyph's wake arcs
    a spoken reply        tint(sentiment(text), its duration)

and draws the glyph at 24 fps while anything is happening, 15 fps at rest,
and not at all while the orb is hidden. Everything it touches is a QObject
it was handed; the frame timer is its own child, so nothing here outlives
the window it draws in.

It holds the main window WEAKLY: the window keeps the controller (to stop
it at quit), and a strong reference back would make the pair cyclic
garbage -- the class of object whose collection mid-emit crashed PySide in
piece 1.
"""

from __future__ import annotations

import logging
import time
import weakref
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtGui import QAction, QActionGroup, QGuiApplication
from PySide6.QtWidgets import QMenu

from ade_desktop.ade_status import is_active, is_online
from ade_desktop.geometry import (Rect, clamp_to_screens, fit_inside, load_state,
                                  save_state)
from ade_desktop.orb.glyph import Look
from ade_desktop.orb.mood import sentiment
from ade_desktop.orb.window import SIZES

log = logging.getLogger("ade_desktop.orb")

LIVELY_MS = 42      # 24 fps
RESTING_MS = 66     # 15 fps
# The orb shares the UI thread with the Trader and the panel. A frame is
# ~25 ms at 100% scaling and ~41 ms at 200% (measured, review 2026-09-18),
# so the interval stretches until drawing takes at most this share of it.
UI_BUDGET = 0.35
MAX_RENDER_DPR = 1.5    # past this Qt scales the image; the figure is soft, not slow
MARGIN = 24
NO_TRAY_TIP = "There is no system tray to bring the orb back from, so it cannot be hidden."
AVATAR_NOTE = ("The Electron avatar is running and listening. The orb's "
               "microphone starts muted so one wake word isn't answered twice; "
               "unmute it from the orb's menu.")
MIC_FAILED = "The microphone could not be opened ({why}). The orb stays muted."


def _screens() -> list[Rect]:
    primary = QGuiApplication.primaryScreen()
    ordered = [primary] + [s for s in QGuiApplication.screens() if s is not primary]
    out = []
    for s in ordered:
        if s is not None:
            g = s.availableGeometry()
            out.append(Rect(g.x(), g.y(), g.width(), g.height()))
    return out


class OrbController(QObject):
    mic_state = Signal(bool)        # the microphone IS (True) or is not listening
    def __init__(self, *, window, orb, renderer, mood, speaker, mic, voice,
                 state_path: Path, avatar_running: bool = False,
                 clock=time.monotonic, parent=None) -> None:
        super().__init__(parent)
        self._window = weakref.ref(window)
        self.orb, self.renderer = orb, renderer
        self.mood, self.speaker, self.mic, self.voice = mood, speaker, mic, voice
        self.panel = window.panel
        self._state_path = Path(state_path)
        self._clock = clock
        self.online = False
        self.remote_busy = False
        self.hear = 0.0
        self._spoken = ""
        self._started = False
        self._render_ms = 0.0       # moving average of one frame's drawing
        self._has_tray = getattr(window, "tray", None) is not None

        saved = load_state(self._state_path).get("orb")
        saved = saved if isinstance(saved, dict) else {}
        self.size_key = saved.get("size") if saved.get("size") in SIZES else "M"
        self.speak_on = saved.get("speak") is True           # default OFF
        self.backing_on = saved.get("backing") is not False  # default ON
        self.visible_on = saved.get("visible") is not False  # default ON
        self.mic_wanted = saved.get("mic") is not False      # default ON
        self.avatar_running = bool(avatar_running)
        self._saved_xy = (saved.get("x"), saved.get("y"))

        self._build_actions(window)
        self._timer = QTimer(self)
        self._timer.setInterval(RESTING_MS)
        self._timer.timeout.connect(self.tick)

        status = window.status
        status.health.connect(self._on_health)
        status.activity.connect(self._on_activity)
        self.panel.busy_changed.connect(self._feed)
        self.panel.watcher.appeared.connect(self._feed)
        self.panel.watcher.vanished.connect(self._feed)
        self.panel.approval_decided.connect(self._on_decided)
        self.panel.turn_failed.connect(self._on_failed)
        self.panel.reply_landed.connect(self._on_reply)
        self.speaker.started.connect(self._on_speech_started)
        self.speaker.failed.connect(self.panel.note)
        self.mic.level.connect(self._on_level)
        self.mic.utterance.connect(self._on_utterance)
        self.mic.failed.connect(self._on_mic_failed)
        self.voice.wake_heard.connect(self.on_wake)
        self.voice.open_requested.connect(self.open_ade)
        self.voice.hush_requested.connect(self.speaker.hush)
        orb.open_requested.connect(self.open_ade)
        orb.mute_requested.connect(self.toggle_mic)
        self.mic_state.connect(orb.set_mic_badge)
        orb.menu_requested.connect(self._popup)
        orb.moved.connect(self._on_moved)

    # -- menus ----------------------------------------------------------------

    @property
    def window(self):
        return self._window()

    def _build_actions(self, window) -> None:
        self.open_act = QAction("Open Ade", self)
        self.open_act.triggered.connect(self.open_ade)
        self.size_group = QActionGroup(self)
        self.size_acts = {}
        for key, label in (("S", "Small"), ("M", "Medium"), ("L", "Large")):
            act = QAction(f"{label} ({SIZES[key]})", self, checkable=True)
            act.setChecked(key == self.size_key)
            act.setData(key)
            self.size_group.addAction(act)
            self.size_acts[key] = act
        self.size_group.triggered.connect(self._on_size)
        self.speak_act = QAction("Speak Ade's replies", self, checkable=True)
        self.speak_act.setChecked(self.speak_on)
        self.speak_act.toggled.connect(self.set_speak)
        self.mic_act = QAction("Microphone", self, checkable=True)
        self.mic_act.toggled.connect(self.set_mic)
        self.backing_act = QAction("Backing glow", self, checkable=True)
        self.backing_act.setChecked(self.backing_on)
        self.backing_act.toggled.connect(self.set_backing)
        self.orb_act = QAction("Hide orb", self)
        self.orb_act.triggered.connect(self.toggle_orb)
        if not self._has_tray:
            self.orb_act.setEnabled(False)
            self.orb_act.setToolTip(NO_TRAY_TIP)
        self.quit_act = QAction("Quit Ade", self)
        self.quit_act.triggered.connect(window.quit_app)
        self.menu = QMenu()
        self.menu.addAction(self.open_act)
        sizes = self.menu.addMenu("Size")
        for act in self.size_acts.values():
            sizes.addAction(act)
        self.menu.addSeparator()
        for act in (self.speak_act, self.mic_act, self.backing_act):
            self.menu.addAction(act)
        self.menu.addSeparator()
        self.menu.addAction(self.orb_act)
        self.menu.addAction(self.quit_act)
        tray = getattr(window, "tray", None)
        if tray is not None and tray.contextMenu() is not None:
            # after "Show Ade", before the separator and Quit
            tmenu = tray.contextMenu()
            before = tmenu.actions()[1] if len(tmenu.actions()) > 1 else None
            for act in (self.orb_act, self.speak_act, self.mic_act):
                tmenu.insertAction(before, act)

    def _popup(self, where) -> None:
        self.menu.popup(where)

    # -- lifecycle ------------------------------------------------------------

    def start(self, *, open_mic: bool = True) -> None:
        """Place and show the orb, open the microphone unless it should
        start muted, and start drawing. open_mic=False (the smoke run)
        never touches the audio device."""
        self._started = True
        if not self._has_tray:
            self.visible_on = True      # hidden with no tray = gone for good
        self.orb.set_orb_size(SIZES[self.size_key])
        self._place()
        if self.visible_on:
            self.orb.show()
        self._sync_orb_act()
        muted_for_avatar = self.avatar_running and self.mic_wanted
        if muted_for_avatar:
            self.panel.note(AVATAR_NOTE)
        self.mic_act.blockSignals(True)
        self.mic_act.setChecked(self.mic_wanted and not muted_for_avatar)
        self.mic_act.blockSignals(False)
        if self.mic_act.isChecked() and (not open_mic or not self.mic.start()):
            self._uncheck_mic()
        self._feed()
        self._timer.start()
        self._announce_mic()

    def stop(self) -> None:
        self._timer.stop()
        self.save()
        self.mic.stop()
        self.voice.stop()
        self.speaker.close()
        self.orb.hide()

    def _place(self) -> None:
        size = SIZES[self.size_key]
        screens = _screens()
        x, y = self._saved_xy
        if isinstance(x, int) and isinstance(y, int):
            rect = Rect(x, y, size, size)
        elif screens:
            s = screens[0]
            rect = Rect(s.x + s.w - size - MARGIN, s.y + s.h - size - MARGIN, size, size)
        else:
            rect = Rect(MARGIN, MARGIN, size, size)
        rect = clamp_to_screens(rect, screens)
        self.orb.move(rect.x, rect.y)

    def save(self) -> None:
        state = load_state(self._state_path)
        state["orb"] = {"x": self.orb.x(), "y": self.orb.y(), "size": self.size_key,
                        "visible": self.visible_on, "speak": self.speak_on,
                        "mic": self.mic_wanted, "backing": self.backing_on}
        save_state(self._state_path, state)

    # -- what Ade is doing ----------------------------------------------------

    def pending(self) -> int:
        return int(self.panel.watcher.pending_count())

    def busy(self) -> bool:
        return bool(self.remote_busy or self.panel.busy)

    def _on_health(self, payload) -> None:
        self.online = is_online(payload)
        self._feed()

    def _on_activity(self, payload) -> None:
        active = is_active(payload)
        if active is not None:          # an error is not "idle"
            self.remote_busy = active
            self._feed()

    def _feed(self, *_) -> None:
        self.mood.feed({"online": self.online, "busy": self.busy(),
                        "pending": self.pending()})

    def _on_decided(self, allow: bool) -> None:
        if allow:
            self.mood.event("approved")

    def _on_failed(self) -> None:
        self.mood.event("failed")

    def on_wake(self) -> None:
        self.mood.event("wake")
        self.renderer.wake(self._clock())

    def _on_level(self, level) -> None:
        self.hear = float(level)

    def _on_utterance(self, utt) -> None:
        # A block captured just before a mute can still be queued: a closed
        # microphone hears nothing, including its last breath.
        if self.mic.running():
            self.voice.on_utterance(utt)

    def _on_mic_failed(self, why: str) -> None:
        self.panel.note(MIC_FAILED.format(why=why))

    def _on_reply(self, text: str) -> None:
        if self.speak_on and self.speaker.speak(text):
            self._spoken = text

    def _on_speech_started(self, seconds: float) -> None:
        self.mood.tint(sentiment(self._spoken), seconds * 1000.0)

    # -- drawing --------------------------------------------------------------

    def look(self, now: float) -> Look:
        return Look(online=self.online, busy=self.busy(), pending=self.pending(),
                    mood=self.mood.frame(), speak=self.speaker.level(now),
                    hear=self.hear if self.mic.running() else 0.0,
                    mic_open=self.mic.running(), breathe=True,
                    backing=self.backing_on)

    def tick(self) -> None:
        if not self.orb.isVisible():
            return
        now = self._clock()
        look = self.look(now)
        dpr = min(self.orb.devicePixelRatioF() or 1.0, MAX_RENDER_DPR)
        t0 = time.perf_counter()
        self.orb.show_frame(self.renderer.render(look, SIZES[self.size_key], now, dpr))
        ms = (time.perf_counter() - t0) * 1000.0
        self._render_ms = ms if not self._render_ms else self._render_ms * 0.8 + ms * 0.2
        lively = (look.busy or look.pending > 0 or look.speak > 0.01 or look.hear > 0.05
                  or (look.mood or {}).get("burst") or self.renderer.wake_kick() > 0)
        want = self.interval_for(lively, self._render_ms)
        if self._timer.interval() != want:
            self._timer.setInterval(want)

    @staticmethod
    def interval_for(lively: bool, render_ms: float) -> int:
        """24 fps lively, 15 at rest -- stretched so drawing never takes
        more than UI_BUDGET of the UI thread."""
        base = LIVELY_MS if lively else RESTING_MS
        return max(base, int(render_ms / UI_BUDGET + 0.5))

    # -- actions --------------------------------------------------------------

    def open_ade(self) -> None:
        window = self.window
        if window is None:
            return
        window.show_and_raise()
        window.set_panel_open(True)
        self.panel.focus_input()

    def _on_size(self, act) -> None:
        key = act.data()
        if key in SIZES and key != self.size_key:
            centre = self.orb.geometry().center()
            self.size_key = key
            px = SIZES[key]
            self.orb.set_orb_size(px)
            rect = fit_inside(Rect(centre.x() - px // 2, centre.y() - px // 2, px, px),
                              _screens())
            self.orb.move(rect.x, rect.y)
            self.save()

    def set_speak(self, on: bool) -> None:
        self.speak_on = bool(on)
        if not on:
            self.speaker.hush()
        self.save()

    def set_mic(self, on: bool) -> None:
        self.mic_wanted = bool(on)
        if on:
            if not self.mic.start():
                self._uncheck_mic()
                return
        else:
            self.mic.stop()
            self.voice.discard()        # nothing captured before the mute is acted on
            self.speaker.hush()         # and Ade stops talking too
            self.hear = 0.0
        self.save()
        self._announce_mic()

    def toggle_mic(self) -> None:
        """The header's Mute button: flip what the microphone IS doing (not
        what the menu last said), through the same path as the orb's menu."""
        want = not self.mic.running()
        self.mic_act.blockSignals(True)
        self.mic_act.setChecked(want)
        self.mic_act.blockSignals(False)
        self.set_mic(want)

    def _uncheck_mic(self) -> None:
        self.mic_act.blockSignals(True)
        self.mic_act.setChecked(False)
        self.mic_act.blockSignals(False)
        self._announce_mic()

    def _announce_mic(self) -> None:
        self.mic_state.emit(self.mic.running())

    def set_backing(self, on: bool) -> None:
        self.backing_on = bool(on)
        self.save()

    def toggle_orb(self) -> None:
        if not self._has_tray and self.orb.isVisible():
            return                      # nothing could bring it back
        self.visible_on = not self.orb.isVisible()
        self.orb.setVisible(self.visible_on)
        self._sync_orb_act()
        self.save()

    def _sync_orb_act(self) -> None:
        self.orb_act.setText("Hide orb" if self.visible_on else "Show orb")

    def _on_moved(self, x: int, y: int) -> None:
        self.save()
