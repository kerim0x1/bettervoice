"""What macOS and Linux share: one BetterVoice per user, through a lock file."""

import os

from bettervoice import brand, config

_lock = None  # the open lock file; the lock lasts as long as the process


def acquire_single_instance():
    """False if BetterVoice is already running for this user."""
    import fcntl

    global _lock
    os.makedirs(config.RUNTIME_DIR, mode=0o700, exist_ok=True)
    fd = os.open(os.path.join(config.RUNTIME_DIR, "bettervoice.lock"),
                 os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        os.close(fd)
        return False
    _lock = fd
    return True


def tell_already_running():
    """Only needed when the running copy can't be reached (an older version)."""
    import tkinter as tk
    from tkinter import messagebox

    root = tk.Tk()
    root.withdraw()
    messagebox.showinfo(brand.NAME, f"{brand.NAME} is already running.", parent=root)
    root.destroy()
