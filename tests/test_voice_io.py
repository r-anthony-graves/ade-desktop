"""The microphone and the speaker, with the device and the player faked:
mute really closes the stream, the level is throttled, an utterance crosses
to the UI thread, a reply is clipped like the avatar's, the mouth follows
the WAV, a new reply stops the old one, and a fault is reported once."""

import gc
import math
import threading
import weakref

import pytest

from ade_desktop.voice.mic import MicListener
from ade_desktop.voice.speaker import MAX_SPOKEN_CHARS, Speaker, clip_for_speech
from ade_desktop.voice.wav import encode_wav

# ------------------------------------------------------------------ the mic


class FakeStream:
    def __init__(self):
        self.active = True
        self.closed = False
        self.stopped = False

    def stop(self):
        self.stopped = True
        self.active = False

    def close(self):
        self.closed = True


class FakeDevice:
    def __init__(self, rate=16000):
        self.rate = rate
        self.callback = None
        self.stream = None
        self.opens = 0

    def open(self, callback):
        self.opens += 1
        self.callback = callback
        self.stream = FakeStream()
        return self.stream, self.rate

    def push(self, samples, block=320):
        import array
        for i in range(0, len(samples), block):
            self.callback(array.array("f", samples[i:i + block]).tobytes(), block, None, None)


def _tone(ms, rate=16000, amp=0.3):
    return [amp * math.sin(2 * math.pi * 220 * i / rate) for i in range(int(rate * ms / 1000))]


def test_mute_closes_the_stream_and_running_says_so(qapp):
    dev = FakeDevice()
    mic = MicListener(open_stream=dev.open)
    assert mic.start() is True and mic.running()
    mic.stop()
    assert dev.stream.stopped and dev.stream.closed
    assert mic.running() is False
    dev.push(_tone(600) + [0.0] * 16000)       # a late block after mute
    # nothing is segmented after stop: no error, no utterance


def test_an_utterance_crosses_to_the_ui_thread(qapp, pump):
    dev = FakeDevice()
    mic = MicListener(open_stream=dev.open)
    got, threads = [], []
    mic.utterance.connect(lambda u: (got.append(u), threads.append(threading.current_thread())))
    mic.start()
    worker = threading.Thread(target=dev.push, args=(_tone(600) + [0.0] * 8000,))
    worker.start()
    worker.join()
    assert pump(lambda: bool(got))
    assert got[0]["rate"] == 16000 and len(got[0]["samples"]) > 9000
    assert threads[0] is threading.main_thread()
    mic.stop()


def test_the_level_is_throttled_to_twenty_a_second(qapp, pump):
    dev = FakeDevice()
    clock = [0.0]
    mic = MicListener(open_stream=dev.open, clock=lambda: clock[0])
    levels = []
    mic.level.connect(levels.append)
    mic.start()
    for i in range(50):                         # 50 blocks inside 0.1 s
        clock[0] = i * 0.002
        dev.push(_tone(20))
    qapp.processEvents()
    assert 1 <= len(levels) <= 3
    assert all(0 < v <= 1 for v in levels)
    mic.stop()


def test_no_microphone_is_a_signal_not_a_crash(qapp):
    def broken(callback):
        raise OSError("no default input device")
    mic = MicListener(open_stream=broken)
    failures = []
    mic.failed.connect(failures.append)
    assert mic.start() is False and not mic.running()
    assert "no default input device" in failures[0]


def test_the_stream_does_not_keep_the_listener_alive(qapp):
    dev = FakeDevice()
    mic = MicListener(open_stream=dev.open)
    mic.start()
    ref = weakref.ref(mic)
    gc.disable()
    try:
        del mic
        assert ref() is None
    finally:
        gc.enable()
    dev.push(_tone(40))                          # the stream outlived it: harmless

# -------------------------------------------------------------- the speaker


def test_clip_for_speech_is_the_avatars_rule():
    assert clip_for_speech("Done. Then more text here.") == "Done."
    assert clip_for_speech("  hello   there  ") == "hello there"
    assert clip_for_speech("The user asks about X. Fine.") == ""
    long = "word " * 80
    clipped = clip_for_speech(long)
    assert len(clipped) <= MAX_SPOKEN_CHARS + 1 and clipped.endswith(".")
    assert clip_for_speech("") == ""


class FakePlayer:
    def __init__(self, fail=False):
        self.played, self.stops, self.fail = [], 0, fail

    def play(self, path):
        if self.fail:
            raise RuntimeError("Failed to play sound")
        self.played.append(path)

    def stop(self):
        self.stops += 1


def _wav():
    rate = 16000
    samples = [0.0] * (rate // 5) + [0.8 * math.sin(i / 3) for i in range(rate // 5)]
    return encode_wav(samples, rate)          # 0.4 s: quiet, then loud


def _speaker(tmp_path, post, player=None, clock=None):
    return Speaker("http://ade", post=post, player=player or FakePlayer(),
                   clock=clock or (lambda: 100.0), tmpdir=tmp_path)


def test_speak_posts_the_clip_and_plays_the_wav(qapp, tmp_path, pump):
    posted = []

    def post(url, body, timeout):
        posted.append((url, body, timeout))
        return {"wav": _wav()}

    player = FakePlayer()
    sp = _speaker(tmp_path, post, player)
    started = []
    sp.started.connect(started.append)
    assert sp.speak("All tests pass. Here are the details...") is True
    assert pump(lambda: bool(started))
    assert posted == [("http://ade/v1/voice/speak", {"text": "All tests pass."}, 180.0)]
    assert len(player.played) == 1 and started[0] == pytest.approx(0.4, abs=0.03)
    sp.close()


def test_the_mouth_follows_the_envelope(qapp, tmp_path, pump):
    now = [100.0]
    sp = _speaker(tmp_path, lambda *a: {"wav": _wav()}, clock=lambda: now[0])
    started = []
    sp.started.connect(started.append)
    sp.speak("Hello.")
    assert pump(lambda: bool(started))
    assert sp.level(100.05) < 0.05          # the quiet half
    assert sp.level(100.30) > 0.5           # the loud half
    assert sp.level(101.0) == 0.0           # finished
    sp.close()


def test_a_second_reply_stops_the_first(qapp, tmp_path, pump):
    player = FakePlayer()
    sp = _speaker(tmp_path, lambda *a: {"wav": _wav()}, player)
    started = []
    sp.started.connect(started.append)
    sp.speak("One.")
    assert pump(lambda: len(started) == 1)
    sp.speak("Two.")
    assert pump(lambda: len(started) == 2)
    assert player.stops >= 1 and len(player.played) == 2
    assert len(list(tmp_path.glob("ade-desktop-speak-*.wav"))) == 1   # the old file went
    sp.close()
    assert list(tmp_path.glob("ade-desktop-speak-*.wav")) == []


def test_a_superseded_fetch_is_never_played(qapp, tmp_path, pump):
    gate = threading.Event()
    player = FakePlayer()

    def post(url, body, timeout):
        if body["text"] == "Slow.":
            gate.wait(5)
        return {"wav": _wav()}

    sp = _speaker(tmp_path, post, player)
    started = []
    sp.started.connect(started.append)
    sp.speak("Slow.")
    sp.speak("Fast.")
    assert pump(lambda: len(started) == 1)
    gate.set()
    pump(lambda: False, timeout=0.3)
    assert len(player.played) == 1


def test_a_fault_is_reported_once_per_kind(qapp, tmp_path, pump):
    sp = _speaker(tmp_path, lambda *a: {
        "error": {"code": "voice_unavailable", "message": "no tts"}, "status": 503})
    notes = []
    sp.failed.connect(notes.append)
    for _ in range(3):
        sp.speak("Hello.")
        pump(lambda: False, timeout=0.15)
    assert len(notes) == 1 and "voice_unavailable" in notes[0]


def test_no_audio_device_is_a_note_not_a_crash(qapp, tmp_path, pump):
    sp = _speaker(tmp_path, lambda *a: {"wav": _wav()}, FakePlayer(fail=True))
    notes = []
    sp.failed.connect(notes.append)
    sp.speak("Hello.")
    assert pump(lambda: bool(notes))
    assert "Failed to play sound" in notes[0]
    assert list(tmp_path.glob("ade-desktop-speak-*.wav")) == []
