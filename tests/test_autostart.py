import types

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

    def QueryValueEx(self, key, name):
        if name not in self.values:
            raise FileNotFoundError(name)
        return self.values[name], self.REG_SZ

    def SetValueEx(self, key, name, reserved, kind, value):
        self.values[name] = value

    def DeleteValue(self, key, name):
        del self.values[name]


@pytest.fixture
def startup(tmp_path, monkeypatch):
    registry = FakeRegistry()
    monkeypatch.setattr(autostart, "winreg", registry)
    monkeypatch.setattr(autostart, "STARTUP_DIR", str(tmp_path))
    return types.SimpleNamespace(dir=tmp_path, registry=registry)


def shortcut_to(target):
    """Bytes that look like a .lnk file pointing at `target` (UTF-16 path)."""
    return b"L\x00\x00\x00" + target.encode("utf-16-le")


def test_enable_and_disable(startup):
    assert not autostart.is_enabled()
    autostart.set_enabled(True)
    assert autostart.is_enabled()
    command = startup.registry.values["BetterVoice"]
    assert command.endswith(" -m bettervoice") or command.endswith('.exe"')
    autostart.set_enabled(False)
    assert not autostart.is_enabled()
    assert "BetterVoice" not in startup.registry.values


def test_entries_of_older_versions_are_replaced(startup):
    # before the rename: a hand-made shortcut to BetterTalk.exe, or a Run value
    old = startup.dir / "Dictation.lnk"
    old.write_bytes(shortcut_to("C:/apps/dist/BetterTalk.exe"))
    other = startup.dir / "Spotify.lnk"
    other.write_bytes(shortcut_to("C:/Spotify/Spotify.exe"))
    startup.registry.values["BetterTalk"] = '"C:/apps/BetterTalk.exe"'
    assert autostart.is_enabled()
    autostart.set_enabled(True)
    assert not old.exists()  # it would start a second, outdated copy
    assert other.exists()
    assert "BetterTalk" not in startup.registry.values
    assert "BetterVoice" in startup.registry.values


def test_autostart_follows_the_running_copy(startup, monkeypatch):
    monkeypatch.setattr(autostart.sys, "frozen", True, raising=False)
    monkeypatch.setattr(autostart.sys, "executable", r"C:\Programs\BetterVoice\BetterVoice.exe")
    autostart.follow_this_copy()
    assert startup.registry.values == {}  # off stays off
    # on, but for the unzipped copy the user had before installing
    startup.registry.values["BetterVoice"] = r'"C:\Downloads\BetterVoice\BetterVoice.exe"'
    autostart.follow_this_copy()
    assert startup.registry.values == {"BetterVoice": r'"C:\Programs\BetterVoice\BetterVoice.exe"'}
    # on for the predecessor
    startup.registry.values = {"BetterTalk": '"C:/apps/BetterTalk.exe"'}
    autostart.follow_this_copy()
    assert startup.registry.values == {"BetterVoice": r'"C:\Programs\BetterVoice\BetterVoice.exe"'}


def test_a_source_run_leaves_autostart_alone(startup):
    startup.registry.values["BetterVoice"] = r'"C:\Programs\BetterVoice\BetterVoice.exe"'
    autostart.follow_this_copy()
    assert startup.registry.values == {"BetterVoice": r'"C:\Programs\BetterVoice\BetterVoice.exe"'}
