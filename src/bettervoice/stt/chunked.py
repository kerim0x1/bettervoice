"""Record, split at pauses, transcribe piece by piece.

Used by every engine that transcribes finished audio rather than a live
stream (local Whisper, ElevenLabs, OpenRouter). While the user is still
speaking, everything up to the last pause is already being transcribed, so
after Win+O only the rest is left. Pure silence is never sent anywhere.
"""

import logging
import queue
import threading

import numpy as np

from bettervoice import config
from bettervoice.mic import SAMPLE_RATE, Microphone
from bettervoice.stt.audio import from_pcm16
from bettervoice.stt.errors import SttError

log = logging.getLogger(__name__)

POLL_S = 0.4  # how often the worker looks for a pause
MAX_PROMPT_CHARS = 200  # previous text handed to the transcriber as context


def speech_spans(audio, min_pause_s=0.5):
    """[{"start": sample, "end": sample}, ...] of the speech in audio (Silero VAD)."""
    from faster_whisper.vad import VadOptions, get_speech_timestamps

    return get_speech_timestamps(
        audio,
        VadOptions(min_silence_duration_ms=int(min_pause_s * 1000), speech_pad_ms=150),
    )


def warm_up_vad():
    """Import and load the VAD now, so the first dictation doesn't wait for it."""
    speech_spans(np.zeros(SAMPLE_RATE, np.float32))


class Transcriber:
    """What ChunkedSession needs from an engine; subclasses set the policy."""

    min_chunk_s = 6  # don't split off shorter pieces: context helps accuracy
    max_chunk_s = 25  # always split before this
    min_pause_s = 0.5  # a pause this long can end a piece

    def prepare(self):
        """Called when recording starts (e.g. to open a connection)."""

    def transcribe(self, audio, language, prompt):
        """audio: float32 16 kHz mono; language: code or None; prompt: prior text."""
        raise NotImplementedError


class ChunkedSession:
    def __init__(self, transcriber, language, on_level=None):
        self.transcriber = transcriber
        self.language = None if language == config.AUTO else language
        self.audio_queue = queue.Queue()
        self.mic = Microphone(self.audio_queue.put, on_level)
        self.stopped = threading.Event()
        self.aborted = False
        self.texts = []
        self.error = None
        self.worker = threading.Thread(target=self._run, daemon=True)

    def start(self):
        self.mic.start()
        self.transcriber.prepare()
        self.worker.start()

    def finish(self):
        """Stop recording, transcribe what's left, return the transcript.

        Text recognized before an error is kept; the error is only raised
        if nothing was recognized at all.
        """
        self.mic.stop()  # all audio is in the queue once this returns
        self.stopped.set()
        self.worker.join()
        text = config.join_transcripts(self.texts)
        if self.error is not None:
            if not text:
                raise self.error
            log.warning("keeping the text recognized before an error: %s", self.error)
        return text

    def abort(self):
        """Stop recording and drop everything; returns immediately."""
        self.aborted = True
        self.mic.stop()
        self.stopped.set()

    def _take_audio(self):
        chunks = []
        while True:
            try:
                chunks.append(self.audio_queue.get_nowait())
            except queue.Empty:
                break
        return from_pcm16(b"".join(chunks))

    def _run(self):
        try:
            pending = np.zeros(0, np.float32)
            while not self.aborted:
                final = self.stopped.is_set()
                pending = np.concatenate([pending, self._take_audio()])
                cut, spans = self._split_point(pending, final)
                if cut:
                    self._transcribe(pending[:cut], spans)
                    pending = pending[cut:]
                    continue  # there may be a backlog (e.g. a model was loading)
                if final:
                    break
                self.stopped.wait(POLL_S)
        except SttError as e:
            log.error("recognition failed: %s", e)
            self.error = e
        except Exception as e:
            log.exception("recognition failed")
            self.error = SttError("Recognition failed", str(e))

    def _split_point(self, audio, final):
        """(samples to transcribe now, speech spans in them); 0 = keep waiting."""
        t = self.transcriber
        max_len = int(t.max_chunk_s * SAMPLE_RATE)
        if final and len(audio) <= max_len:
            return len(audio), speech_spans(audio, t.min_pause_s) if len(audio) else []
        if len(audio) < t.min_chunk_s * SAMPLE_RATE:
            return 0, []
        window = audio[:max_len]
        spans = speech_spans(window, t.min_pause_s)
        # a span is finished once a real pause follows it
        closed = [s for s in spans if len(window) - s["end"] >= t.min_pause_s * SAMPLE_RATE]
        if closed:
            return closed[-1]["end"], closed
        if len(audio) >= max_len:  # no pause for a long time: split anyway
            return max_len, spans
        return 0, []

    def _transcribe(self, audio, spans):
        if not spans or self.aborted:
            return  # silence: nothing to send, and Whisper would hallucinate
        speech = audio[max(0, spans[0]["start"]):spans[-1]["end"]]
        prompt = config.join_transcripts(self.texts)[-MAX_PROMPT_CHARS:]
        text = self.transcriber.transcribe(speech, self.language, prompt)
        if text:
            self.texts.append(text)
