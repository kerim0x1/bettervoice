"""Linux: the hotkey through an X11 key grab, pasting with XTest (or wtype or
ydotool under Wayland), the pill cut to shape with XShape, and a pystray icon.

Wayland lets no app grab keys for itself: there, a shortcut in the desktop's
keyboard settings runs `bettervoice --toggle` instead (see ipc.py). On GNOME
BetterVoice can add that shortcut for the user.
"""

import logging
import os
import select
import shlex
import shutil
import subprocess
import threading
import time

from bettervoice import autostart, brand
from bettervoice.desktop.base import PasteFallback, ui
from bettervoice.desktop.posix import (  # noqa: F401 - part of this module's interface
    acquire_single_instance,
    tell_already_running,
)

log = logging.getLogger(__name__)

NAME = "Linux"
COMPUTER = "computer"
HOTKEY = "Ctrl+Alt+O"
TRAY_ICON = "tray icon"
TRAY_PLACE = "the system tray"
AUTOSTART_LABEL = "Start at login"
DISPLAY_FONT = TEXT_FONT = OVERLAY_FONT = ICON_FONT = None  # the desktop's own font
OVERLAY_FONT_SIZE = 9
OVERLAY_KEY_COLOR = None  # X11 has no see-through color: XShape cuts the pill out

CLIPBOARD_RESTORE_DELAY = 1.0  # s; give the target app time to read the paste
# terminals paste with Ctrl+Shift+V; matched against the window's WM_CLASS
TERMINALS = (
    "alacritty", "blackbox", "cool-retro-term", "foot", "gnome-terminal", "guake",
    "kgx", "kitty", "konsole", "lxterminal", "mate-terminal", "ptyxis", "qterminal",
    "rxvt", "sakura", "st-256color", "terminator", "terminology", "tilda", "tilix",
    "urxvt", "wezterm", "xfce4-terminal", "xterm",
)


def is_wayland():
    return bool(os.environ.get("WAYLAND_DISPLAY")) or (
        os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland")


def is_gnome():
    return "gnome" in os.environ.get("XDG_CURRENT_DESKTOP", "").lower()


def _xlib():
    from Xlib import XK, X, display, error

    return X, XK, display, error


_display = None  # the tk thread's own connection, for shapes and pointer queries


def _tk_display():
    global _display
    if _display is None:
        _display = _xlib()[2].Display()
    return _display


# ---------------------------------------------------------------- process ---


def prepare_process():
    pass


def init_ui(root, on_reopen=None):
    import tkinter as tk

    root.iconphoto(True, tk.PhotoImage(master=root, file=brand.ICON_PNG_PATH))


def set_window_icon(window):
    pass  # every window has the mark since init_ui


def bring_to_front(window):
    window.lift()
    window.focus_force()


def open_path(path):
    subprocess.Popen(["xdg-open", path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


# ------------------------------------------------------------------ access ---


def shortcut_command():
    """The command a desktop shortcut runs to start and stop a dictation."""
    return " ".join(shlex.quote(part) for part in autostart.command() + ["--toggle"])


GNOME_KEYS = "org.gnome.settings-daemon.plugins.media-keys"
GNOME_PATH = f"/{GNOME_KEYS.replace('.', '/')}/custom-keybindings/bettervoice/"


def _gsettings(*args):
    return subprocess.run(["gsettings", *args], capture_output=True, text=True,
                          timeout=5).stdout.strip()


def gnome_shortcut_set():
    """True if BetterVoice's custom shortcut is in GNOME's keyboard settings."""
    try:
        return GNOME_PATH in _gsettings("get", GNOME_KEYS, "custom-keybindings")
    except (OSError, subprocess.SubprocessError):
        return False


def add_gnome_shortcut():
    """Add Ctrl+Alt+O -> `bettervoice --toggle` to GNOME's custom shortcuts."""
    paths = _gsettings("get", GNOME_KEYS, "custom-keybindings")
    entries = [] if paths.startswith("@as") else [
        p.strip().strip("'") for p in paths.strip("[]").split(",") if p.strip()]
    if GNOME_PATH not in entries:
        entries.append(GNOME_PATH)
    schema = f"{GNOME_KEYS}.custom-keybinding:{GNOME_PATH}"
    _gsettings("set", schema, "name", brand.NAME)
    _gsettings("set", schema, "command", shortcut_command())
    _gsettings("set", schema, "binding", "<Control><Alt>o")
    _gsettings("set", GNOME_KEYS, "custom-keybindings", str(entries))


def missing_access():
    """Under Wayland the hotkey needs a desktop shortcut; GNOME's we can check."""
    if not is_wayland() or (is_gnome() and gnome_shortcut_set()):
        return []
    return ["shortcut"]


def request_access():
    if is_wayland() and is_gnome():
        add_gnome_shortcut()


def self_check():
    """python-xlib loads its extensions by name: are they in the build?"""
    from Xlib import XK, X, display, error  # noqa: F401
    from Xlib.ext import shape, xtest  # noqa: F401


# ----------------------------------------------------------------- hotkey ---


class Hotkeys:
    """Ctrl+Alt+O, and Esc during a dictation, grabbed on the X server.

    Under Wayland this only sees keys typed into X11 apps: there the desktop
    shortcut to `bettervoice --toggle` does the job.
    """

    def __init__(self, on_hotkey, on_cancel, on_error):
        self.on_hotkey, self.on_cancel, self.on_error = on_hotkey, on_cancel, on_error
        self._escape_wanted = False
        self._wake_read, self._wake_write = os.pipe()

    def start(self):
        threading.Thread(target=self._run, daemon=True).start()

    def dictating(self, active):
        """Grab Esc while a dictation runs, and only then."""
        self._escape_wanted = active
        os.write(self._wake_write, b"!")

    def _run(self):
        X, XK, xdisplay, xerror = _xlib()
        try:
            d = xdisplay.Display()
        except Exception as e:
            log.error("no X display for the hotkey: %s", e)
            if not is_wayland():
                self.on_error("Hotkey unavailable")
            return
        root = d.screen().root
        key_o = d.keysym_to_keycode(XK.string_to_keysym("o"))
        key_escape = d.keysym_to_keycode(XK.string_to_keysym("Escape"))
        modifiers = X.ControlMask | X.Mod1Mask
        # Caps Lock and Num Lock count as modifiers too: grab with each of them
        locks = (0, X.LockMask, X.Mod2Mask, X.LockMask | X.Mod2Mask)
        taken = xerror.CatchError(xerror.BadAccess)
        for lock in locks:
            root.grab_key(key_o, modifiers | lock, True, X.GrabModeAsync, X.GrabModeAsync,
                          onerror=taken)
        d.sync()
        if taken.get_error():
            log.error("%s is taken by another app", HOTKEY)
            self.on_error(f"{HOTKEY} is taken by another app")
        else:
            log.info("ready: %s to dictate, Esc to cancel", HOTKEY)
        escape_grabbed = False
        last_release = None  # autorepeat repeats a release and a press, at the same time
        while True:
            if escape_grabbed != self._escape_wanted:
                escape_grabbed = self._escape_wanted
                if escape_grabbed:
                    root.grab_key(key_escape, X.AnyModifier, True, X.GrabModeAsync,
                                  X.GrabModeAsync, onerror=xerror.CatchError())
                else:
                    root.ungrab_key(key_escape, X.AnyModifier)
                d.sync()
            if not d.pending_events():
                ready, _, _ = select.select([d.fileno(), self._wake_read], [], [])
                if self._wake_read in ready:
                    os.read(self._wake_read, 64)
            while d.pending_events():
                event = d.next_event()
                if event.type == X.KeyRelease and event.detail == key_o:
                    last_release = event.time
                elif event.type != X.KeyPress:
                    continue
                elif event.detail == key_o and event.state & modifiers == modifiers:
                    if event.time != last_release:
                        self.on_hotkey()
                elif event.detail == key_escape:
                    self.on_cancel()


# ------------------------------------------------------------------ paste ---


def _held_modifiers(d):
    """Ctrl, Alt, Shift or Super still pressed (e.g. from the hotkey)."""
    XK = _xlib()[1]
    pressed = d.query_keymap()
    for name in ("Control_L", "Control_R", "Alt_L", "Alt_R", "Shift_L", "Shift_R",
                 "Super_L", "Super_R", "Meta_L", "Meta_R"):
        code = d.keysym_to_keycode(XK.string_to_keysym(name))
        if code and pressed[code // 8] & (1 << (code % 8)):
            return True
    return False


def _active_window_class(d):
    """WM_CLASS of the focused X11 window, lowercased; None if none is focused
    (under Wayland: a Wayland app has the focus)."""
    X = _xlib()[0]
    root = d.screen().root
    active = root.get_full_property(d.intern_atom("_NET_ACTIVE_WINDOW"), X.AnyPropertyType)
    if not active or not active.value or not active.value[0]:
        return None
    try:
        names = d.create_resource_object("window", active.value[0]).get_wm_class()
    except Exception:
        return ""
    return " ".join(names or ()).lower()


def is_terminal(window_class):
    return any(name in (window_class or "").split() for name in TERMINALS) or any(
        name in (window_class or "") for name in ("terminal", "konsole"))


def _xtest_paste(d, shift):
    X, XK = _xlib()[:2]
    from Xlib.ext import xtest

    keys = [d.keysym_to_keycode(XK.string_to_keysym("Control_L"))]
    if shift:
        keys.append(d.keysym_to_keycode(XK.string_to_keysym("Shift_L")))
    keys.append(d.keysym_to_keycode(XK.string_to_keysym("v")))
    for key in keys:
        xtest.fake_input(d, X.KeyPress, key)
    d.sync()
    time.sleep(0.02)
    for key in reversed(keys):
        xtest.fake_input(d, X.KeyRelease, key)
    d.sync()


def _run_tool(args):
    try:
        return subprocess.run(args, capture_output=True, timeout=3).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def _wayland_paste():
    """Ctrl+V through a Wayland input tool, if one is installed and works."""
    if shutil.which("wtype") and _run_tool(["wtype", "-M", "ctrl", "v", "-m", "ctrl"]):
        return True
    # ydotool needs its daemon; 29 = left Ctrl, 47 = V
    return bool(shutil.which("ydotool")) and _run_tool(
        ["ydotool", "key", "29:1", "47:1", "47:0", "29:0"])


def _clipboard_get():
    try:
        return ui.root.clipboard_get()
    except Exception:  # empty, or not text
        return None


def _clipboard_set(text):
    ui.root.clipboard_clear()
    ui.root.clipboard_append(text)


def paste(text):
    """Put the text on the clipboard and send the paste shortcut to the
    focused app; restore the previous clipboard text afterwards.

    Raises PasteFallback when no way to type into the focused app is left
    (a Wayland app, without wtype or ydotool): the text stays on the clipboard.
    """
    previous = ui.call(_clipboard_get)
    ui.call(lambda: _clipboard_set(text))
    d = _xlib()[2].Display()
    try:
        deadline = time.time() + 2
        while _held_modifiers(d) and time.time() < deadline:
            time.sleep(0.02)
        time.sleep(0.05)
        window_class = _active_window_class(d)
        if window_class is None and is_wayland():
            if not _wayland_paste():
                raise PasteFallback("Copied – press Ctrl+V to paste")
        else:
            _xtest_paste(d, shift=is_terminal(window_class))
    finally:
        d.close()
    if previous:
        ui.call(lambda: ui.root.after(int(CLIPBOARD_RESTORE_DELAY * 1000),
                                      lambda: _clipboard_set(previous)))


# ---------------------------------------------------------------- overlay ---


def prepare_overlay(win):
    pass  # override-redirect windows never take the focus on X11


def shape_overlay(win, width, height):
    """Cut the window to the pill's rounded shape (called on every resize)."""
    try:
        from Xlib.ext import shape

        d = _tk_display()
        if not d.has_extension("SHAPE") or width < height:
            return
        inner = d.create_resource_object("window", win.winfo_id())
        # tk wraps every toplevel in a window of its own: that one is on screen
        wrapper = inner.query_tree().parent
        mask = inner.create_pixmap(width, height, 1)
        gc = mask.create_gc(foreground=0, background=0)
        mask.fill_rectangle(gc, 0, 0, width, height)
        gc.change(foreground=1)
        mask.fill_arc(gc, 0, 0, height, height, 0, 360 * 64)
        mask.fill_arc(gc, width - height, 0, height, height, 0, 360 * 64)
        mask.fill_rectangle(gc, height // 2, 0, width - height, height)
        for window in (inner, wrapper):
            if window.id != d.screen().root.id:
                window.shape_mask(shape.SO.Set, shape.SK.Bounding, 0, 0, mask)
        gc.free()
        mask.free()
        d.flush()
    except Exception:
        log.debug("could not shape the overlay", exc_info=True)


def overlay_shown(win):
    pass


def overlay_anchor(root, width, height):
    """Next to the mouse pointer. Under Wayland the X server doesn't know
    where the pointer is: the pill sits at the bottom of the screen there."""
    if is_wayland():
        return (root.winfo_screenwidth() - width) // 2, root.winfo_screenheight() - height - 96
    x, y = root.winfo_pointerxy()
    return x + 12, y + 18


def _work_area(root):
    try:
        X = _xlib()[0]
        d = _tk_display()
        area = d.screen().root.get_full_property(d.intern_atom("_NET_WORKAREA"),
                                                 X.AnyPropertyType)
        if area and len(area.value) >= 4:
            left, top, width, height = area.value[:4]
            return left, top, left + width, top + height
    except Exception:
        pass
    return 0, 0, root.winfo_screenwidth(), root.winfo_screenheight()


def clamp_to_work_area(root, x, y, w, h):
    left, top, right, bottom = _work_area(root)
    return max(left + 4, min(x, right - w - 4)), max(top + 4, min(y, bottom - h - 4))


# ------------------------------------------------------------------- tray ---


def _latin1(text):
    return text.replace("–", "-").encode("latin-1", "replace").decode("latin-1")


def make_tray(name, title, menu):
    import pystray  # connects to the X server as it loads

    class TrayIcon(pystray.Icon):
        """pystray's X11 backend names its window in Latin-1 only."""

        def __init__(self, name, icon, title, menu):
            super().__init__(name, icon, _latin1(title), menu)

        title = property(pystray.Icon.title.fget,
                         lambda self, value: pystray.Icon.title.fset(self, _latin1(value)))

    return TrayIcon(name, brand.draw_mark(64), title, menu)


class _NoDockTraceback(logging.Filter):
    def filter(self, record):
        return record.getMessage() != "Failed to dock icon"


def run_tray(icon):
    """Without a system tray (GNOME needs an extension for it) the icon has
    nowhere to go: say so once, instead of pystray's tracebacks."""
    logging.getLogger("pystray._base").addFilter(_NoDockTraceback())
    threading.Thread(target=icon.run, daemon=True).start()

    def check():
        time.sleep(3)
        if hasattr(icon, "_systray_manager") and not icon._systray_manager:
            log.warning("no system tray: open %s from the app menu for its settings",
                        brand.NAME)

    threading.Thread(target=check, daemon=True).start()


def stop_tray(icon):
    icon.stop()
