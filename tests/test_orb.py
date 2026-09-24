"""The orb window and its controller, offscreen, against the real main
window and panel with the network faked: the flags, the hit test, click vs
drag, the moods Ade's state produces, the menu's settings and where they
are remembered, the microphone really closing, and a dropped orb freed."""

import gc
import math
import weakref

import pytest
from PySide6.QtCore import QObject, QPoint, QPointF, Qt, Signal
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QLabel

from ade_desktop.app import DesktopWindow
from ade_desktop.conversation.panel import ConversationPanel
from ade_desktop.conversation.sessions import GENERAL
from ade_desktop.conversation.stack import ChatStack
from ade_desktop.conversation.threads import ThreadStore
from ade_desktop.geometry import load_state, save_state
from ade_desktop.orb.controller import AVATAR_NOTE, OrbController
from ade_desktop.orb.glyph import GlyphRenderer, Look
from ade_desktop.orb.mood import Mood
from ade_desktop.orb.window import SIZES, OrbWindow
from ade_desktop.sections import Section
from ade_desktop.voice.controller import VoiceController
from ade_desktop.voice.mic import MicListener
from ade_desktop.voice.speaker import Speaker
from ade_desktop.voice.wav import encode_wav

UP = {"status": "up", "may_execute_tools": True, "blocking_reason": "", "subsystems": {}}


class FakeStatus(QObject):
    health = Signal(dict)
    settings = Signal(dict)
    activity = Signal(dict)

    def start(self): pass
    def stop(self): pass


class FakeClient(QObject):
    done = Signal(str, object)
    line = Signal(str, str)

    def __init__(self):
        super().__init__()
        self.calls = []

    def _rid(self, *call):
        self.calls.append(call)
        return f"r{len(self.calls)}"

    def ask(self, q, skills, history, turn_id=None): return self._rid("ask", q)
    def chat(self, text): return self._rid("chat", text)
    def task(self, text, t, skills, turn_id=None): return self._rid("task", text, t)
    def cancel(self, turn_id): return self._rid("cancel", turn_id)
    def decide(self, aid, allow): return self._rid("decide", aid, allow)
    def stop(self): pass


class FakeWatcher(QObject):
    appeared = Signal(object)
    vanished = Signal(str)

    def __init__(self):
        super().__init__()
        live = self.live = set()
        self.appeared.connect(lambda a: live.add(a["id"]))
        self.vanished.connect(live.discard)

    def pending_count(self): return len(self.live)
    def start(self): pass
    def stop(self): pass


class FakeStream:
    active = True

    def stop(self): self.active = False
    def close(self): self.closed = True


class FakeDevice:
    def __init__(self):
        self.opens = 0
        self.stream = None

    def open(self, callback):
        self.opens += 1
        self.stream = FakeStream()
        return self.stream, 16000


class FakePlayer:
    def __init__(self): self.played = []
    def play(self, path): self.played.append(path)
    def stop(self): pass


def _wav():
    return encode_wav([0.5 * math.sin(i / 4) for i in range(8000)], 16000)


class Rig:
    """No callback here may capture the Rig: a Rig -> window -> lambda ->
    Rig cycle is cyclic garbage holding QWidgets, which the collector can
    free on whatever thread allocates next -- a worker's -- and Qt aborts
    (measured 2026-09-18, the full suite). Capture plain lists instead."""

    def __init__(self, tmp_path, *, avatar=False, saved=None, tray=False, listen=None):
        self.state = tmp_path / "window.json"
        if saved is not None:
            save_state(self.state, saved)
        self.client, self.watcher = FakeClient(), FakeWatcher()
        self.panel = ConversationPanel(self.client, self.watcher,
                                       ThreadStore(tmp_path / "threads.json"))
        # A page holds a STACK of chats since 2026-09-24 (requirement 7),
        # so the window is given one. `self.panel` stays the inner session,
        # which is what these tests drive; the orb and voice reach it
        # through the stack, exactly as they do in the real app.
        self.stack = ChatStack(GENERAL, lambda _n, p=self.panel: p)
        self.status = FakeStatus()
        quits = self.quits = []
        self.win = DesktopWindow([Section("Trader", QLabel("t"))], self.status,
                                 state_path=self.state, tray_available=tray,
                                 quit_fn=lambda: quits.append(1), panel=self.stack)
        self.device = FakeDevice()
        spoken = self.spoken = []

        def post(url, body, timeout):
            spoken.append(body["text"])
            return {"wav": _wav()}

        self.player = FakePlayer()
        self.speaker = Speaker("http://ade", post=post, player=self.player,
                               tmpdir=tmp_path)
        self.orb = OrbWindow()
        self.renderer = GlyphRenderer(epoch=0.0)
        self.mood = Mood()
        self.mic = MicListener(open_stream=self.device.open)
        self.voice = VoiceController(self.panel, base="http://ade",
                                     listen=listen or (lambda *a: {"error": "unused"}))
        self.ctl = OrbController(window=self.win, orb=self.orb, renderer=self.renderer,
                                 mood=self.mood, speaker=self.speaker, mic=self.mic,
                                 voice=self.voice, state_path=self.state,
                                 avatar_running=avatar)
        self.win.orb_controller = self.ctl

    def notes(self):
        return [m["text"] for m in self.panel.view_messages("chat") if m.get("role") == "system"]


@pytest.fixture
def rig(qapp, tmp_path):
    r = Rig(tmp_path)
    yield r
    r.ctl.stop()

# ---------------------------------------------------------------- the window


def test_the_orb_is_a_frameless_on_top_tool_window_that_never_takes_focus(qapp):
    orb = OrbWindow()
    flags = orb.windowFlags()
    for flag in (Qt.WindowType.FramelessWindowHint, Qt.WindowType.WindowStaysOnTopHint,
                 Qt.WindowType.WindowDoesNotAcceptFocus):
        assert flags & flag, flag
    assert (flags & Qt.WindowType.Tool) == Qt.WindowType.Tool
    assert orb.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
    assert orb.testAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
    assert orb.focusPolicy() == Qt.FocusPolicy.NoFocus
    assert orb.width() == orb.height() == SIZES["M"]


def _framed_orb():
    orb = OrbWindow()
    r = GlyphRenderer(epoch=990.0)
    orb.show_frame(r.render(Look(online=True), SIZES["M"], 1000.0))
    return orb


def test_the_hit_test_passes_the_corners_and_takes_the_centre(qapp):
    orb = _framed_orb()
    c = SIZES["M"] // 2
    assert orb.hit(QPoint(c, c)) is True
    for p in ((2, 2), (SIZES["M"] - 3, 2), (2, SIZES["M"] - 3), (SIZES["M"] - 3, SIZES["M"] - 3)):
        assert orb.hit(QPoint(*p)) is False, p


def test_faint_glow_passes_clicks_through_and_solid_takes_them(qapp):
    """The backing glow is alpha 1..47 over much of the square: Windows only
    passes alpha-0 clicks, so the orb decides itself (review finding)."""
    orb = _framed_orb()
    c = SIZES["M"] // 2
    img = orb.frame
    faint = next(QPoint(x, c) for x in range(4, c)
                 if 0 < img.pixelColor(x, c).alpha() < 20
                 and max(img.pixelColor(x + dx, c + dy).alpha()
                         for dx in range(-6, 7) for dy in range(-6, 7)) < 48)
    assert orb.should_pass_through(faint) is True
    assert orb.should_pass_through(QPoint(c, c)) is False
    assert orb.should_pass_through(QPoint(2, 2)) is True
    assert orb.should_pass_through(QPoint(-5, c)) is True      # outside the window
    orb._press = QPoint(0, 0)                                  # mid-drag: never
    assert orb.should_pass_through(faint) is False


def test_set_through_only_touches_the_style_on_a_change(qapp, monkeypatch):
    from ade_desktop.orb import window as window_module
    calls = []
    monkeypatch.setattr(window_module, "set_input_transparent",
                        lambda hwnd, through: calls.append(through) or True)
    monkeypatch.setattr(window_module.QGuiApplication, "platformName",
                        staticmethod(lambda: "windows"))
    orb = OrbWindow()
    orb.set_through(True)
    orb.set_through(True)
    orb.set_through(False)
    assert calls == [True, False]


def _mouse(kind, pos, button=Qt.MouseButton.LeftButton, global_pos=None):
    gp = QPointF(global_pos if global_pos is not None else pos)
    return QMouseEvent(kind, QPointF(pos), gp, button, button, Qt.KeyboardModifier.NoModifier)


def test_a_click_opens_and_a_drag_moves_without_opening(qapp):
    orb = _framed_orb()
    orb.move(100, 100)
    opened, moved = [], []
    orb.open_requested.connect(lambda: opened.append(1))
    orb.moved.connect(lambda x, y: moved.append((x, y)))
    c = QPoint(190, 190)
    orb.mousePressEvent(_mouse(QMouseEvent.Type.MouseButtonPress, c, global_pos=QPoint(290, 290)))
    orb.mouseReleaseEvent(_mouse(QMouseEvent.Type.MouseButtonRelease, c, global_pos=QPoint(292, 291)))
    assert opened == [1] and moved == []
    orb.mousePressEvent(_mouse(QMouseEvent.Type.MouseButtonPress, c, global_pos=QPoint(290, 290)))
    orb.mouseMoveEvent(_mouse(QMouseEvent.Type.MouseMove, c, global_pos=QPoint(340, 310)))
    orb.mouseReleaseEvent(_mouse(QMouseEvent.Type.MouseButtonRelease, c, global_pos=QPoint(340, 310)))
    assert opened == [1] and moved == [(150, 120)]


def test_a_press_on_clear_pixels_is_ignored(qapp):
    orb = _framed_orb()
    opened = []
    orb.open_requested.connect(lambda: opened.append(1))
    ev = _mouse(QMouseEvent.Type.MouseButtonPress, QPoint(2, 2))
    orb.mousePressEvent(ev)
    orb.mouseReleaseEvent(_mouse(QMouseEvent.Type.MouseButtonRelease, QPoint(2, 2)))
    assert not ev.isAccepted() and opened == []


def test_a_dropped_orb_is_freed_at_once(qapp, tmp_path):
    """The orb as the app wires it -- menus, signals, a started controller --
    not a bare window with nothing connected (review finding)."""
    r = Rig(tmp_path)
    r.ctl.start(open_mic=False)
    r.ctl.tick()
    r.ctl.stop()
    refs = [weakref.ref(o) for o in (r.orb, r.ctl, r.speaker, r.mic, r.voice)]
    gc.disable()
    try:
        r.orb = r.ctl = r.speaker = r.mic = r.voice = None
        r.win.orb_controller = None
        assert [ref() for ref in refs] == [None] * 5
    finally:
        gc.enable()

# ------------------------------------------------------------ the controller


def test_start_shows_the_orb_and_opens_the_microphone(rig):
    rig.ctl.start()
    assert rig.orb.isVisible()
    assert rig.mic.running() and rig.device.opens == 1
    assert rig.ctl.mic_act.isChecked()


def test_with_the_avatar_running_the_mic_starts_muted_and_says_why(qapp, tmp_path):
    r = Rig(tmp_path, avatar=True)
    r.ctl.start()
    try:
        assert not r.mic.running() and r.device.opens == 0
        assert not r.ctl.mic_act.isChecked()
        assert AVATAR_NOTE in r.notes()
    finally:
        r.ctl.stop()


def test_muting_closes_the_stream(rig):
    rig.ctl.start()
    rig.ctl.mic_act.setChecked(False)
    assert not rig.mic.running() and rig.device.stream.active is False
    assert load_state(rig.state)["orb"]["mic"] is False
    rig.ctl.mic_act.setChecked(True)
    assert rig.mic.running() and rig.device.opens == 2


def test_the_mood_follows_what_ade_is_doing(rig):
    rig.ctl.start(open_mic=False)
    assert rig.mood.frame()["mood"] == "dormant"               # nothing heard yet
    rig.status.health.emit(UP)
    assert rig.mood.frame()["mood"] is None                    # online, idle
    rig.status.activity.emit({"active": True, "count": 1})
    assert rig.mood.frame()["mood"] == "thinking"
    rig.status.activity.emit({"error": "ConnectError"})       # an error is not idle
    assert rig.mood.frame()["mood"] == "thinking"
    rig.status.activity.emit({"active": False, "count": 0})
    rig.watcher.appeared.emit({"id": "a1", "tool": "run_shell", "args": {}})
    assert rig.mood.frame()["mood"] == "attentive"
    rig.watcher.vanished.emit("a1")
    assert rig.mood.frame()["mood"] is None
    rig.panel.send("hello")                                     # a turn in flight
    assert rig.mood.frame()["mood"] == "thinking"
    rig.client.done.emit("r1", {"error": "boom"})               # ... that fails
    assert rig.mood.frame()["mood"] == "troubled"


def test_an_allowed_approval_is_satisfied(rig):
    rig.ctl.start(open_mic=False)
    rig.status.health.emit(UP)
    rig.watcher.appeared.emit({"id": "a1", "tool": "write_file", "args": {}})
    card = next(m for m in rig.panel.view_messages("chat") if m["kind"] == "approval")
    rig.panel._on_card_decided("a1", True)
    rig.client.done.emit(f"r{len(rig.client.calls)}", {"ok": True})
    rig.watcher.vanished.emit("a1")
    assert card["meta"]["decided"].startswith("Allowed")
    assert rig.mood.frame()["mood"] == "satisfied"


def test_the_wake_word_startles_the_orb_and_opens_ade(rig):
    rig.ctl.start(open_mic=False)
    rig.status.health.emit(UP)
    rig.win.hide()
    assert rig.voice.on_text("Ade", "whisper") == "opened"
    assert rig.mood.frame()["mood"] == "startled"
    assert rig.renderer.wake_at > 0
    assert rig.win.isVisible() and rig.win.panel_open()


def test_replies_are_spoken_only_when_speaking_is_on(rig, pump):
    rig.ctl.start(open_mic=False)
    rig.panel.send("hello")
    rig.client.done.emit("r1", {"answer": "All good. More detail follows."})
    pump(lambda: False, timeout=0.2)
    assert rig.spoken == []                                     # default OFF
    rig.ctl.speak_act.setChecked(True)
    rig.panel.send("again")
    rig.client.done.emit("r2", {"answer": "Everything is great. Details."})
    assert pump(lambda: bool(rig.player.played))
    assert rig.spoken == ["Everything is great."]
    assert rig.mood.frame()["tint"] is not None                 # the reply's sentiment
    assert load_state(rig.state)["orb"]["speak"] is True


def test_a_frame_is_drawn_while_shown_and_never_while_hidden(qapp, tmp_path):
    r = Rig(tmp_path, tray=True)
    r.ctl.start(open_mic=False)
    try:
        r.ctl.tick()
        first = r.orb.frame
        assert first is not None and first.width() >= SIZES["M"]
        r.ctl.toggle_orb()
        assert not r.orb.isVisible() and r.ctl.orb_act.text() == "Show orb"
        r.ctl.tick()
        assert r.orb.frame is first
        assert load_state(r.state)["orb"]["visible"] is False
    finally:
        r.ctl.stop()


def test_with_no_tray_the_orb_cannot_be_hidden_for_good(qapp, tmp_path):
    r = Rig(tmp_path, saved={"orb": {"visible": False}})
    r.ctl.start(open_mic=False)
    try:
        assert r.orb.isVisible()                 # saved hidden, but nothing could show it
        assert not r.ctl.orb_act.isEnabled()
        r.ctl.toggle_orb()
        assert r.orb.isVisible()
    finally:
        r.ctl.stop()


def test_the_frame_rate_stretches_to_keep_the_ui_thread_free():
    assert OrbController.interval_for(True, 10.0) == 42      # 24 fps when cheap
    assert OrbController.interval_for(False, 10.0) == 66     # 15 fps at rest
    assert OrbController.interval_for(True, 41.0) == 117     # 200% scaling: <= 35 %


def test_the_size_changes_about_the_centre_and_stays_on_screen(rig):
    from PySide6.QtGui import QGuiApplication
    rig.ctl.start(open_mic=False)
    screen = QGuiApplication.primaryScreen().availableGeometry()
    rig.orb.move(screen.center().x() - SIZES["M"] // 2, screen.center().y() - SIZES["M"] // 2)
    before = rig.orb.geometry().center()
    rig.ctl.size_acts["L"].trigger()
    assert rig.orb.width() == SIZES["L"]
    assert (rig.orb.geometry().center() - before).manhattanLength() <= 2
    assert load_state(rig.state)["orb"]["size"] == "L"
    rig.ctl.size_acts["S"].trigger()             # from the bottom-right corner:
    rig.orb.move(screen.right() - SIZES["S"], screen.bottom() - SIZES["S"])
    rig.ctl.size_acts["L"].trigger()
    assert screen.contains(rig.orb.geometry()), (screen, rig.orb.geometry())


def test_orb_settings_and_window_state_share_window_json(qapp, tmp_path):
    r = Rig(tmp_path, saved={"orb": {"x": 40, "y": 50, "size": "S", "visible": True,
                                     "speak": True, "mic": False, "backing": False}})
    r.ctl.start()
    try:
        assert (r.orb.x(), r.orb.y()) == (40, 50) and r.orb.width() == SIZES["S"]
        assert r.ctl.speak_act.isChecked() and not r.ctl.backing_act.isChecked()
        assert not r.mic.running() and r.device.opens == 0      # remembered mute
        r.win.save_state()                                      # the window's own save
        state = load_state(r.state)
        assert state["orb"]["size"] == "S" and "w" in state      # neither clobbers the other
    finally:
        r.ctl.stop()


def test_a_position_on_a_vanished_monitor_is_pulled_back(qapp, tmp_path):
    r = Rig(tmp_path, saved={"orb": {"x": -50000, "y": -50000}})
    r.ctl.start(open_mic=False)
    try:
        assert r.orb.x() > -10000 and r.orb.y() > -10000
    finally:
        r.ctl.stop()


def test_quit_stops_the_orb_and_releases_the_microphone(rig):
    rig.ctl.start()
    rig.win.quit_app()
    assert not rig.mic.running() and rig.device.stream.active is False
    assert not rig.orb.isVisible() and rig.quits == [1]


def test_the_controller_does_not_keep_the_main_window_alive(qapp, tmp_path):
    """The window holds the controller; the controller holds the window
    weakly. Were it strong, the pair would be cyclic garbage."""
    r = Rig(tmp_path)
    ref = weakref.ref(r.win)
    gc.disable()
    try:
        r.win = None
        assert ref() is None
        assert r.ctl.window is None
        r.ctl.open_ade()                    # a late click finds no window: harmless
    finally:
        gc.enable()


def test_muting_discards_speech_already_captured_and_silences_ade(qapp, tmp_path, pump):
    import threading
    gate = threading.Event()

    def listen(url, body, timeout):
        gate.wait(5)
        return {"text": "Ade, what is pending", "engine": "whisper"}

    r = Rig(tmp_path, listen=listen)
    r.ctl.start()
    try:
        r.ctl.speak_act.setChecked(True)
        r.mic.utterance.emit({"samples": [0.1] * 1600, "rate": 16000})   # in flight
        r.mic.utterance.emit({"samples": [0.1] * 1600, "rate": 16000})   # waiting
        hushed = []
        r.speaker.hush = lambda: hushed.append(1)
        r.ctl.mic_act.setChecked(False)
        gate.set()
        pump(lambda: not r.voice._inflight, timeout=3)
        pump(lambda: False, timeout=0.2)
        assert r.client.calls == []               # nothing asked after the mute
        assert hushed and r.win.isHidden()
    finally:
        r.ctl.stop()


def test_an_utterance_arriving_after_mute_is_dropped(rig):
    rig.ctl.start()
    rig.ctl.mic_act.setChecked(False)
    rig.mic.utterance.emit({"samples": [0.1] * 1600, "rate": 16000})
    assert rig.voice._inflight is False


def test_ade_stop_silences_the_reply(rig):
    rig.ctl.start(open_mic=False)
    hushed = []
    rig.speaker.hush = lambda: hushed.append(1)
    rig.voice.hush_requested.disconnect()
    rig.voice.hush_requested.connect(rig.speaker.hush)
    assert rig.voice.on_text("Ade, stop.", "whisper") == "hushed"
    assert hushed == [1] and rig.client.calls == []


# -- the mute button (Ray, 2026-09-18: "i need a mute botton") ----------------

def test_the_header_has_a_mute_button_that_mutes_and_unmutes(rig):
    rig.win.attach_mic(rig.ctl)
    rig.ctl.start()
    button = rig.win.mic_button
    assert button.isVisibleTo(rig.win) and button.text() == "Mute"
    button.click()
    assert not rig.mic.running() and rig.device.stream.active is False
    assert button.text() == "Unmute" and button.property("muted") is True
    assert not rig.ctl.mic_act.isChecked()               # the orb's menu agrees
    assert load_state(rig.state)["orb"]["mic"] is False  # and it is remembered
    button.click()
    assert rig.mic.running() and button.text() == "Mute" and rig.ctl.mic_act.isChecked()


def test_the_orb_menu_and_the_button_stay_in_step(rig):
    rig.win.attach_mic(rig.ctl)
    rig.ctl.start()
    rig.ctl.mic_act.setChecked(False)                    # muted from the orb's menu
    assert rig.win.mic_button.text() == "Unmute"
    rig.ctl.mic_act.setChecked(True)
    assert rig.win.mic_button.text() == "Mute"


def test_muted_for_the_avatar_the_button_says_unmute(qapp, tmp_path):
    r = Rig(tmp_path, avatar=True)
    r.win.attach_mic(r.ctl)
    r.ctl.start()
    try:
        assert r.win.mic_button.text() == "Unmute"
        r.win.mic_button.click()                         # Ray's explicit choice
        assert r.mic.running() and r.win.mic_button.text() == "Mute"
    finally:
        r.ctl.stop()


def test_a_microphone_that_will_not_open_leaves_the_button_on_unmute(qapp, tmp_path):
    r = Rig(tmp_path)

    def broken(callback):
        raise OSError("no input device")

    r.mic._open = broken                                 # the device is gone
    r.win.attach_mic(r.ctl)
    r.ctl.start()
    try:
        assert not r.mic.running() and r.win.mic_button.text() == "Unmute"
        r.win.mic_button.click()
        assert not r.mic.running() and r.win.mic_button.text() == "Unmute"
        assert not r.ctl.mic_act.isChecked()
    finally:
        r.ctl.stop()


def test_without_an_orb_there_is_no_mute_button(qapp, tmp_path):
    win = DesktopWindow([Section("Trader", QLabel("t"))], FakeStatus(),
                        state_path=tmp_path / "w.json", tray_available=False)
    assert not win.mic_button.isVisibleTo(win)


# -- the mute button ON the orb (Ray, 2026-09-18: "put a mute button on the orb too") --

def _badge_point(orb):
    centre, _radius = orb.badge()
    return QPoint(round(centre.x()), round(centre.y()))


def _badge_colour(orb):
    """The average colour inside the mic button, as painted."""
    from PySide6.QtGui import QColor  # noqa: F401
    img = orb.grab().toImage()
    centre, radius = orb.badge()
    rs = gs = bs = n = 0
    for dx in range(-int(radius) + 3, int(radius) - 2, 2):
        for dy in range(-int(radius) + 3, int(radius) - 2, 2):
            if dx * dx + dy * dy <= (radius - 3) ** 2:
                c = img.pixelColor(round(centre.x()) + dx, round(centre.y()) + dy)
                rs, gs, bs, n = rs + c.red(), gs + c.green(), bs + c.blue(), n + 1
    return rs / n, gs / n, bs / n


def test_the_orb_draws_a_mic_button_that_shows_the_state(qapp):
    orb = _framed_orb()
    orb.set_mic_badge(True)
    r1, g1, b1 = _badge_colour(orb)
    orb.set_mic_badge(False)
    r2, g2, b2 = _badge_colour(orb)
    assert r2 > g2 + 25 and r2 > b2 + 25                  # muted reads red
    assert not (r1 > g1 + 25 and r1 > b1 + 25)            # listening does not
    assert orb.listening is False


@pytest.mark.parametrize("key", ["S", "M", "L"])
def test_the_mic_button_sits_low_on_the_orb_at_every_size(qapp, key):
    orb = OrbWindow(SIZES[key])
    centre, radius = orb.badge()
    size = SIZES[key]
    assert centre.x() == size / 2 and size * 0.8 < centre.y() < size - radius
    assert radius >= 12                                   # big enough to aim at


def test_the_mic_button_takes_clicks_where_the_glyph_is_clear(qapp):
    from PySide6.QtGui import QImage
    orb = OrbWindow()
    clear = QImage(SIZES["M"], SIZES["M"], QImage.Format.Format_ARGB32_Premultiplied)
    clear.fill(0)
    orb.show_frame(clear)
    b = _badge_point(orb)
    assert orb.hit(b) is True and orb.should_pass_through(b) is False
    c = SIZES["M"] // 2
    assert orb.hit(QPoint(c, c)) is False                 # the rest still passes


def test_a_click_on_the_mic_button_mutes_and_does_not_open(qapp):
    orb = _framed_orb()
    orb.move(100, 100)
    opened, muted = [], []
    orb.open_requested.connect(lambda: opened.append(1))
    orb.mute_requested.connect(lambda: muted.append(1))
    b = _badge_point(orb)
    g = b + QPoint(100, 100)
    orb.mousePressEvent(_mouse(QMouseEvent.Type.MouseButtonPress, b, global_pos=g))
    orb.mouseReleaseEvent(_mouse(QMouseEvent.Type.MouseButtonRelease, b, global_pos=g))
    assert muted == [1] and opened == []
    c = QPoint(190, 190)
    orb.mousePressEvent(_mouse(QMouseEvent.Type.MouseButtonPress, c, global_pos=QPoint(290, 290)))
    orb.mouseReleaseEvent(_mouse(QMouseEvent.Type.MouseButtonRelease, c, global_pos=QPoint(290, 290)))
    assert muted == [1] and opened == [1]


def test_a_drag_from_the_mic_button_moves_the_orb_and_mutes_nothing(qapp):
    orb = _framed_orb()
    orb.move(100, 100)
    muted, moved = [], []
    orb.mute_requested.connect(lambda: muted.append(1))
    orb.moved.connect(lambda x, y: moved.append((x, y)))
    b = _badge_point(orb)
    g = b + QPoint(100, 100)
    orb.mousePressEvent(_mouse(QMouseEvent.Type.MouseButtonPress, b, global_pos=g))
    orb.mouseMoveEvent(_mouse(QMouseEvent.Type.MouseMove, b, global_pos=g + QPoint(40, -30)))
    orb.mouseReleaseEvent(_mouse(QMouseEvent.Type.MouseButtonRelease, b, global_pos=g + QPoint(40, -30)))
    assert muted == [] and moved == [(140, 70)]


def test_the_pointer_over_the_mic_button_is_a_hand(qapp):
    orb = _framed_orb()
    orb.sync_cursor(_badge_point(orb))
    assert orb.cursor().shape() == Qt.CursorShape.PointingHandCursor
    orb.sync_cursor(QPoint(190, 190))
    assert orb.cursor().shape() == Qt.CursorShape.ArrowCursor


def test_the_orb_button_and_the_header_button_are_one_mute(rig):
    rig.win.attach_mic(rig.ctl)
    rig.ctl.start()
    assert rig.orb.listening is True
    rig.orb.mute_requested.emit()                         # a click on the orb's button
    assert not rig.mic.running() and rig.device.stream.active is False
    assert rig.orb.listening is False and rig.win.mic_button.text() == "Unmute"
    assert not rig.ctl.mic_act.isChecked()
    rig.win.mic_button.click()                            # unmuted from the header
    assert rig.mic.running() and rig.orb.listening is True


def test_the_orb_is_busy_while_any_section_s_chat_works(qapp, tmp_path):
    """Voice talks to General, but the mood is every chat's (2026-09-18)."""
    r = Rig(tmp_path)
    side_client, side_watcher = FakeClient(), FakeWatcher()
    side = ConversationPanel(side_client, side_watcher, ThreadStore(tmp_path / "t-pm.json"))
    # Both pages hold a STACK since 2026-09-24; the mood still walks every
    # SESSION inside them, which is what this test is about.
    side_stack = ChatStack("PM", lambda _n, p=side: p)
    win = DesktopWindow([Section("PM", QLabel("pm"))], r.status, state_path=r.state,
                        tray_available=False, quit_fn=lambda: None, panel=r.stack,
                        side_panels={"PM": side_stack})
    ctl = OrbController(window=win, orb=OrbWindow(), renderer=GlyphRenderer(epoch=0.0),
                        mood=Mood(), speaker=r.speaker, mic=MicListener(open_stream=r.device.open),
                        voice=r.voice, state_path=r.state, avatar_running=True)
    win.orb_controller = ctl
    try:
        assert ctl.busy() is False
        side.send("list the risks")
        assert ctl.busy() is True and not r.panel.busy
    finally:
        ctl.stop()
