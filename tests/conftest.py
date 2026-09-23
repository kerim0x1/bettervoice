"""Shared fixtures: isolated settings, a fake microphone, test audio, a mock HTTP server."""

import http.server
import json
import os
import sys
import threading
import time
import wave

import numpy as np
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "tests", "data")
sys.path.insert(0, os.path.join(ROOT, "src"))  # also works without `pip install -e .`

from bettervoice import config, mic  # noqa: E402

SETTING_ENV_NAMES = [name for names, _ in config._SETTINGS.values() for name in names]


def pcm(name):
    """16 kHz mono 16-bit PCM bytes of a test clip."""
    with wave.open(os.path.join(DATA, name)) as w:
        return w.readframes(w.getnframes())


def silence(seconds):
    return b"\0\0" * int(16000 * seconds)


def to_float(data):
    return np.frombuffer(data, np.int16).astype(np.float32) / 32768.0


@pytest.fixture
def settings(tmp_path, monkeypatch):
    """Settings written to a temp .env, starting from defaults."""
    monkeypatch.setattr(config, "CONFIG_ENV", str(tmp_path / ".env"))
    for name in SETTING_ENV_NAMES:
        monkeypatch.delenv(name, raising=False)
    return config


class FakeStream:
    """Stands in for sounddevice.RawInputStream: plays `audio`, then silence.

    speed > 1 plays faster than real time (tests don't need to wait).
    """

    audio = b""
    speed = 1.0

    def __init__(self, samplerate, blocksize, dtype, channels, callback):
        self.callback = callback
        self.block = blocksize * 2
        self.running = False

    def start(self):
        self.running = True
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        pos, started = 0, time.perf_counter()
        while self.running:
            chunk = self.audio[pos:pos + self.block] or b"\0" * self.block
            self.callback(chunk, self.block // 2, None, None)
            pos += self.block
            delay = started + pos / 32000 / self.speed - time.perf_counter()
            time.sleep(max(0.0, delay))

    def stop(self):
        self.running = False

    close = stop


@pytest.fixture
def fake_mic(monkeypatch):
    """Returns a function play(audio_bytes, speed=1.0) that sets what the mic hears."""
    monkeypatch.setattr(mic.sd, "RawInputStream", FakeStream)

    def play(audio, speed=1.0):
        FakeStream.audio = audio
        FakeStream.speed = speed

    play(b"")
    return play


class MockServer:
    """A local HTTP server; tests set `responses` and read `requests`."""

    def __init__(self):
        self.requests = []
        self.responses = []  # (status, body dict or bytes, close_after)
        server = self

        class Handler(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"  # keep-alive, like the real APIs

            def do_POST(self):
                self._handle()

            def do_GET(self):
                self._handle()

            def _handle(self):
                length = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(length)
                server.requests.append({"method": self.command, "path": self.path,
                                        "headers": dict(self.headers), "body": body})
                status, payload, close_after = (server.responses.pop(0) if server.responses
                                                else (200, {}, False))
                data = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                # drop the connection without announcing it, like an idle timeout
                self.close_connection = close_after

            def log_message(self, *args):
                pass

        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.host = f"127.0.0.1:{self.httpd.server_address[1]}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


@pytest.fixture
def server():
    s = MockServer()
    yield s
    s.close()
