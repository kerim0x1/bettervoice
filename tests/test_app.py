"""The dictation flow in bettervoice.app: hotkey, Esc, errors, paste."""

import ctypes
import queue
import threading
import time
import types

import pytest

from bettervoice import app as bv
from bettervoice.stt.errors import MissingKey, SttError


class FakeSession:
    def __init__(self, text="Hello world.", error=None, finish_gate=None):
        self.text, self.error, self.finish_gate = text, error, finish_gate
        self.started = threading.Event()
        self.aborted = False

    def start(self):
        self.started.set()

    def finish(self):
        if self.finish_gate:
            self.finish_gate.wait(5)
        if self.error:
            raise self.error
        return self.text

    def abort(self):
        self.aborted = True


@pytest.fixture
def app(monkeypatch, settings):
    sessions = []
    ns = types.SimpleNamespace(pasted=[], sessions=sessions, next=lambda: FakeSession())

    def create_session(engine, language, on_level=None):
        session = ns.next()
        if isinstance(session, Exception):
            raise session
        sessions.append(session)
        return session

    monkeypatch.setattr(bv, "ui_q", queue.Queue())
    monkeypatch.setattr(bv, "paste_text", ns.pasted.append)
    monkeypatch.setattr(bv, "OVERLAY", types.SimpleNamespace(push_level=lambda level: None))
    monkeypatch.setattr(bv.stt, "create_session", create_session)
    monkeypatch.setattr(bv.stt, "polish", lambda text, engine: text)
    monkeypatch.setattr(bv, "current", None)
    settings.set("engine", "deepgram")

    def events():
        out = []
        while not bv.ui_q.empty():
            out.append(bv.ui_q.get()[:2])
        return out

    def wait_idle(timeout=3):
        deadline = time.time() + timeout
        while bv.current is not None and time.time() < deadline:
            time.sleep(0.01)
        time.sleep(0.05)
        return bv.current is None

    ns.events, ns.wait_idle = events, wait_idle
    return ns


def start(app):
    bv.on_hotkey()
    deadline = time.time() + 2
    while not app.sessions and time.time() < deadline:
        time.sleep(0.01)
    app.sessions[-1].started.wait(2)
    return app.sessions[-1]


def test_dictation_is_pasted(app):
    start(app)
    bv.on_hotkey()
    bv.on_hotkey()  # ignored while processing
    assert app.wait_idle()
    assert app.pasted == ["Hello world."]
    assert app.events() == [("show",), ("processing",), ("hide",)]


def test_polish_runs_before_paste(app, monkeypatch):
    monkeypatch.setattr(bv.stt, "polish", lambda text, engine: text.upper())
    start(app)
    bv.on_hotkey()
    app.wait_idle()
    assert app.pasted == ["HELLO WORLD."]


def test_escape_while_recording(app):
    assert bv.cancel() is False  # nothing running: Esc isn't ours
    session = start(app)
    assert bv.cancel() is True
    assert app.wait_idle()
    assert session.aborted and app.pasted == []
    assert ("flash", "Cancelled") in app.events()


def test_escape_while_processing_and_start_again(app):
    gate = threading.Event()
    app.next = lambda: FakeSession(finish_gate=gate)
    start(app)
    bv.on_hotkey()  # stop: finish() now hangs, e.g. waiting for a model download
    assert bv.cancel() is True
    assert bv.current is None  # Win+O works again right away
    app.next = lambda: FakeSession(text="New.")
    start(app)
    bv.on_hotkey()
    gate.set()
    assert app.wait_idle()
    assert app.pasted == ["New."]  # the cancelled one was dropped


def test_missing_key_opens_the_settings(app):
    app.next = lambda: MissingKey("ElevenLabs: API key missing")
    bv.on_hotkey()
    assert app.wait_idle()
    events = app.events()
    assert ("flash", "ElevenLabs: API key missing") in events and ("settings",) in events


def test_errors_are_shown(app):
    app.next = lambda: FakeSession(error=SttError("OpenRouter: out of credit"))
    start(app)
    bv.on_hotkey()
    assert app.wait_idle()
    assert ("flash", "OpenRouter: out of credit") in app.events()
    assert app.pasted == []


def test_empty_result(app):
    app.next = lambda: FakeSession(text="")
    start(app)
    bv.on_hotkey()
    app.wait_idle()
    assert ("flash", "No speech recognized") in app.events()


def test_keyboard_hook(monkeypatch):
    pressed, cancels = [], []
    user32 = types.SimpleNamespace(keybd_event=lambda *a: None,
                                   CallNextHookEx=lambda *a: 0)
    monkeypatch.setattr(bv, "user32", user32)
    monkeypatch.setattr(bv, "win_is_down", lambda: True)
    monkeypatch.setattr(bv, "on_hotkey", lambda: pressed.append(1))
    active = [False]
    monkeypatch.setattr(bv, "cancel", lambda: cancels.append(1) or active[0])
    monkeypatch.setattr(bv, "_swallowed", set())

    def key(vk, down):
        info = bv.KBDLLHOOKSTRUCT(vkCode=vk)
        message = bv.WM_KEYDOWN if down else bv.WM_KEYUP
        return bv._hook_callback(0, message, ctypes.addressof(info))

    # Win+O: swallowed down and up, autorepeat doesn't trigger again
    assert key(bv.VK_O, True) == 1 and key(bv.VK_O, True) == 1
    assert key(bv.VK_O, False) == 1
    assert pressed == [1]
    # Esc with nothing running goes to the focused app
    assert key(bv.VK_ESCAPE, True) == 0 and key(bv.VK_ESCAPE, False) == 0
    # Esc during a dictation is ours, including its key-up
    active[0] = True
    assert key(bv.VK_ESCAPE, True) == 1 and key(bv.VK_ESCAPE, False) == 1
    # other keys pass through
    assert key(0x41, True) == 0
