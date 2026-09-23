"""Start BetterVoice with Windows, via the per-user Run key."""

import glob
import logging
import os
import sys
import winreg

from bettervoice import brand

log = logging.getLogger(__name__)

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = brand.NAME
LEGACY_VALUE_NAMES = ("BetterTalk",)  # the app's name before the rename
STARTUP_DIR = os.path.join(
    os.environ.get("APPDATA", ""), "Microsoft", "Windows", "Start Menu", "Programs", "Startup"
)
# shortcuts to these, set up by hand for older versions, would start a
# second (possibly outdated) copy next to the Run key entry
_OUR_FILES = ("bettervoice.exe", "bettertalk.exe", "dictate.py", "start-dictation.vbs")


def command():
    """What Windows runs at login: the exe, or pythonw with the package."""
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'
    pythonw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    if not os.path.exists(pythonw):
        pythonw = sys.executable
    return f'"{pythonw}" -m bettervoice'


def _legacy_shortcuts():
    found = []
    for path in glob.glob(os.path.join(STARTUP_DIR, "*.lnk")):
        try:
            with open(path, "rb") as f:
                data = f.read().lower()
        except OSError:
            continue
        # .lnk files store the target path as ANSI and/or UTF-16 text
        if any(name.encode() in data or name.encode("utf-16-le") in data for name in _OUR_FILES):
            found.append(path)
    return found


def _run_value(name):
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            return winreg.QueryValueEx(key, name)[0]
    except OSError:
        return None


def is_enabled():
    return _run_value(VALUE_NAME) is not None or bool(_legacy_shortcuts())


def follow_this_copy():
    """Point an enabled autostart at the running app.

    After a move to another copy – from the zip to the installer, or from
    BetterTalk – Windows would otherwise keep starting the old one. Only the
    packaged app does this; a source run never redirects autostart.
    """
    if not getattr(sys, "frozen", False):
        return
    current = _run_value(VALUE_NAME)
    legacy = _legacy_shortcuts() + [n for n in LEGACY_VALUE_NAMES if _run_value(n) is not None]
    if (current is not None or legacy) and (current != command() or legacy):
        set_enabled(True)
        log.info("autostart now starts %s", command())


def set_enabled(enabled):
    """Turn autostart on or off; old entries of earlier versions are removed."""
    for path in _legacy_shortcuts():
        try:
            os.remove(path)
            log.info("removed old autostart shortcut %s", path)
        except OSError as e:
            log.warning("could not remove %s: %s", path, e)
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
        for name in LEGACY_VALUE_NAMES:
            if _run_value(name) is not None:
                winreg.DeleteValue(key, name)
        if enabled:
            winreg.SetValueEx(key, VALUE_NAME, 0, winreg.REG_SZ, command())
        elif _run_value(VALUE_NAME) is not None:
            winreg.DeleteValue(key, VALUE_NAME)
