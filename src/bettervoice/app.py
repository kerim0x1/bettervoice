"""BetterVoice: press Win+O to start dictating, Win+O again to stop, Esc to cancel.

The transcript is pasted into whatever window/field has focus. Speech is
recognized locally (Whisper, offline) or by Deepgram, ElevenLabs or an
OpenRouter model; the optional AI Polish removes filler words.

Usage (`python -m bettervoice ...` works the same):
    bettervoice             # run; the first start opens the setup
    bettervoice --setup     # open the setup wizard again
    bettervoice --test      # record 5 s with the configured engine, print the text
    bettervoice --version
"""

import ctypes
import ctypes.wintypes
import logging
import os
import queue
import sys
import threading
import time
import tkinter as tk

import pyperclip
import pystray

from bettervoice import __version__, autostart, brand, config, stt
from bettervoice import overlay as overlay_ui
from bettervoice.mic import PortAudioError
from bettervoice.stt.errors import MissingKey, SttError
from bettervoice.stt.local import ENGINE as LOCAL

log = logging.getLogger("bettervoice")

# ------------------------------------------------------------------- log ---

LOG_MAX_BYTES = 1_000_000


def setup_logging():
    """Log to the console, or without one (pythonw / windowed exe) to
    %APPDATA%\\BetterVoice\\bettervoice.log. Transcripts are never logged."""
    if sys.stdout is None or sys.stderr is None:
        try:
            if os.path.getsize(config.LOG_PATH) > LOG_MAX_BYTES:
                os.replace(config.LOG_PATH, config.LOG_PATH + ".1")
        except OSError:
            pass
        log_file = open(config.LOG_PATH, "a", buffering=1, encoding="utf-8")
        sys.stdout = sys.stdout or log_file
        sys.stderr = sys.stderr or log_file
    logging.basicConfig(
        level=logging.INFO,
        stream=sys.stdout,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    logging.captureWarnings(True)


# ------------------------------------------------------------------ paste ---

VK_LWIN, VK_RWIN, VK_CONTROL, VK_V = 0x5B, 0x5C, 0x11, 0x56
KEYEVENTF_KEYUP = 0x0002
CLIPBOARD_RESTORE_DELAY = 1.0  # s; give the target app time to read the paste

user32 = ctypes.windll.user32


def win_is_down():
    return any(user32.GetAsyncKeyState(vk) & 0x8000 for vk in (VK_LWIN, VK_RWIN))


def wait_for_win_release(timeout=2.0):
    """The user is likely still holding the Win key from the hotkey press."""
    deadline = time.time() + timeout
    while win_is_down() and time.time() < deadline:
        time.sleep(0.02)


def _restore_clipboard(text):
    try:
        pyperclip.copy(text)
    except Exception:
        pass


def paste_text(text):
    """Paste via clipboard + Ctrl+V, then put the previous clipboard text back.

    Only text can be restored: if the clipboard held something else (e.g. an
    image), the transcript simply stays on the clipboard.
    """
    try:
        previous = pyperclip.paste()
    except Exception:
        previous = ""
    pyperclip.copy(text)
    wait_for_win_release()
    time.sleep(0.05)
    user32.keybd_event(VK_CONTROL, 0, 0, 0)
    user32.keybd_event(VK_V, 0, 0, 0)
    time.sleep(0.02)
    user32.keybd_event(VK_V, 0, KEYEVENTF_KEYUP, 0)
    user32.keybd_event(VK_CONTROL, 0, KEYEVENTF_KEYUP, 0)

    if previous:
        timer = threading.Timer(CLIPBOARD_RESTORE_DELAY, _restore_clipboard, (previous,))
        timer.daemon = True
        timer.start()


# ----------------------------------------------------------------- hotkey ---
# Win+O is already claimed by Windows itself (rotation lock), so RegisterHotKey
# fails with ERROR_HOTKEY_ALREADY_REGISTERED. Instead we install a low-level
# keyboard hook that intercepts the combo before Windows processes it. The
# hook also turns Esc into "cancel" while a dictation is running.

WH_KEYBOARD_LL = 13
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_SYSKEYDOWN = 0x0104
WM_SYSKEYUP = 0x0105
VK_O = 0x4F
VK_ESCAPE = 0x1B
VK_DUMMY = 0xFF  # tapped so the Win key release doesn't open the Start menu

LRESULT = ctypes.c_ssize_t
HookProc = ctypes.WINFUNCTYPE(
    LRESULT, ctypes.c_int, ctypes.wintypes.WPARAM, ctypes.wintypes.LPARAM
)
user32.SetWindowsHookExW.restype = ctypes.c_void_p
user32.UnhookWindowsHookEx.argtypes = [ctypes.c_void_p]
user32.CallNextHookEx.restype = LRESULT
user32.CallNextHookEx.argtypes = [
    ctypes.c_void_p,
    ctypes.c_int,
    ctypes.wintypes.WPARAM,
    ctypes.wintypes.LPARAM,
]


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("vkCode", ctypes.wintypes.DWORD),
        ("scanCode", ctypes.wintypes.DWORD),
        ("flags", ctypes.wintypes.DWORD),
        ("time", ctypes.wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


_swallowed = set()  # keys whose key-up must be swallowed too


def _hook_callback(n_code, w_param, l_param):
    if n_code == 0:
        vk = ctypes.cast(l_param, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents.vkCode
        down = w_param in (WM_KEYDOWN, WM_SYSKEYDOWN)
        if vk == VK_O and down and win_is_down():
            if VK_O not in _swallowed:  # ignore key autorepeat
                _swallowed.add(VK_O)
                user32.keybd_event(VK_DUMMY, 0, 0, 0)
                user32.keybd_event(VK_DUMMY, 0, KEYEVENTF_KEYUP, 0)
                on_hotkey()
            return 1  # swallow: Windows never sees Win+O
        if vk == VK_ESCAPE and down and (VK_ESCAPE in _swallowed or cancel()):
            _swallowed.add(VK_ESCAPE)
            return 1  # the Esc belonged to us, not to the focused app
        if not down and vk in _swallowed:
            _swallowed.discard(vk)
            return 1
    return user32.CallNextHookEx(None, n_code, w_param, l_param)


def run_hotkey_loop():
    """Install the keyboard hook and pump messages for it (blocks)."""
    hook_proc = HookProc(_hook_callback)  # keep a reference so it isn't GC'd
    hook = user32.SetWindowsHookExW(WH_KEYBOARD_LL, hook_proc, None, 0)
    if not hook:
        log.error("could not install keyboard hook")
        ui_q.put(("flash", "Hotkey unavailable", "error"))
        return
    log.info("ready: Win+O to dictate, Esc to cancel")
    msg = ctypes.wintypes.MSG()
    try:
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            pass  # hook callbacks are delivered while GetMessageW pumps
    finally:
        user32.UnhookWindowsHookEx(hook)


# -------------------------------------------------------------- dictation ---

ui_q = queue.Queue()  # overlay/tray/window events, handled on the tk main thread
OVERLAY = None
TRAY = None

state_lock = threading.Lock()
current = None  # the Dictation in progress, if any


class Dictation:
    """One dictation: record until Win+O, transcribe, paste."""

    def __init__(self):
        self.engine = config.get("engine")
        self.language = config.get("language")
        self.stop_requested = threading.Event()
        self.processing = False  # Win+O was pressed the second time
        self.cancelled = False  # Esc

    def run(self):
        global current
        try:
            self._run()
        except MissingKey as e:
            log.error("%s", e)
            ui_q.put(("flash", e.message, "error"))
            ui_q.put(("settings",))
        except SttError as e:
            log.error("%s", e)
            if not self.cancelled:
                ui_q.put(("flash", e.message, "error"))
        except Exception:
            log.exception("dictation failed")
            if not self.cancelled:
                ui_q.put(("flash", "Recognition failed", "error"))
        finally:
            with state_lock:
                if current is self:
                    current = None

    def _run(self):
        session = stt.create_session(self.engine, self.language, OVERLAY.push_level)
        try:
            session.start()
        except PortAudioError as e:
            raise SttError("No microphone found", str(e)) from e
        log.info("recording (%s, %s)", self.engine, self.language)
        self.stop_requested.wait()
        if self.cancelled:
            session.abort()
            log.info("cancelled")
            return
        started = time.perf_counter()
        stop_watching = self._watch_model_loading()
        try:
            text = session.finish()
        finally:
            stop_watching()
        if self.cancelled:
            return
        text = stt.polish(text, self.engine)
        log.info("recognized %d characters in %.2fs after stop",
                 len(text), time.perf_counter() - started)
        if self.cancelled:
            return
        if text:
            paste_text(text)
            ui_q.put(("hide",))
        else:
            ui_q.put(("flash", "No speech recognized", "info"))

    def _watch_model_loading(self):
        """While the local model is still downloading or loading, show its
        progress. Returns the function that ends the watching."""
        lock = threading.Lock()
        done = False

        def stop():
            nonlocal done
            with lock:  # after this, nothing more is posted
                done = True

        def post(event):
            with lock:
                if not done and not self.cancelled:
                    ui_q.put(event)

        def watch():
            while not LOCAL.ready and not done and not self.cancelled:
                post(("status", f"Local model {LOCAL.status}  ·  Esc to cancel"))
                time.sleep(0.3)
            post(("processing",))

        if self.engine == config.LOCAL and not LOCAL.ready:
            threading.Thread(target=watch, daemon=True).start()
        return stop


def on_hotkey():
    """Win+O; called from the keyboard hook, so it must return quickly."""
    global current
    with state_lock:
        if current is None:
            current = Dictation()
            ui_q.put(("show",))  # instant feedback at the caret
            threading.Thread(target=current.run, daemon=True).start()
        elif not current.processing:
            current.processing = True
            ui_q.put(("processing",))
            current.stop_requested.set()
        # while processing: ignore; Esc cancels


def cancel():
    """Esc; True if a dictation was running (the key is then swallowed)."""
    global current
    with state_lock:
        dictation = current
        if dictation is None:
            return False
        dictation.cancelled = True
        dictation.stop_requested.set()
        current = None  # a new dictation may start right away
    ui_q.put(("flash", "Cancelled", "info"))
    return True


def sync_engine():
    """Load the local model if it's selected, otherwise free its memory; warm
    up what the selected engine needs so the first dictation is quick."""
    engine = config.get("engine")
    if engine == config.LOCAL:
        LOCAL.load(config.get("local_model"))
    else:
        LOCAL.unload()
    if engine != config.DEEPGRAM:
        from bettervoice.stt.chunked import warm_up_vad

        threading.Thread(target=warm_up_vad, daemon=True).start()


def settings_changed():
    sync_engine()
    refresh_tray()


# ------------------------------------------------------------------- test ---


def run_test(seconds=5):
    engine = config.get("engine")
    if not config.has_key(engine):
        print(f"[error] no API key for {engine}")
        sys.exit(1)
    sync_engine()  # a local model loads while we record
    session = stt.create_session(engine, config.get("language"))
    print(f"[test] recording {seconds}s ({engine}) - speak now...")
    session.start()
    time.sleep(seconds)
    started = time.perf_counter()
    text = stt.polish(session.finish(), engine)
    print(f"[test] transcript ({time.perf_counter() - started:.2f}s after stop): {text!r}")


# ------------------------------------------------------------------- tray ---


def status_text():
    engine = config.get("engine")
    language = config.LANGUAGES.get(config.get("language"), config.get("language"))
    if engine == config.LOCAL:
        detail = LOCAL.status
    elif not config.has_key(engine):
        detail = "API key missing"
    else:
        detail = language
    return f"{config.engine_label(engine)}: {detail}"


def refresh_tray():
    if TRAY is not None:
        TRAY.title = f"{brand.NAME} – {status_text()}"
        TRAY.update_menu()


IMAGE_ICON, LR_LOADFROMFILE, SM_CXSMICON = 1, 0x10, 49
user32.LoadImageW.restype = ctypes.c_void_p
user32.LoadImageW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_uint,
                              ctypes.c_int, ctypes.c_int, ctypes.c_uint]


class TrayIcon(pystray.Icon):
    """pystray loads the icon at the large-icon size and Windows shrinks it
    for the tray, which blurs the mark. Load the ICO's own small frame."""

    def _assert_icon_handle(self):
        if getattr(self, "_icon_handle", None):
            return
        size = user32.GetSystemMetrics(SM_CXSMICON)
        handle = user32.LoadImageW(None, brand.ICON_PATH, IMAGE_ICON, size, size, LR_LOADFROMFILE)
        if handle:
            self._icon_handle = handle
        else:
            super()._assert_icon_handle()


def _choice_menu(setting, options):
    """Radio-button submenu that sets config `setting` to one of `options`."""

    def item(value, label):
        def select(icon, item):
            ui_q.put(("set", setting, value))

        def checked(item):
            return config.get(setting) == value

        return pystray.MenuItem(label, select, checked=checked, radio=True)

    return pystray.Menu(*(item(value, label) for value, label in options.items()))


def start_tray():
    engines = {engine: config.engine_label(engine) for engine in config.ENGINES}
    menu = pystray.Menu(
        pystray.MenuItem("Win+O to dictate · Esc to cancel", None, enabled=False),
        pystray.MenuItem(lambda item: status_text(), None, enabled=False),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Recognition", _choice_menu("engine", engines)),
        pystray.MenuItem("Language", _choice_menu("language", config.LANGUAGES)),
        pystray.MenuItem("AI Polish",
                         lambda icon, item: ui_q.put(("set", "polish", "toggle")),
                         checked=lambda item: config.enabled("polish")),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Settings…", lambda icon, item: ui_q.put(("settings",)),
                         default=True),
        pystray.MenuItem("Open log", lambda icon, item: os.startfile(config.LOG_PATH)),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Quit", lambda icon, item: ui_q.put(("quit",))),
    )
    icon = TrayIcon("bettervoice", brand.draw_mark(64), f"{brand.NAME} – {status_text()}", menu)
    threading.Thread(target=icon.run, daemon=True).start()
    return icon


# --------------------------------------------------------------- windows ---

_settings_window = None


def open_settings(root, page=None):
    """The settings window (one at a time); page: "engine", "language", "general"."""
    global _settings_window
    from bettervoice import setup_ui

    if _settings_window is not None and _settings_window.winfo_exists():
        _settings_window.show(page)
        return

    def closed():
        global _settings_window
        _settings_window = None

    _settings_window = setup_ui.SetupWindow(
        root, wizard=False, page=page, on_change=settings_changed, on_close=closed
    )


def apply_setting(root, name, value):
    """A tray choice (runs on the tk thread)."""
    if name == "polish":
        on = not config.enabled("polish")
        if on and not config.has_key(config.OPENROUTER):
            open_settings(root, "general")  # AI Polish needs an OpenRouter key
            return
        config.set("polish", "1" if on else "0")
    elif name == "engine" and not config.has_key(value):
        open_settings(root, "engine")
        _settings_window.select_engine(value)
        return
    else:
        config.set(name, value)
    settings_changed()


ERROR_ALREADY_EXISTS = 183
MB_ICONINFORMATION = 0x40
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
kernel32.CreateMutexW.restype = ctypes.c_void_p
# the second name is the one used before the rename, so an old copy and
# BetterVoice never run (and grab Win+O) at the same time
_MUTEX_NAMES = ("BetterVoice.SingleInstance", "DictationWinO_SingleInstance")
_mutex_handles = []  # held for the lifetime of the process


def acquire_single_instance():
    """False if BetterVoice, or its predecessor, is already running."""
    for name in _MUTEX_NAMES:
        _mutex_handles.append(kernel32.CreateMutexW(None, False, name))
        if ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
            return False
    return True


def _tell_already_running():
    user32.MessageBoxW(
        None,
        f"{brand.NAME} is already running – its icon is in the notification area of the "
        "taskbar.\n\n"
        f"If the older version (BetterTalk) is running there, quit it from its icon "
        f"and start {brand.NAME} again.",
        brand.NAME,
        MB_ICONINFORMATION,
    )


# ------------------------------------------------------------------- main ---


def _configured_before():
    """An earlier version was set up (e.g. with a Deepgram key) or the user got
    as far as downloading a local model: keep running without the wizard."""
    engine = config.get("engine")
    if engine == config.LOCAL:
        return LOCAL.state != "off"
    return config.has_key(engine)


def main(force_setup=False):
    global OVERLAY, TRAY
    if not acquire_single_instance():
        log.error("%s is already running", brand.NAME)
        _tell_already_running()
        return
    try:
        autostart.follow_this_copy()
    except OSError as e:
        log.warning("could not update autostart: %s", e)
    try:  # our own taskbar button and icon, also when started from source
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(brand.APP_USER_MODEL_ID)
    except (AttributeError, OSError):
        pass
    overlay_ui.enable_dpi_awareness()
    root = tk.Tk()
    root.withdraw()
    root.iconbitmap(default=brand.ICON_PATH)  # every window gets the mark
    OVERLAY = overlay_ui.Overlay(root)
    LOCAL.on_status = lambda: refresh_tray()

    if force_setup or not config.enabled("setup_done"):
        from bettervoice import setup_ui

        wizard = setup_ui.SetupWindow(root, wizard=True, on_change=settings_changed)
        root.wait_window(wizard)
        if not config.enabled("setup_done") and not _configured_before():
            log.info("setup closed before it was finished")
            return

    TRAY = start_tray()
    sync_engine()

    # the keyboard hook needs its own message pump; tk owns the main thread
    threading.Thread(target=run_hotkey_loop, daemon=True).start()

    # windows run their own event loop: open them via after_idle so polling
    # continues meanwhile
    handlers = {
        "show": OVERLAY.show_recording,
        "processing": OVERLAY.set_processing,
        "status": OVERLAY.status,
        "hide": OVERLAY.hide,
        "flash": OVERLAY.flash,
        "settings": lambda page=None: root.after_idle(open_settings, root, page),
        "set": lambda name, value: root.after_idle(apply_setting, root, name, value),
    }

    def poll_events():
        while True:
            try:
                event, *args = ui_q.get_nowait()
            except queue.Empty:
                break
            if event == "quit":
                TRAY.stop()
                root.destroy()
                return
            handlers[event](*args)
        root.after(25, poll_events)

    poll_events()
    root.mainloop()


def run(argv=None):
    """Command-line entry point: `bettervoice` / `python -m bettervoice`."""
    args = sys.argv[1:] if argv is None else argv
    if "--version" in args:
        print(f"{brand.NAME} {__version__}")
        return
    config.prepare_data_dir()
    setup_logging()
    log.info("%s %s", brand.NAME, __version__)
    if "--test" in args:
        run_test()
    else:
        main(force_setup="--setup" in args)


if __name__ == "__main__":
    run()
