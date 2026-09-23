"""Autostart on all three systems, each tested with a fake registry or a
temporary folder, so every test runs everywhere."""

import plistlib
import sys

import pytest

from bettervoice import autostart


class FakeRegistry:
    HKEY_CURRENT_USER, KEY_SET_VALUE, REG_SZ = object(), 2, 1

    def __init__(self):
        self.values = {}

    def OpenKey(self, *args):
        registry = self

        class Key:
            def __enter__(self):
                return registry

            def __exit__(self, *exc):
                return False

        return Key()

    CreateKeyEx = OpenKey

    def QueryValueEx(self, key, name):
        if name not in self.values:
            raise FileNotFoundError(name)
        return self.values[name], self.REG_SZ

    def SetValueEx(self, key, name, reserved, kind, value):
        self.values[name] = value

    def DeleteValue(self, key, name):
        del self.values[name]


@pytest.fixture
def run_key(tmp_path):
    return autostart.RunKey(FakeRegistry(), str(tmp_path))


@pytest.fixture
def frozen(monkeypatch):
    """Run as the packaged app, installed at `path`."""

    def install(path):
        monkeypatch.setattr(autostart.sys, "frozen", True, raising=False)
        monkeypatch.setattr(autostart.sys, "executable", path)

    return install


def shortcut_to(target):
    """Bytes that look like a .lnk file pointing at `target` (UTF-16 path)."""
    return b"L\x00\x00\x00" + target.encode("utf-16-le")


# ---------------------------------------------------------------- Windows ---


def test_run_key_on_and_off(run_key):
    assert not run_key.is_enabled()
    run_key.set_enabled(True)
    assert run_key.is_enabled()
    value = run_key.registry.values["BetterVoice"]
    assert value.startswith('"') and (value.endswith(" -m bettervoice") or value.endswith('"'))
    run_key.set_enabled(False)
    assert not run_key.is_enabled()
    assert "BetterVoice" not in run_key.registry.values


def test_run_key_replaces_entries_of_older_versions(run_key, tmp_path):
    # before the rename: a hand-made shortcut to BetterTalk.exe, or a Run value
    old = tmp_path / "Dictation.lnk"
    old.write_bytes(shortcut_to("C:/apps/dist/BetterTalk.exe"))
    other = tmp_path / "Spotify.lnk"
    other.write_bytes(shortcut_to("C:/Spotify/Spotify.exe"))
    run_key.registry.values["BetterTalk"] = '"C:/apps/BetterTalk.exe"'
    assert run_key.is_enabled()
    run_key.set_enabled(True)
    assert not old.exists()  # it would start a second, outdated copy
    assert other.exists()
    assert "BetterTalk" not in run_key.registry.values
    assert "BetterVoice" in run_key.registry.values


def test_run_key_follows_the_running_copy(run_key, frozen, monkeypatch):
    monkeypatch.setattr(autostart, "backend", lambda: run_key)
    frozen(r"C:\Programs\BetterVoice\BetterVoice.exe")
    autostart.follow_this_copy()
    assert run_key.registry.values == {}  # off stays off
    # on, but for the unzipped copy the user had before installing
    run_key.registry.values["BetterVoice"] = r'"C:\Downloads\BetterVoice\BetterVoice.exe"'
    autostart.follow_this_copy()
    assert run_key.registry.values == {
        "BetterVoice": r'"C:\Programs\BetterVoice\BetterVoice.exe"'}
    # on for the predecessor
    run_key.registry.values = {"BetterTalk": '"C:/apps/BetterTalk.exe"'}
    autostart.follow_this_copy()
    assert run_key.registry.values == {
        "BetterVoice": r'"C:\Programs\BetterVoice\BetterVoice.exe"'}


def test_a_source_run_leaves_autostart_alone(run_key, monkeypatch):
    monkeypatch.setattr(autostart, "backend", lambda: run_key)
    run_key.registry.values["BetterVoice"] = r'"C:\Programs\BetterVoice\BetterVoice.exe"'
    autostart.follow_this_copy()
    assert run_key.registry.values == {
        "BetterVoice": r'"C:\Programs\BetterVoice\BetterVoice.exe"'}


# ------------------------------------------------------------------ macOS ---


def test_launch_agent(tmp_path, frozen, monkeypatch):
    agent = autostart.LaunchAgent(str(tmp_path / "LaunchAgents"))
    assert not agent.is_enabled()
    agent.set_enabled(True)
    with open(agent.path, "rb") as f:
        plist = plistlib.load(f)
    assert plist["Label"] == "com.kerim0x1.bettervoice" and plist["RunAtLoad"]
    assert plist["ProgramArguments"] == [sys.executable, "-m", "bettervoice"] or \
        plist["ProgramArguments"][1:] == ["-m", "bettervoice"]
    assert agent.up_to_date()
    # the app moved to /Applications: autostart follows it there
    monkeypatch.setattr(autostart, "backend", lambda: agent)
    frozen("/Applications/BetterVoice.app/Contents/MacOS/BetterVoice")
    assert not agent.up_to_date()
    autostart.follow_this_copy()
    with open(agent.path, "rb") as f:
        assert plistlib.load(f)["ProgramArguments"] == [
            "/Applications/BetterVoice.app/Contents/MacOS/BetterVoice"]
    agent.set_enabled(False)
    assert not agent.is_enabled()


# ------------------------------------------------------------------ Linux ---


def test_xdg_autostart(tmp_path, frozen, monkeypatch):
    entry = autostart.XdgAutostart(str(tmp_path / "autostart"))
    assert not entry.is_enabled()
    monkeypatch.setattr(autostart, "backend", lambda: entry)
    frozen("/home/ana/Apps/Better Voice/bettervoice")
    autostart.set_enabled(True)
    text = (tmp_path / "autostart" / "bettervoice.desktop").read_text(encoding="utf-8")
    assert text.startswith("[Desktop Entry]\n")
    assert 'Exec="/home/ana/Apps/Better Voice/bettervoice"\n' in text
    assert autostart.is_enabled() and entry.up_to_date()
    frozen("/opt/bettervoice/bettervoice")
    autostart.follow_this_copy()
    assert "Exec=/opt/bettervoice/bettervoice\n" in (
        tmp_path / "autostart" / "bettervoice.desktop").read_text(encoding="utf-8")
    autostart.set_enabled(False)
    assert not entry.is_enabled()


def test_desktop_entry_quoting():
    line = autostart.XdgAutostart.exec_line
    assert line(["/usr/bin/python3", "-m", "bettervoice"]) == "/usr/bin/python3 -m bettervoice"
    assert line(["/a b/run"]) == '"/a b/run"'
    assert line(['/a"b/$x']) == '"/a\\\\"b/\\\\$x"'  # escaped, then escaped as a string
    assert line(["/100%/run"]) == "/100%%/run"
