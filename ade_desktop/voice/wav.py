"""WAV in and out -- the avatar's encodeWav()/downsample() (ptt.js), plus the
loudness envelope that drives the orb's mouth while Ade speaks. Pure."""

from __future__ import annotations

import io
import math
import struct
import wave


def downsample(samples, src_rate: int, dst_rate: int = 16000) -> list[float]:
    """Linear interpolation to dst_rate (the avatar resamples to 16 kHz
    before /v1/voice/listen)."""
    samples = list(samples)
    if src_rate == dst_rate or not samples:
        return samples
    n_out = int(round(len(samples) * dst_rate / src_rate))
    ratio = src_rate / dst_rate
    out = []
    last = len(samples) - 1
    for i in range(n_out):
        pos = i * ratio
        j = int(pos)
        frac = pos - j
        a = samples[min(j, last)]
        b = samples[min(j + 1, last)]
        out.append(a + (b - a) * frac)
    return out


def encode_wav(samples, rate: int = 16000) -> bytes:
    """16-bit PCM mono WAV from floats in -1..1 (clipped)."""
    frames = b"".join(
        struct.pack("<h", int(max(-1.0, min(1.0, s)) * 32767)) for s in samples)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(frames)
    return buf.getvalue()


def rms_envelope(wav_bytes: bytes, frame_ms: int = 20) -> list[float]:
    """Loudness per frame, normalised so the loudest frame is 1.0. The orb's
    mouth reads it at (now - start) while the reply plays."""
    with wave.open(io.BytesIO(wav_bytes)) as w:
        rate, width, channels = w.getframerate(), w.getsampwidth(), w.getnchannels()
        raw = w.readframes(w.getnframes())
    if width != 2 or not raw:
        return []
    count = len(raw) // 2
    values = struct.unpack(f"<{count}h", raw[:count * 2])
    if channels > 1:
        values = values[::channels]
    step = max(1, int(rate * frame_ms / 1000))
    env = []
    for i in range(0, len(values), step):
        chunk = values[i:i + step]
        env.append(math.sqrt(sum(v * v for v in chunk) / len(chunk)) / 32768.0)
    peak = max(env) if env else 0.0
    return [e / peak for e in env] if peak > 0 else env
