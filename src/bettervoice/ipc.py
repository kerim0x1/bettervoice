"""Commands for the running BetterVoice from a second start:

    bettervoice --toggle     start or stop a dictation (the hotkey)
    bettervoice --cancel     cancel it (Esc)
    bettervoice --settings   open the settings
    bettervoice --quit       quit

Under Wayland a desktop shortcut to `--toggle` is the hotkey. The channel is
a Unix socket (a named pipe on Windows) that only this user can reach, with a
random key the running copy writes to its data folder. Messages are plain
command names: nothing received is ever unpickled.
"""

import hashlib
import logging
import os
import secrets
import sys
import threading
from multiprocessing.connection import AuthenticationError, Client, Listener

from bettervoice import config

log = logging.getLogger(__name__)

COMMANDS = ("toggle", "cancel", "settings", "quit")


def address():
    if sys.platform == "win32":
        # one pipe per user and data folder (tests use their own folder)
        suffix = hashlib.sha256(config.RUNTIME_DIR.lower().encode()).hexdigest()[:16]
        return rf"\\.\pipe\BetterVoice-{suffix}"
    return os.path.join(config.RUNTIME_DIR, "bettervoice.sock")


def _family():
    return "AF_PIPE" if sys.platform == "win32" else "AF_UNIX"


def _key_path():
    return os.path.join(config.RUNTIME_DIR, "ipc.key")


def send(command):
    """Hand a command to the running BetterVoice; False if none is running."""
    try:
        with open(_key_path(), "rb") as f:
            key = f.read()
        with Client(address(), family=_family(), authkey=key) as conn:
            conn.send_bytes(command.encode())
        return True
    except (OSError, EOFError, AuthenticationError):
        return False


class Server:
    """Receives commands on its own thread and hands them to handle(command)."""

    def __init__(self, handle):
        self.handle = handle
        self.listener = None
        self.closed = False

    def start(self):
        os.makedirs(config.RUNTIME_DIR, mode=0o700, exist_ok=True)
        key = secrets.token_bytes(32)
        fd = os.open(_key_path(), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(key)
        if sys.platform != "win32" and os.path.exists(address()):
            os.unlink(address())  # left by a crash: this process holds the instance lock
        self.listener = Listener(address(), family=_family(), authkey=key)
        threading.Thread(target=self._serve, daemon=True).start()

    def _serve(self):
        while not self.closed:
            try:
                with self.listener.accept() as conn:
                    if not conn.poll(2):
                        continue
                    command = conn.recv_bytes(64).decode("ascii", "replace")
            except (OSError, EOFError, AuthenticationError):
                continue  # a client that went away or had the wrong key; or closed
            if command in COMMANDS:
                log.info("command: %s", command)
                self.handle(command)

    def close(self):
        self.closed = True
        if self.listener is not None:
            self.listener.close()
