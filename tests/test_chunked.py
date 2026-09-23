import threading
import time

import numpy as np
import pytest

from bettervoice.stt import chunked
from bettervoice.stt.chunked import ChunkedSession, Transcriber
from bettervoice.stt.errors import SttError
from conftest import pcm, silence


class Recorder(Transcriber):
    """Records what it's asked to transcribe; returns chunk numbers as text."""

    def __init__(self, fail_on=None, **policy):
        self.calls = []
        self.fail_on = fail_on
        for name, value in policy.items():
            setattr(self, name, value)

    def transcribe(self, audio, language, prompt):
        self.calls.append((len(audio) / 16000, language, prompt))
        if len(self.calls) == self.fail_on:
            raise SttError("Test: broken")
        return f"Part{len(self.calls)}."


def run(session, seconds):
    session.start()
    time.sleep(seconds)
    return session.finish()


def wait_for(condition, timeout=10):
    end = time.monotonic() + timeout
    while not condition():
        assert time.monotonic() < end, "timed out"
        time.sleep(0.02)


def test_splits_at_pauses_and_passes_context(fake_mic):
    chunked.warm_up_vad()  # loading the VAD must not delay the first split on a slow runner
    speech = pcm("de.wav")  # 3.7 s
    fake_mic(speech + silence(1.0) + speech + silence(1.0) + speech + silence(1.0), speed=6)
    transcriber = Recorder(min_chunk_s=3, max_chunk_s=25, min_pause_s=0.5)
    session = ChunkedSession(transcriber, "de")
    session.start()
    wait_for(lambda: transcriber.calls)  # a piece is transcribed while still "speaking"
    time.sleep(16 / 6)  # the rest of the recording
    text = session.finish()
    assert len(transcriber.calls) >= 2
    assert text == " ".join(f"Part{i + 1}." for i in range(len(transcriber.calls)))
    assert all(language == "de" for _, language, _ in transcriber.calls)
    assert transcriber.calls[0][2] == ""  # no context for the first piece
    assert transcriber.calls[1][2] == "Part1."
    # the pieces are speech only: silence around them is trimmed
    assert sum(duration for duration, _, _ in transcriber.calls) < 3 * 3.7 + 1.5


def test_auto_language_is_passed_as_none(fake_mic):
    fake_mic(pcm("de.wav"), speed=6)
    transcriber = Recorder()
    run(ChunkedSession(transcriber, "multi"), 1.0)
    assert transcriber.calls[0][1] is None


def test_silence_is_never_sent(fake_mic):
    fake_mic(silence(3), speed=6)
    transcriber = Recorder()
    assert run(ChunkedSession(transcriber, "de"), 0.8) == ""
    assert transcriber.calls == []


def test_error_keeps_earlier_text(fake_mic):
    speech = pcm("de.wav")
    fake_mic(speech + silence(1.0) + speech + silence(1.0), speed=6)
    transcriber = Recorder(fail_on=2, min_chunk_s=3, min_pause_s=0.5)
    assert run(ChunkedSession(transcriber, "de"), 1.8) == "Part1."


def test_error_without_text_raises(fake_mic):
    fake_mic(pcm("de.wav"), speed=6)
    session = ChunkedSession(Recorder(fail_on=1), "de")
    with pytest.raises(SttError, match="broken"):
        run(session, 1.0)


def test_unexpected_exception_becomes_stt_error(fake_mic):
    class Broken(Transcriber):
        def transcribe(self, audio, language, prompt):
            raise ValueError("bug")

    fake_mic(pcm("de.wav"), speed=6)
    with pytest.raises(SttError, match="Recognition failed"):
        run(ChunkedSession(Broken(), "de"), 1.0)


def test_abort_returns_at_once_and_drops_everything(fake_mic):
    release = threading.Event()

    class Slow(Recorder):
        def transcribe(self, audio, language, prompt):
            release.wait(5)
            return super().transcribe(audio, language, prompt)

    fake_mic(pcm("de.wav") + silence(1.0), speed=6)
    transcriber = Slow(min_chunk_s=0.5, min_pause_s=0.5)
    session = ChunkedSession(transcriber, "de")
    session.start()
    time.sleep(1.2)
    started = time.perf_counter()
    session.abort()
    assert time.perf_counter() - started < 0.2
    release.set()
    session.worker.join(2)
    assert not session.worker.is_alive()


def test_split_point_forces_a_cut_without_pauses(monkeypatch):
    transcriber = Recorder(min_chunk_s=6, max_chunk_s=25, min_pause_s=0.5)
    session = ChunkedSession(transcriber, "de")
    audio = np.zeros(16000 * 30, np.float32)

    # one span of speech that never pauses: cut at max_chunk_s
    monkeypatch.setattr(chunked, "speech_spans",
                        lambda a, p=0.5: [{"start": 0, "end": len(a)}])
    cut, spans = session._split_point(audio, final=False)
    assert cut == 25 * 16000 and spans

    # a finished sentence followed by a pause: cut right after it
    monkeypatch.setattr(chunked, "speech_spans",
                        lambda a, p=0.5: [{"start": 0, "end": 8 * 16000},
                                          {"start": 9 * 16000, "end": len(a)}])
    cut, spans = session._split_point(audio[: 16000 * 12], final=False)
    assert cut == 8 * 16000 and len(spans) == 1

    # too short to split yet
    assert session._split_point(audio[: 16000 * 3], final=False) == (0, [])
