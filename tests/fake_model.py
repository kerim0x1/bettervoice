"""A stand-in for Whisper inside the recognition process (see test_local.py)."""

import os


class FakeWhisper:
    def __init__(self, name, device, path):
        if name == "broken":
            raise RuntimeError("no such model")
        self.name, self.device = name, device

    def warm_up(self):
        pass

    def transcribe(self, audio, language=None, prompt=""):
        if prompt == "crash":
            os._exit(3)  # like a GPU driver taking the process down
        return f"{len(audio)} samples, {language}, {prompt!r}"
