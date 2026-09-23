"""Against the real services and models. Opt-in: RUN_INTEGRATION=1.

Cloud engines are only tested when their API key is configured; the local
engine only when a model is already downloaded.
"""

import os
import time

import pytest

from bettervoice import config, stt
from bettervoice.stt import local
from bettervoice.stt.chunked import ChunkedSession
from conftest import pcm, silence

pytestmark = pytest.mark.skipif(not os.environ.get("RUN_INTEGRATION"),
                                reason="set RUN_INTEGRATION=1 to talk to real services")

DE = pcm("de.wav")  # German speech; its transcript contains "Hallo" and "Test"


def dictate(session, audio):
    session.start()
    time.sleep(len(audio) / 32000 + 0.5)
    return session.finish()


@pytest.mark.parametrize("engine", [config.DEEPGRAM, config.ELEVENLABS, config.OPENROUTER])
def test_bogus_keys_are_rejected(engine):
    assert stt.check_key(engine, "bogus-key") is False


@pytest.mark.parametrize("engine", [config.DEEPGRAM, config.ELEVENLABS, config.OPENROUTER])
def test_cloud_engine(engine, fake_mic):
    if not config.has_key(engine):
        pytest.skip(f"no {engine} key configured")
    assert stt.check_key(engine, config.get(config.key_setting(engine))) is True
    fake_mic(DE + silence(0.5))
    text = dictate(stt.create_session(engine, "de"), DE)
    assert "Hallo" in text and "Test" in text


def test_local_engine(fake_mic):
    gpu = local.gpu_status() == "ok"
    if local.model_path(local.resolve("auto", gpu)) is None:
        pytest.skip("no local model downloaded")
    engine = local.LocalEngine()
    engine.load("auto")
    engine.wait()
    transcriber = local.LocalTranscriber()
    transcriber.prepare = lambda: None
    local_engine, local.ENGINE = local.ENGINE, engine
    try:
        fake_mic(DE + silence(0.5))
        text = dictate(ChunkedSession(transcriber, "multi"), DE)
    finally:
        local.ENGINE = local_engine
    assert "Hallo" in text and "Test" in text
