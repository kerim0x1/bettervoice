import http.server
import json
import os
import threading
import time
import types

import numpy as np
import pytest

from bettervoice.stt import local
from bettervoice.stt.errors import SttError

FILES = {
    "config.json": b'{"a": 1}',
    "model.bin": os.urandom(300_000),
    "tokenizer.json": b"{}",
    "vocabulary.txt": b"a\nb\n",
    "README.md": b"not needed",
}


class Hub(http.server.BaseHTTPRequestHandler):
    """A tiny stand-in for huggingface.co: file listing + ranged downloads."""

    honor_range = True
    requests = []

    def do_GET(self):
        Hub.requests.append((self.path, self.headers.get("Range")))
        if self.path.startswith("/api/models/"):
            listing = [{"type": "file", "path": p, "size": len(d)} for p, d in FILES.items()]
            self._send(200, json.dumps(listing).encode())
            return
        data = FILES[self.path.rsplit("/", 1)[-1]]
        start = 0
        header = self.headers.get("Range")
        if header and Hub.honor_range:
            start = int(header.split("=")[1].split("-")[0])
        self._send(206 if start else 200, data[start:])

    def _send(self, status, data):
        self.send_response(status)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


@pytest.fixture
def hub(tmp_path, monkeypatch):
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Hub)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    monkeypatch.setattr(local, "HUB", f"http://127.0.0.1:{server.server_address[1]}")
    monkeypatch.setattr(local.config, "MODELS_DIR", str(tmp_path / "models"))
    monkeypatch.setattr(local, "_legacy_path", lambda name: None)
    Hub.requests, Hub.honor_range = [], True
    yield tmp_path / "models"
    server.shutdown()
    server.server_close()


def test_download_with_progress(hub):
    progress = []
    assert local.model_path("small") is None
    folder = local.download("small", lambda done, total: progress.append((done, total)))
    assert local.model_path("small") == folder
    for name in ("config.json", "model.bin", "tokenizer.json", "vocabulary.txt"):
        with open(os.path.join(folder, name), "rb") as f:
            assert f.read() == FILES[name]
    assert not os.path.exists(os.path.join(folder, "README.md"))  # only what Whisper needs
    total = sum(len(FILES[n]) for n in ("config.json", "model.bin", "tokenizer.json",
                                        "vocabulary.txt"))
    assert progress[-1] == (total, total)


def test_download_resumes(hub):
    folder = hub / "small"
    folder.mkdir(parents=True)
    (folder / "model.bin.part").write_bytes(FILES["model.bin"][:100_000])
    local.download("small")
    assert (folder / "model.bin").read_bytes() == FILES["model.bin"]
    assert ("/Systran/faster-whisper-small/resolve/main/model.bin", "bytes=100000-") in Hub.requests


def test_download_starts_over_if_the_server_ignores_ranges(hub):
    Hub.honor_range = False
    folder = hub / "small"
    folder.mkdir(parents=True)
    (folder / "model.bin.part").write_bytes(b"x" * 1000)
    local.download("small")
    assert (folder / "model.bin").read_bytes() == FILES["model.bin"]


def fake_whisper(name="small", closed=None):
    return types.SimpleNamespace(
        name=name, device="cpu", close=lambda: closed is not None and closed.append(name),
        transcribe=lambda audio, language, prompt: f"{name}: {len(audio)}")


def test_failed_load_is_retried(monkeypatch):
    engine = local.LocalEngine()
    attempts = []

    def load(choice, still_wanted):
        attempts.append(choice)
        if len(attempts) == 1:
            raise SttError("Model download failed – check your internet connection")
        return fake_whisper()

    monkeypatch.setattr(engine, "_load_whisper", load)
    engine.load("small")
    with pytest.raises(SttError, match="download failed"):
        engine.wait()
    assert engine.state == "error"
    engine.load("small")  # same choice: loads again because it failed
    assert engine.wait().name == "small"
    assert engine.state == "ready" and attempts == ["small", "small"]
    engine.load("small")  # loaded: nothing to do
    assert attempts == ["small", "small"]


def test_unload_releases_waiting_sessions(monkeypatch):
    engine = local.LocalEngine()
    release = threading.Event()
    monkeypatch.setattr(engine, "_load_whisper",
                        lambda choice, still_wanted: release.wait(5) and fake_whisper())
    engine.load("large-v3-turbo")
    errors = []
    waiter = threading.Thread(target=lambda: errors.append(pytest.raises(SttError, engine.wait)))
    waiter.start()
    time.sleep(0.1)
    engine.unload()
    waiter.join(1)
    assert not waiter.is_alive() and errors
    release.set()
    time.sleep(0.1)
    assert engine.state == "off"  # the late load result was discarded


def test_status_is_reported(monkeypatch):
    engine = local.LocalEngine()
    seen = []
    engine.on_status = lambda: seen.append(engine.state)
    monkeypatch.setattr(engine, "_load_whisper", lambda choice, still_wanted: fake_whisper())
    engine.load("small")
    engine.wait()
    time.sleep(0.05)
    assert seen[0] == "loading" and seen[-1] == "ready"
    assert engine.status == "ready – small (CPU)"


def test_resolve():
    assert local.resolve("auto", gpu=True) == "large-v3-turbo"
    assert local.resolve("auto", gpu=False) == "small"
    assert local.resolve("base", gpu=True) == "base"


def wait_for(condition, timeout=5):
    deadline = time.monotonic() + timeout
    while not condition() and time.monotonic() < deadline:
        time.sleep(0.01)
    return condition()


def test_fetch_downloads_without_loading(hub, settings):
    engine = local.LocalEngine()
    engine.fetch("small")
    assert wait_for(lambda: engine.status == "small – loads when you dictate")
    assert engine.state == "off" and local.model_path("small") is not None
    assert engine._whisper is None  # nothing in memory until a dictation starts


def test_idle_model_is_freed_and_loads_again(monkeypatch, settings):
    monkeypatch.setattr(local, "IDLE_UNLOAD_S", 0.3)
    monkeypatch.setattr(local, "IDLE_CHECK_S", 0.05)
    engine = local.LocalEngine()
    closed = []
    loads = []

    def load(choice, still_wanted):
        loads.append(choice)
        return fake_whisper(choice, closed)

    monkeypatch.setattr(engine, "_load_whisper", load)
    settings.set("local_model", "small")
    engine.load("small")
    assert engine.transcribe([0.0] * 5, "de", "") == "small: 5"
    assert engine.state == "ready"
    assert wait_for(lambda: engine.state == "off")  # idle: freed
    assert wait_for(lambda: closed == ["small"])
    assert engine.status == "small – loads when you dictate"
    assert engine.transcribe([0.0] * 7, "de", "") == "small: 7"  # loads again
    assert loads == ["small", "small"]


def test_the_model_can_stay_loaded(monkeypatch, settings):
    monkeypatch.setattr(local, "IDLE_UNLOAD_S", 0.1)
    monkeypatch.setattr(local, "IDLE_CHECK_S", 0.05)
    settings.set("local_unload", "0")
    engine = local.LocalEngine()
    monkeypatch.setattr(engine, "_load_whisper", lambda c, s: fake_whisper(c))
    engine.load("small")
    engine.wait()
    time.sleep(0.4)
    assert engine.state == "ready"


def test_the_model_runs_in_a_process_of_its_own():
    model = local.WorkerModel("tiny", "cpu", "unused", model="fake_model:FakeWhisper")
    try:
        assert model._process.is_alive() and model._process.pid != os.getpid()
        text = model.transcribe(np.zeros(16000, np.float32), "de", "Hello")
        assert text == "16000 samples, de, 'Hello'"
    finally:
        model.close()
    assert not model._process.is_alive()  # its memory is free again


def test_a_failed_load_in_the_process_is_reported():
    with pytest.raises(SttError, match="failed to load") as error:
        local.WorkerModel("broken", "cpu", "unused", model="fake_model:FakeWhisper")
    assert "no such model" in str(error.value)


def test_a_crashed_process_fails_the_transcription():
    model = local.WorkerModel("tiny", "cpu", "unused", model="fake_model:FakeWhisper")
    try:
        with pytest.raises(SttError, match="stopped"):
            model.transcribe(np.zeros(10, np.float32), None, "crash")
    finally:
        model.close()
