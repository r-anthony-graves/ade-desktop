"""The pure half of voice: the wake rule, WAV encoding, the loudness
envelope, and utterance segmentation -- the avatar's rules and constants."""

import io
import math
import wave

from ade_desktop.voice.segmenter import HANG_MS, MAX_MS, MIN_MS, Segmenter
from ade_desktop.voice.wake import strip_wake
from ade_desktop.voice.wav import downsample, encode_wav, rms_envelope

RATE = 16000


def test_the_wake_word():
    assert strip_wake("Ade, run the tests") == "run the tests"
    assert strip_wake("hey ade what time is it") == "what time is it"
    assert strip_wake("ok Aday, x") == "x"
    assert strip_wake("ADA open the window") == "open the window"
    assert strip_wake("Adelaide is lovely") is None
    assert strip_wake("Ada") is None           # a separator and more text needed
    assert strip_wake("ade ") == ""
    assert strip_wake("the ade thing") is None
    assert strip_wake(None) is None


def _tone(ms, amp=0.3, freq=220.0, rate=RATE):
    n = int(rate * ms / 1000)
    return [amp * math.sin(2 * math.pi * freq * i / rate) for i in range(n)]


def _silence(ms, rate=RATE):
    return [0.0] * int(rate * ms / 1000)


def _feed(seg, samples, rate=RATE, block=320):
    out = []
    for i in range(0, len(samples), block):
        out += seg.feed(samples[i:i + block], rate)
    return out


def test_wav_round_trips():
    data = encode_wav(_tone(100), RATE)
    with wave.open(io.BytesIO(data)) as w:
        assert (w.getframerate(), w.getnchannels(), w.getsampwidth()) == (16000, 1, 2)
        assert w.getnframes() == 1600


def test_downsample_is_the_avatars_box_average():
    assert len(downsample([0.0] * 44100, 44100, 16000)) == 16000
    assert downsample([1.0, 2.0], 16000, 16000) == [1.0, 2.0]
    assert downsample([1.0, 3.0, 5.0, 7.0], 32000, 16000) == [2.0, 6.0]
    # a tone at the new Nyquist averages away rather than aliasing through
    alt = [1.0, -1.0] * 100
    assert max(abs(v) for v in downsample(alt, 32000, 16000)) == 0.0


def test_rms_envelope_follows_loudness():
    wav = encode_wav(_silence(200) + _tone(200, amp=0.8), RATE)
    env = rms_envelope(wav, frame_ms=20)
    assert len(env) == 20
    assert max(env[:9]) < 0.05 and min(env[11:]) > 0.5
    assert max(env) <= 1.0


def test_silence_is_not_an_utterance():
    assert _feed(Segmenter(), _silence(2000)) == []


def test_a_word_then_silence_is_one_utterance_hangover_included():
    got = _feed(Segmenter(), _tone(500) + _silence(HANG_MS + 200))
    assert len(got) == 1
    secs = len(got[0]) / RATE
    assert 0.5 + HANG_MS / 1000 - 0.03 <= secs <= 0.5 + (HANG_MS + 40) / 1000


def test_a_short_word_is_sent_because_the_hangover_counts():
    """The avatar measures MIN_MS on the whole segment: a bare "Ade." or
    "yes" (200 ms) plus the 400 ms hang is 600 ms and is sent."""
    assert MIN_MS == 300
    got = _feed(Segmenter(), _tone(200) + _silence(HANG_MS + 200))
    assert len(got) == 1


def test_under_the_minimum_is_dropped():
    seg = Segmenter()
    seg._hearing, seg._buf = False, [0.1] * int(RATE * 0.2)
    assert seg._send(RATE) == []                 # 200 ms in all: a cough


def test_a_long_noise_is_sent_whole_at_the_ceiling():
    assert MAX_MS == 12000
    got = _feed(Segmenter(), _tone(13000))
    assert len(got) == 1 and 12.0 < len(got[0]) / RATE <= 12.03


def test_the_hangover_joins_close_words_and_splits_far_ones():
    close = _feed(Segmenter(), _tone(400) + _silence(300) + _tone(400) + _silence(600))
    far = _feed(Segmenter(), _tone(400) + _silence(600) + _tone(400) + _silence(600))
    assert len(close) == 1 and len(far) == 2


def test_segmentation_is_rate_independent():
    got = _feed(Segmenter(), _tone(500, rate=44100) + _silence(700, rate=44100),
                rate=44100, block=882)
    assert len(got) == 1 and abs(len(got[0]) / 44100 - 0.9) < 0.05
