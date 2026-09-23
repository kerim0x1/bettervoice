"""Microphone capture: 16 kHz mono int16, delivered in 50 ms chunks."""

import numpy as np
import sounddevice as sd

SAMPLE_RATE = 16000
CHUNK_MS = 50

PortAudioError = sd.PortAudioError


class Microphone:
    """Calls on_audio(bytes) for every chunk and on_level(0..1) for the overlay.

    Both callbacks run on the PortAudio thread, so they must be quick.
    """

    def __init__(self, on_audio, on_level=None):
        self.on_audio = on_audio
        self.on_level = on_level
        self.stream = None

    def start(self):
        self.stream = sd.RawInputStream(
            samplerate=SAMPLE_RATE,
            blocksize=SAMPLE_RATE * CHUNK_MS // 1000,
            dtype="int16",
            channels=1,
            callback=self._callback,
        )
        try:
            self.stream.start()
        except Exception:
            self.stream.close()
            raise

    def stop(self):
        """Stop and release the device; buffered audio is delivered first."""
        if self.stream is None:
            return
        try:
            self.stream.stop()
        finally:
            self.stream.close()
            self.stream = None

    def _callback(self, indata, frames, time_info, status):
        chunk = bytes(indata)  # indata is reused by PortAudio: copy it
        self.on_audio(chunk)
        if self.on_level is not None and chunk:
            samples = np.frombuffer(chunk, np.int16).astype(np.float32)
            rms = float(np.sqrt(np.mean(samples * samples)))
            self.on_level(min(1.0, (rms / 4000.0) ** 0.7))
