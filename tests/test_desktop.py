"""The system layer: the key filter every backend shares, the way to the UI
thread, and the parts of the system the tests run on."""

import ctypes
import os
import queue
import shutil
import subprocess
import sys
import threading
import time
import tkinter as tk
import types

import pytest

from bettervoice.desktop import base

HOTKEY, ESCAPE, OTHER = "o", "esc", "a"
linux = pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux only")
macos = pytest.mark.skipif(sys.platform != "darwin", reason="macOS only")
windows = pytest.mark.skipif(sys.platform != "win32", reason="Windows only")


class Calls:
    """Stands in for app.on_hotkey and app.cancel."""

    def __init__(self, dictating=False):
        self.hotkeys = 0
        self.cancels = 0
        self.dictating = dictating

    def hotkey(self):
        self.hotkeys += 1

    def cancel(self):
        self.cancels += 1
        return self.dictating


# ------------------------------------------------------------ key filter ---


def test_hotkey_is_swallowed_with_its_release_and_autorepeat():
    calls = Calls()
    keys = base.KeyFilter(HOTKEY, ESCAPE, calls.hotkey, calls.cancel)
    assert keys.feed(HOTKEY, True, True)
    assert keys.feed(HOTKEY, True, True)  # autorepeat: swallowed, not a second press
    assert keys.feed(HOTKEY, False, False)  # the release, even with the modifiers up
    assert calls.hotkeys == 1
    # without the modifiers it's just a key for the focused app
    assert not keys.feed(HOTKEY, True, False)
    assert not keys.feed(HOTKEY, False, False)
    assert keys.feed(HOTKEY, True, True) and calls.hotkeys == 2


def test_escape_is_ours_only_during_a_dictation():
    calls = Calls(dictating=False)
    keys = base.KeyFilter(HOTKEY, ESCAPE, calls.hotkey, calls.cancel)
    assert not keys.feed(ESCAPE, True, False) and not keys.feed(ESCAPE, False, False)
    calls.dictating = True
    assert keys.feed(ESCAPE, True, False)  # cancels the dictation
    assert keys.feed(ESCAPE, False, False)  # and its release is ours too
    assert calls.cancels == 2
    assert not keys.feed(OTHER, True, False) and not keys.feed(OTHER, False, False)


def test_before_hotkey_runs_first():
    order = []
    keys = base.KeyFilter(HOTKEY, ESCAPE, lambda: order.append("hotkey"), lambda: False,
                          before_hotkey=lambda: order.append("before"))
    keys.feed(HOTKEY, True, True)
    assert order == ["before", "hotkey"]


# -------------------------------------------------------------- UI thread ---


def test_ui_call_runs_on_the_ui_thread():
    ui = base.Ui()
    assert ui.call(lambda: 42) == 42  # nothing attached yet: runs right away
    posted = queue.Queue()
    ui.attach(None, posted.put)
    result = {}

    def worker():
        try:
            result["thread"] = ui.call(lambda: threading.current_thread().name)
            ui.call(lambda: 1 / 0)
        except ZeroDivisionError:
            result["error"] = True

    thread = threading.Thread(target=worker)
    thread.start()
    for _ in range(2):
        posted.get(timeout=5)()  # the "tk thread" (here the main thread) runs it
    thread.join(5)
    assert result == {"thread": threading.main_thread().name, "error": True}


# ---------------------------------------------------------------- Windows ---


@windows
def test_windows_keyboard_hook(monkeypatch):
    from bettervoice.desktop import windows as win

    monkeypatch.setattr(win, "user32", types.SimpleNamespace(keybd_event=lambda *a: None,
                                                             CallNextHookEx=lambda *a: 0))
    monkeypatch.setattr(win, "win_is_down", lambda: True)
    calls = Calls()
    hooks = win.Hotkeys(calls.hotkey, calls.cancel, on_error=print)

    def key(vk, down):
        info = win.KBDLLHOOKSTRUCT(vkCode=vk)
        message = win.WM_KEYDOWN if down else win.WM_KEYUP
        return hooks._callback(0, message, ctypes.addressof(info))

    # Win+O: swallowed down and up, autorepeat doesn't trigger again
    assert key(win.VK_O, True) == 1 and key(win.VK_O, True) == 1
    assert key(win.VK_O, False) == 1
    assert calls.hotkeys == 1
    # Esc with nothing running goes to the focused app
    assert key(win.VK_ESCAPE, True) == 0 and key(win.VK_ESCAPE, False) == 0
    # Esc during a dictation is ours, including its key-up
    calls.dictating = True
    assert key(win.VK_ESCAPE, True) == 1 and key(win.VK_ESCAPE, False) == 1
    # other keys pass through
    assert key(0x41, True) == 0


# ------------------------------------------------------------------ Linux ---


@linux
def test_terminals_paste_with_shift():
    from bettervoice.desktop import linux as lx

    assert lx.is_terminal("gnome-terminal-server gnome-terminal-server")
    assert lx.is_terminal("kitty kitty") and lx.is_terminal("org.kde.konsole konsole")
    assert not lx.is_terminal("navigator firefox") and not lx.is_terminal(None)


@linux
def test_wayland_is_detected(monkeypatch):
    from bettervoice.desktop import linux as lx

    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    monkeypatch.setenv("XDG_SESSION_TYPE", "x11")
    assert not lx.is_wayland() and lx.missing_access() == []
    monkeypatch.setenv("XDG_SESSION_TYPE", "wayland")
    monkeypatch.setenv("XDG_CURRENT_DESKTOP", "KDE")
    assert lx.is_wayland() and lx.missing_access() == ["shortcut"]


@linux
def test_gnome_shortcut_is_added(monkeypatch):
    from bettervoice.desktop import linux as lx

    stored = {"custom-keybindings": "@as []"}

    def gsettings(*args):
        if args[0] == "get":
            return stored.get(args[2], "")
        stored[args[2]] = args[3]
        return ""

    monkeypatch.setattr(lx, "_gsettings", gsettings)
    assert not lx.gnome_shortcut_set()
    lx.add_gnome_shortcut()
    assert stored["custom-keybindings"] == str([lx.GNOME_PATH])
    assert stored["binding"] == "<Control><Alt>o"
    assert stored["command"].endswith("--toggle")
    assert lx.gnome_shortcut_set()
    stored["custom-keybindings"] = "['/org/gnome/custom0/']"  # keeps the user's own ones
    lx.add_gnome_shortcut()
    assert stored["custom-keybindings"] == str(["/org/gnome/custom0/", lx.GNOME_PATH])


def x_server():
    """An X server to talk to (xvfb-run in CI), with xdotool to press keys."""
    if not sys.platform.startswith("linux") or not os.environ.get("DISPLAY"):
        pytest.skip("no X display")
    if not shutil.which("xdotool"):
        pytest.skip("xdotool is not installed")


def wait_until(condition, timeout=5):
    deadline = time.monotonic() + timeout
    while not condition() and time.monotonic() < deadline:
        time.sleep(0.02)
    return condition()


@linux
def test_x11_hotkey_and_escape_grabs(monkeypatch):
    x_server()
    from bettervoice.desktop import linux as lx

    calls = Calls(dictating=True)
    errors = []
    hooks = lx.Hotkeys(calls.hotkey, calls.cancel, errors.append)
    hooks.start()
    time.sleep(0.5)  # the grab is in place
    subprocess.run(["xdotool", "key", "ctrl+alt+o"], check=True)
    assert wait_until(lambda: calls.hotkeys == 1), errors
    subprocess.run(["xdotool", "key", "Escape"], check=True)
    time.sleep(0.3)
    assert calls.cancels == 0  # not dictating: Esc isn't grabbed
    hooks.dictating(True)
    time.sleep(0.3)
    subprocess.run(["xdotool", "key", "Escape"], check=True)
    assert wait_until(lambda: calls.cancels == 1)
    hooks.dictating(False)
    assert errors == []


@linux
def test_x11_paste_types_into_the_focused_field(monkeypatch):
    x_server()
    from bettervoice.desktop import linux as lx

    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    monkeypatch.setenv("XDG_SESSION_TYPE", "x11")
    root = tk.Tk()
    try:
        entry = tk.Entry(root)
        entry.pack()
        root.update()
        entry.focus_force()
        root.update()
        posted = queue.Queue()
        monkeypatch.setattr(lx, "ui", base.Ui())
        lx.ui.attach(root, posted.put)
        root.clipboard_clear()
        root.clipboard_append("what was there before")
        done, errors = threading.Event(), []

        def worker():
            try:
                lx.paste("Hello from BetterVoice")
            except Exception as e:
                errors.append(e)
            finally:
                done.set()

        threading.Thread(target=worker, daemon=True).start()
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and not (done.is_set() and entry.get()):
            while not posted.empty():
                posted.get()()
            root.update()
            time.sleep(0.01)
        assert not errors and entry.get() == "Hello from BetterVoice"
        # a second later the clipboard holds the previous text again
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline and root.clipboard_get() != "what was there before":
            root.update()
            time.sleep(0.02)
        assert root.clipboard_get() == "what was there before"
    finally:
        root.destroy()


# ------------------------------------------------------------------ macOS ---


@macos
def test_macos_event_tap_callback():
    import Quartz

    from bettervoice.desktop import macos as mac

    calls = Calls(dictating=True)
    hooks = mac.Hotkeys(calls.hotkey, calls.cancel, on_error=print)

    def key(code, down, flags=0):
        event = Quartz.CGEventCreateKeyboardEvent(None, code, down)
        Quartz.CGEventSetFlags(event, flags)
        kind = Quartz.kCGEventKeyDown if down else Quartz.kCGEventKeyUp
        return hooks._callback(None, kind, event, None)

    control_option = Quartz.kCGEventFlagMaskControl | Quartz.kCGEventFlagMaskAlternate
    assert key(mac.KEY_O, True, control_option) is None  # ⌃⌥O: swallowed
    assert key(mac.KEY_O, False) is None  # and its release
    assert calls.hotkeys == 1
    assert key(mac.KEY_O, True, Quartz.kCGEventFlagMaskCommand) is not None  # ⌘O: the app's
    assert key(mac.KEY_ESCAPE, True) is None and calls.cancels == 1


@macos
def test_macos_hotkey_and_paste_for_real():
    """With the Accessibility permission (GitHub's macOS runners have it): the
    event tap sees a posted ⌃⌥O, and ⌘V types into a text field."""
    import Quartz

    from bettervoice.desktop import macos as mac

    if not mac.is_trusted():
        pytest.skip("needs the Accessibility permission")
    calls = Calls()
    errors = []
    hooks = mac.Hotkeys(calls.hotkey, calls.cancel, errors.append)
    hooks.start()
    time.sleep(0.5)
    control_option = Quartz.kCGEventFlagMaskControl | Quartz.kCGEventFlagMaskAlternate
    for down in (True, False):
        event = Quartz.CGEventCreateKeyboardEvent(None, mac.KEY_O, down)
        Quartz.CGEventSetFlags(event, control_option)
        Quartz.CGEventPost(Quartz.kCGHIDEventTap, event)
    assert wait_until(lambda: calls.hotkeys == 1), errors

    root = tk.Tk()
    try:
        entry = tk.Entry(root)
        entry.pack()
        root.update()
        mac.bring_to_front(root)
        entry.focus_force()
        root.update()
        done = threading.Event()

        def worker():
            try:
                mac.paste("Hello from BetterVoice")
            finally:
                done.set()

        threading.Thread(target=worker, daemon=True).start()
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and not (done.is_set() and entry.get()):
            root.update()
            time.sleep(0.01)
        assert entry.get() == "Hello from BetterVoice"
    finally:
        root.destroy()


@macos
def test_macos_overlay_placement():
    from bettervoice.desktop import macos as mac

    root = tk.Tk()
    try:
        x, y = mac.overlay_anchor(root, 176, 40)
        left, top = mac.clamp_to_work_area(root, x, y, 176, 40)
        assert isinstance(left, int) and isinstance(top, int)
    finally:
        root.destroy()
