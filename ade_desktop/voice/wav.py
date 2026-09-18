"""WAV in and out -- the avatar's encodeWav()/downsample() (ptt.js), plus the
loudness envelope that drives the orb's mouth while Ade speaks. Pure."""

from __future__ import annotations

import io
import math
import struct
import wave


def downsample(samples, src_rate: int, dst_rate: int = 16000) -> list[float]:
    """ptt.js's downsample(): each output sample is the MEAN of the input
    samples it covers -- a crude low-pass, which linear interpolation is
    not (review, 2026-09-18). Upsampling is never done: the input is
    returned as it came."""
    samples = list(samples)
    if dst_rate >= src_rate or not samples:
        return samples
    ratio = src_rate / dst_rate
    n_out = math.floor(len(samples) / ratio)    # as JS: floor(len / ratio)
    out = []
    for i in range(n_out):
        start = int(i * ratio)
        end = min(len(samples), int((i + 1) * ratio))
        n = end - start
        out.append(sum(samples[start:end]) / n if n else 0.0)
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
