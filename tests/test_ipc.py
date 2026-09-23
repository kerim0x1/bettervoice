"""Commands for the running copy (`bettervoice --toggle` & co.) and one
instance per user."""

import os
import shutil
import subprocess
import sys
import tempfile
import threading

import pytest

from bettervoice import cli, config, ipc
from conftest import ROOT


@pytest.fixture
def runtime(monkeypatch):
    # short: a Unix socket's path must stay under ~100 characters
    folder = tempfile.mkdtemp(prefix="bv-", dir=None if sys.platform == "win32" else "/tmp")
    monkeypatch.setattr(config, "RUNTIME_DIR", folder)
    yield folder
    shutil.rmtree(folder, ignore_errors=True)


@pytest.fixture
def server(runtime):
    received = []
    arrived = threading.Event()

    def handle(command):
        received.append(command)
        arrived.set()

    server = ipc.Server(handle)
    server.start()
    server.received, server.arrived = received, arrived
    yield server
    server.close()


def test_commands_reach_the_running_copy(server):
    assert ipc.send("toggle")
    assert server.arrived.wait(5)
    assert server.received == ["toggle"]


def test_unknown_commands_are_dropped(server):
    assert ipc.send("rm -rf")
    assert ipc.send("settings")
    assert server.arrived.wait(5)
    assert server.received == ["settings"]


def test_nothing_is_running(runtime):
    assert not ipc.send("toggle")


def test_only_the_key_holder_gets_in(server, runtime):
    with open(os.path.join(runtime, "ipc.key"), "wb") as f:
        f.write(b"not the key")
    assert not ipc.send("toggle")
    assert not server.arrived.wait(0.5)


def test_the_command_line_hands_commands_over(server, monkeypatch):
    monkeypatch.setattr("bettervoice.app.run", lambda args: pytest.fail("started the app"))
    cli.main(["--toggle"])
    assert server.arrived.wait(5) and server.received == ["toggle"]


def test_quit_without_a_running_copy_does_nothing(runtime, monkeypatch):
    monkeypatch.setattr("bettervoice.app.run", lambda args: pytest.fail("started the app"))
    cli.main(["--quit"])


def test_toggle_without_a_running_copy_starts_the_app(runtime, monkeypatch):
    started = []
    monkeypatch.setattr("bettervoice.app.run", started.append)
    cli.main(["--toggle"])
    assert started == [["--toggle"]]


@pytest.mark.skipif(sys.platform == "win32", reason="Windows uses a mutex")
def test_one_instance_per_user(runtime, monkeypatch):
    from bettervoice.desktop import posix

    monkeypatch.setattr(posix, "_lock", None)
    assert posix.acquire_single_instance()
    try:
        second = subprocess.run(
            [sys.executable, "-c",
             "import sys; sys.path.insert(0, 'src'); from bettervoice import config; "
             "config.RUNTIME_DIR = sys.argv[1]; from bettervoice.desktop import posix; "
             "print(posix.acquire_single_instance())", runtime],
            cwd=ROOT, capture_output=True, text=True, timeout=30)
        assert second.stdout.strip() == "False", second.stderr
    finally:
        os.close(posix._lock)
