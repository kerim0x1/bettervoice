"""Conversions between the float32 audio used internally and upload formats."""

import io
import wave

import numpy as np

from bettervoice.mic import SAMPLE_RATE


def to_pcm16(audio):
    """float32 in [-1, 1] -> little-endian 16-bit PCM bytes."""
    return (np.clip(audio, -1.0, 1.0) * 32767).astype("<i2").tobytes()


def from_pcm16(data):
    """16-bit PCM bytes -> float32 in [-1, 1]."""
    return np.frombuffer(data, np.int16).astype(np.float32) / 32768.0


def to_wav(audio):
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(to_pcm16(audio))
    return buf.getvalue()
