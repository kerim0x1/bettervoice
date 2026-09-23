"""Smoke test: every page of the setup wizard and the settings window renders,
for every engine. Windows are invisible and nothing touches the network."""

import time
import tkinter as tk

import pytest

from bettervoice import autostart, brand, config, setup_ui
from bettervoice.stt import local, openrouter


@pytest.fixture(scope="module")
def root():
    try:
        window = tk.Tk()
    except tk.TclError:
        pytest.skip("no display")
    window.withdraw()
    yield window
    window.destroy()


@pytest.fixture
def ui(root, settings, monkeypatch):
    monkeypatch.setattr(setup_ui.SetupWindow, "focus_force", lambda self: None)
    monkeypatch.setattr(autostart, "is_enabled", lambda: False)
    monkeypatch.setattr(openrouter, "audio_models", lambda: ["google/gemini-3.8-flash"])
    monkeypatch.setattr(local, "gpu_status", slow_gpu_status)
    # an exception in a Tk callback would only be printed: make it fail the test
    errors = []
    monkeypatch.setattr(root, "report_callback_exception", lambda *exc: errors.append(exc))
    windows = []

    def open_window(**kwargs):
        window = setup_ui.SetupWindow(root, **kwargs)
        window.attributes("-alpha", 0.0)
        windows.append(window)
        return window

    yield open_window
    for window in windows:
        if window.winfo_exists():
            pump(window)
            window.destroy()
    root.update()
    assert not errors, errors[0][1]


def slow_gpu_status():
    time.sleep(0.2)  # long enough to be overtaken by the user
    return "none"


def pump(window, rounds=15):
    for _ in range(rounds):
        window.update()
        time.sleep(0.02)


def test_every_wizard_page_renders(ui):
    wizard = ui(wizard=True)
    assert wizard.title() == f"{brand.NAME} – Setup"
    for page in setup_ui.WIZARD_STEPS:
        engines = config.ENGINES if page == "setup" else [wizard.engine]
        for engine in engines:
            wizard.engine = engine
            wizard.show(page)
            pump(wizard)
            assert wizard.page == page


def test_every_settings_page_renders(ui):
    closed = []
    settings = ui(wizard=False, on_close=lambda: closed.append(True))
    assert settings.title() == f"{brand.NAME} – Settings"
    for engine in config.ENGINES:
        settings.select_engine(engine)
        pump(settings)
        assert settings.cards[engine].selected
    for page, _label, _icon in setup_ui.SETTINGS_PAGES:
        settings.show(page)
        pump(settings)
    settings.close()
    assert closed


def test_engine_without_key_stays_inactive(ui):
    settings = ui(wizard=False)
    settings.select_engine(config.ELEVENLABS)
    pump(settings)
    assert config.get("engine") == config.LOCAL  # no key yet: nothing switched
    settings.select_engine(config.LOCAL)
    assert config.get("engine") == config.LOCAL


def test_switching_cards_quickly(ui):
    # a replaced panel's background check must not touch its destroyed widgets
    settings = ui(wizard=False)
    for engine in (config.LOCAL, config.DEEPGRAM, config.LOCAL, config.OPENROUTER):
        settings.select_engine(engine)
    pump(settings, rounds=30)
