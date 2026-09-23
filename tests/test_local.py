import http.server
import json
import os
import threading
import time
import types

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


def fake_whisper(name="small"):
    return types.SimpleNamespace(name=name, device="cpu")


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
