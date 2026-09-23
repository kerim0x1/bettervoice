"""Start BetterVoice when the user signs in: the Run key on Windows, a
LaunchAgent on macOS, an XDG autostart entry on Linux."""

import glob
import logging
import os
import plistlib
import sys

from bettervoice import brand

if sys.platform == "win32":
    import winreg
else:
    winreg = None  # tests of the Windows backend bring a fake registry

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
LAUNCH_AGENT = "com.kerim0x1.bettervoice"


def command():
    """What starts this copy of BetterVoice: the app, or Python with the package."""
    if getattr(sys, "frozen", False):
        return [sys.executable]
    python = sys.executable
    if sys.platform == "win32":  # no console window
        pythonw = os.path.join(os.path.dirname(python), "pythonw.exe")
        if os.path.exists(pythonw):
            python = pythonw
    return [python, "-m", "bettervoice"]


class RunKey:
    """Windows: the per-user Run key, and the entries of the predecessor."""

    def __init__(self, registry, startup_dir):
        self.registry = registry
        self.startup_dir = startup_dir

    @staticmethod
    def line(args):
        """The program quoted, then its arguments: as the installer writes it."""
        return " ".join([f'"{args[0]}"', *args[1:]])

    def _value(self, name):
        try:
            with self.registry.OpenKey(self.registry.HKEY_CURRENT_USER, RUN_KEY) as key:
                return self.registry.QueryValueEx(key, name)[0]
        except OSError:
            return None

    def _legacy_shortcuts(self):
        found = []
        for path in glob.glob(os.path.join(self.startup_dir, "*.lnk")):
            try:
                with open(path, "rb") as f:
                    data = f.read().lower()
            except OSError:
                continue
            # .lnk files store the target path as ANSI and/or UTF-16 text
            if any(name.encode() in data or name.encode("utf-16-le") in data
                   for name in _OUR_FILES):
                found.append(path)
        return found

    def _legacy(self):
        return self._legacy_shortcuts() + [
            name for name in LEGACY_VALUE_NAMES if self._value(name) is not None]

    def is_enabled(self):
        return self._value(VALUE_NAME) is not None or bool(self._legacy())

    def up_to_date(self):
        return self._value(VALUE_NAME) == self.line(command()) and not self._legacy()

    def set_enabled(self, enabled):
        """Turn autostart on or off; old entries of earlier versions are removed."""
        for path in self._legacy_shortcuts():
            try:
                os.remove(path)
                log.info("removed old autostart shortcut %s", path)
            except OSError as e:
                log.warning("could not remove %s: %s", path, e)
        reg = self.registry
        # created if missing: a fresh Windows profile may have no Run key yet
        with reg.CreateKeyEx(reg.HKEY_CURRENT_USER, RUN_KEY, 0, reg.KEY_SET_VALUE) as key:
            for name in LEGACY_VALUE_NAMES:
                if self._value(name) is not None:
                    reg.DeleteValue(key, name)
            if enabled:
                reg.SetValueEx(key, VALUE_NAME, 0, reg.REG_SZ, self.line(command()))
            elif self._value(VALUE_NAME) is not None:
                reg.DeleteValue(key, VALUE_NAME)


class LaunchAgent:
    """macOS: a LaunchAgent that starts BetterVoice at login."""

    def __init__(self, folder):
        self.path = os.path.join(folder, f"{LAUNCH_AGENT}.plist")

    def _arguments(self):
        try:
            with open(self.path, "rb") as f:
                return plistlib.load(f).get("ProgramArguments")
        except (OSError, plistlib.InvalidFileException):
            return None

    def is_enabled(self):
        return os.path.exists(self.path)

    def up_to_date(self):
        return self._arguments() == command()

    def set_enabled(self, enabled):
        if not enabled:
            if os.path.exists(self.path):
                os.remove(self.path)
            return
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, "wb") as f:
            plistlib.dump({"Label": LAUNCH_AGENT, "ProgramArguments": command(),
                           "RunAtLoad": True, "ProcessType": "Interactive"}, f)


class XdgAutostart:
    """Linux: an entry in the XDG autostart folder, which every desktop reads."""

    def __init__(self, folder):
        self.path = os.path.join(folder, "bettervoice.desktop")

    @staticmethod
    def exec_line(args):
        """Quoted and escaped as the Desktop Entry Specification asks."""
        parts = []
        for arg in args:
            arg = arg.replace("%", "%%")
            if any(c in arg for c in " \t\n\"'\\><~|&;$*?#()`"):
                arg = '"' + "".join("\\" + c if c in '"`$\\' else c for c in arg) + '"'
            parts.append(arg)
        return " ".join(parts).replace("\\", "\\\\")

    def _exec(self):
        try:
            with open(self.path, encoding="utf-8") as f:
                for line in f:
                    if line.startswith("Exec="):
                        return line[len("Exec="):].rstrip("\n")
        except OSError:
            pass
        return None

    def is_enabled(self):
        return os.path.exists(self.path)

    def up_to_date(self):
        return self._exec() == self.exec_line(command())

    def set_enabled(self, enabled):
        if not enabled:
            if os.path.exists(self.path):
                os.remove(self.path)
            return
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as f:
            f.write("[Desktop Entry]\n"
                    "Type=Application\n"
                    f"Name={brand.NAME}\n"
                    f"Comment={brand.TAGLINE}\n"
                    f"Exec={self.exec_line(command())}\n"
                    f"Icon={brand.ICON_PNG_PATH}\n"
                    "Terminal=false\n"
                    "X-GNOME-Autostart-enabled=true\n")


def backend():
    if sys.platform == "win32":
        return RunKey(winreg, STARTUP_DIR)
    if sys.platform == "darwin":
        return LaunchAgent(os.path.expanduser("~/Library/LaunchAgents"))
    config_home = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return XdgAutostart(os.path.join(config_home, "autostart"))


def is_enabled():
    return backend().is_enabled()


def set_enabled(enabled):
    backend().set_enabled(enabled)


def follow_this_copy():
    """Point an enabled autostart at the running app.

    After a move to another copy – from the zip to the installer, or from
    BetterTalk – the system would otherwise keep starting the old one. Only
    the packaged app does this; a source run never redirects autostart.
    """
    if not getattr(sys, "frozen", False):
        return
    entry = backend()
    if entry.is_enabled() and not entry.up_to_date():
        entry.set_enabled(True)
        log.info("autostart now starts %s", command()[0])
