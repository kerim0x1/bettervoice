"""BetterVoice: press the hotkey to start dictating, press it again to stop,
Esc to cancel. The hotkey is Win+O on Windows, ⌃⌥O on macOS and Ctrl+Alt+O
on Linux.

The transcript is pasted into whatever window/field has focus. Speech is
recognized locally (Whisper, offline) or by Deepgram, ElevenLabs or an
OpenRouter model; the optional AI Polish removes filler words.

Usage (`python -m bettervoice ...` works the same):
    bettervoice             # run; the first start opens the setup
    bettervoice --setup     # open the setup wizard again
    bettervoice --test      # record 5 s with the configured engine, print the text
    bettervoice --version
    bettervoice --toggle    # to the running copy: start or stop (see ipc.py)
"""

import logging
import os
import queue
import sys
import threading
import time
import tkinter as tk

from bettervoice import __version__, autostart, brand, config, ipc, stt
from bettervoice import overlay as overlay_ui
from bettervoice.desktop import PasteFallback, system, ui
from bettervoice.mic import PortAudioError
from bettervoice.stt.errors import MissingKey, SttError
from bettervoice.stt.local import ENGINE as LOCAL

log = logging.getLogger("bettervoice")

# ------------------------------------------------------------------- log ---

LOG_MAX_BYTES = 1_000_000


def setup_logging():
    """Log to the terminal, or without one (the packaged app, pythonw, a start
    from the desktop) to config.LOG_PATH. Transcripts are never logged."""
    stream = sys.stdout
    if stream is None or sys.stderr is None or not stream.isatty():
        try:
            if os.path.getsize(config.LOG_PATH) > LOG_MAX_BYTES:
                os.replace(config.LOG_PATH, config.LOG_PATH + ".1")
        except OSError:
            pass
        stream = open(config.LOG_PATH, "a", buffering=1, encoding="utf-8")
        sys.stdout = sys.stdout or stream  # pythonw has no console at all
        sys.stderr = sys.stderr or stream
    logging.basicConfig(
        level=logging.INFO,
        stream=stream,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    logging.captureWarnings(True)


def paste_text(text):
    system.paste(text)


# -------------------------------------------------------------- dictation ---

ui_q = queue.Queue()  # overlay/tray/window events, handled on the tk main thread
OVERLAY = None
TRAY = None
HOTKEYS = None

state_lock = threading.Lock()
current = None  # the Dictation in progress, if any


def _set_current(dictation):
    """Change the running dictation (under state_lock)."""
    global current
    current = dictation
    if HOTKEYS is not None:
        HOTKEYS.dictating(dictation is not None)  # Esc is ours only meanwhile


class Dictation:
    """One dictation: record until the hotkey, transcribe, paste."""

    def __init__(self):
        self.engine = config.get("engine")
        self.language = config.get("language")
        self.stop_requested = threading.Event()
        self.processing = False  # the hotkey was pressed the second time
        self.cancelled = False  # Esc

    def run(self):
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
                    _set_current(None)

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
        if not text:
            ui_q.put(("flash", "No speech recognized", "info"))
            return
        try:
            paste_text(text)
        except PasteFallback as e:
            ui_q.put(("flash", e.message, "info"))
        else:
            ui_q.put(("hide",))

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
    """The hotkey; called from the keyboard hook, so it must return quickly."""
    with state_lock:
        if current is None:
            dictation = Dictation()
            _set_current(dictation)
            ui_q.put(("show",))  # instant feedback at the caret
            threading.Thread(target=dictation.run, daemon=True).start()
        elif not current.processing:
            current.processing = True
            ui_q.put(("processing",))
            current.stop_requested.set()
        # while processing: ignore; Esc cancels


def cancel():
    """Esc; True if a dictation was running (the key is then swallowed)."""
    with state_lock:
        dictation = current
        if dictation is None:
            return False
        dictation.cancelled = True
        dictation.stop_requested.set()
        _set_current(None)  # a new dictation may start right away
    ui_q.put(("flash", "Cancelled", "info"))
    return True


def handle_command(command):
    """A command from `bettervoice --toggle` & co. (on the command thread)."""
    if command == "toggle":
        on_hotkey()
    elif command == "cancel":
        cancel()
    else:  # "settings", "quit"
        ui_q.put((command,))


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


_tray_refresh = threading.Event()  # set while a refresh waits in ui_q


def refresh_tray():
    """Update the tray's tooltip and menu soon, on the tk thread (AppKit wants
    the main thread); a burst of calls, e.g. download progress, makes one."""
    if TRAY is not None and not _tray_refresh.is_set():
        _tray_refresh.set()
        ui_q.put(("tray",))


def _refresh_tray_now():
    _tray_refresh.clear()
    TRAY.title = f"{brand.NAME} – {status_text()}"
    TRAY.update_menu()


def _choice_menu(setting, options):
    """Radio-button submenu that sets config `setting` to one of `options`."""
    import pystray

    def item(value, label):
        def select(icon, item):
            ui_q.put(("set", setting, value))

        def checked(item):
            return config.get(setting) == value

        return pystray.MenuItem(label, select, checked=checked, radio=True)

    return pystray.Menu(*(item(value, label) for value, label in options.items()))


def start_tray():
    import pystray  # here, not at the top: on Linux it connects to the X server

    engines = {engine: config.engine_label(engine) for engine in config.ENGINES}
    menu = pystray.Menu(
        pystray.MenuItem(f"{system.HOTKEY} to dictate · Esc to cancel", None, enabled=False),
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
        pystray.MenuItem("Open log", lambda icon, item: system.open_path(config.LOG_PATH)),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Quit", lambda icon, item: ui_q.put(("quit",))),
    )
    icon = system.make_tray("bettervoice", f"{brand.NAME} – {status_text()}", menu)
    system.run_tray(icon)
    return icon


# --------------------------------------------------------------- windows ---

_settings_window = None


def open_settings(root, page=None):
    """The settings window (one at a time); page: "engine", "language", "general"."""
    global _settings_window
    from bettervoice import setup_ui

    if _settings_window is not None and _settings_window.winfo_exists():
        _settings_window.show(page)
        system.bring_to_front(_settings_window)
        return

    def closed():
        global _settings_window
        _settings_window = None

    _settings_window = setup_ui.SetupWindow(
        root, wizard=False, page=page, on_change=settings_changed, on_close=closed,
        on_quit=lambda: ui_q.put(("quit",)),  # also where the tray has no menu
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


# ------------------------------------------------------------------- main ---


def _configured_before():
    """An earlier version was set up (e.g. with a Deepgram key) or the user got
    as far as downloading a local model: keep running without the wizard."""
    engine = config.get("engine")
    if engine == config.LOCAL:
        return LOCAL.state != "off"
    return config.has_key(engine)


def main(force_setup=False):
    global OVERLAY, TRAY, HOTKEYS
    if not system.acquire_single_instance():
        log.error("%s is already running", brand.NAME)
        if not ipc.send("settings"):  # the running copy shows itself instead
            system.tell_already_running()
        return
    try:
        autostart.follow_this_copy()
    except OSError as e:
        log.warning("could not update autostart: %s", e)
    system.prepare_process()
    root = tk.Tk(className="bettervoice")
    root.withdraw()
    ui.attach(root, lambda fn: ui_q.put(("call", fn)))
    system.init_ui(root, on_reopen=lambda: ui_q.put(("settings",)))
    commands = ipc.Server(handle_command)
    try:
        commands.start()
    except OSError as e:
        log.warning("no command channel (bettervoice --toggle): %s", e)
    OVERLAY = overlay_ui.Overlay(root)
    LOCAL.on_status = refresh_tray

    if force_setup or not config.enabled("setup_done"):
        from bettervoice import setup_ui

        wizard = setup_ui.SetupWindow(root, wizard=True, on_change=settings_changed)
        root.wait_window(wizard)
        if not config.enabled("setup_done") and not _configured_before():
            log.info("setup closed before it was finished")
            return

    TRAY = start_tray()
    sync_engine()
    HOTKEYS = system.Hotkeys(on_hotkey, cancel,
                             on_error=lambda message: ui_q.put(("flash", message, "error")))
    HOTKEYS.start()
    if "shortcut" in system.missing_access():  # Wayland: the desktop shortcut is missing
        ui_q.put(("flash", f"Set up {system.HOTKEY} in Settings → General", "info"))

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
        "tray": _refresh_tray_now,
        "call": lambda fn: fn(),
    }

    def poll_events():
        while True:
            try:
                event, *args = ui_q.get_nowait()
            except queue.Empty:
                break
            if event == "quit":
                commands.close()
                system.stop_tray(TRAY)
                root.destroy()
                return
            handlers[event](*args)
        root.after(25, poll_events)

    poll_events()
    root.mainloop()


def self_check():
    """Load what the app otherwise loads only later: a packaged build that
    lacks something fails here, in CI, instead of in front of the user."""
    import ctranslate2  # noqa: F401 - the local engine
    import faster_whisper  # noqa: F401

    from bettervoice import setup_ui  # noqa: F401
    from bettervoice.stt import deepgram, elevenlabs, openrouter  # noqa: F401
    from bettervoice.stt.chunked import warm_up_vad

    warm_up_vad()  # the Silero model and ONNX Runtime
    system.self_check()


def run(argv=None):
    """Start the app (the command line comes through bettervoice.cli)."""
    args = sys.argv[1:] if argv is None else argv
    if "--version" in args:
        print(f"{brand.NAME} {__version__}")
        return
    if "--check" in args:
        self_check()
        print(f"{brand.NAME} {__version__}: ok")
        return
    config.prepare_data_dir()
    setup_logging()
    log.info("%s %s on %s", brand.NAME, __version__, system.NAME)
    if "--test" in args:
        run_test()
    else:
        main(force_setup="--setup" in args)


if __name__ == "__main__":
    run()
