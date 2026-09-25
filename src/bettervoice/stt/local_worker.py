"""The offline model's own process.

The app starts it when a dictation begins and ends it when BetterVoice sits
idle: CUDA's runtime (about 600 MB of RAM next to the model in video memory)
or the model itself (about 350 MB on the CPU) then take memory only while
BetterVoice is in use. It imports only what recognition needs.

Protocol over a multiprocessing pipe: the worker answers ("ready", device) or
("error", detail) once the model is loaded, then handles (audio bytes,
language, prompt) requests with ("text", text) or ("error", detail) until it
gets None or the app goes away.
"""

import ctypes
import ctypes.util
import glob
import importlib
import os
import sys

import numpy as np

from bettervoice import config

BEAM_SIZE = 5

# the GPU needs CUDA 12's cuBLAS (pip install nvidia-cublas-cu12); on Windows
# CTranslate2 ships the rest itself, on Linux it also needs cuDNN 9
if sys.platform == "win32":
    CUDA_LIBS = ("cublas64_12.dll", "cublasLt64_12.dll")
else:
    CUDA_LIBS = ("libcublas.so.12", "libcublasLt.so.12", "libcudnn.so.9")


# ------------------------------------------------------------------- GPU ---


def cuda_dirs():
    """Folders that may hold NVIDIA's libraries, besides the system's."""
    # a "cuda" folder next to the app or in the data folder
    dirs = [os.path.join(config.APP_DIR, "cuda"), os.path.join(config.DATA_DIR, "cuda")]
    try:
        import nvidia  # pip install nvidia-cublas-cu12

        for base in nvidia.__path__:
            dirs += glob.glob(os.path.join(base, "*", "bin" if sys.platform == "win32" else "lib"))
    except ImportError:
        pass
    return [d for d in dirs if os.path.isdir(d)]


def find_cuda_lib(name):
    """Whether a CUDA library can be found, without loading it."""
    if any(os.path.exists(os.path.join(d, name)) for d in cuda_dirs()):
        return True
    if sys.platform == "win32":
        return ctypes.util.find_library(name) is not None  # searches PATH
    stem = name[3:].split(".so")[0]  # libcublas.so.12 -> cublas
    return ctypes.util.find_library(stem) == name  # the loader's cache


def prepare_cuda():
    """Make the CUDA libraries findable for CTranslate2 in this process."""
    if sys.platform == "win32":
        for d in cuda_dirs():
            if d not in os.environ["PATH"]:  # CTranslate2 looks the DLLs up via PATH
                os.environ["PATH"] = d + os.pathsep + os.environ["PATH"]
        return
    for name in CUDA_LIBS:  # loaded globally, CTranslate2 then finds them by name
        for d in cuda_dirs():
            path = os.path.join(d, name)
            if os.path.exists(path):
                ctypes.CDLL(path, mode=ctypes.RTLD_GLOBAL)
                break
        else:
            ctypes.CDLL(name, mode=ctypes.RTLD_GLOBAL)  # installed system-wide


# ----------------------------------------------------------------- model ---


class Whisper:
    """A loaded Whisper model that transcribes one chunk (<= 30 s) at a time."""

    def __init__(self, name, device, path):
        from faster_whisper import WhisperModel
        from faster_whisper.tokenizer import Tokenizer
        from faster_whisper.transcribe import get_suppressed_tokens

        self.name = name
        self.device = device
        self.model = WhisperModel(
            path,
            device=device,
            # int8 GEMMs aren't supported on every GPU (e.g. RTX 50xx): fp16 is
            compute_type="float16" if device == "cuda" else "int8",
            cpu_threads=min(os.cpu_count() or 4, 8),
        )
        self._tokenizer_cls = Tokenizer
        self._suppress = list(get_suppressed_tokens(self._tokenizer("en"), [-1]))

    def _tokenizer(self, language):
        m = self.model
        return self._tokenizer_cls(
            m.hf_tokenizer, m.model.is_multilingual, task="transcribe", language=language
        )

    def warm_up(self):
        """The first call is slow (allocations, kernel setup): do it now."""
        self.transcribe(np.zeros(16000, np.float32), "en")  # 1 s of silence

    def transcribe(self, audio, language=None, prompt=""):
        """audio: float32, 16 kHz mono, <= 30 s. language None = detect it."""
        from faster_whisper.audio import pad_or_trim

        m = self.model
        # encode once: language detection and decoding both reuse the result
        encoded = m.encode(pad_or_trim(m.feature_extractor(audio)))
        if language is None:
            language = self._detect_language(encoded)
        tokenizer = self._tokenizer(language)
        prefix = []
        if prompt:
            prefix = [tokenizer.sot_prev] + tokenizer.encode(" " + prompt.strip())
        result = m.model.generate(
            encoded,
            [prefix + list(tokenizer.sot_sequence) + [tokenizer.no_timestamps]],
            beam_size=BEAM_SIZE,
            max_length=448,
            return_scores=True,
            return_no_speech_prob=True,
            suppress_blank=True,
            suppress_tokens=self._suppress,
        )[0]
        if result.no_speech_prob > 0.6 and result.scores[0] < -1.0:
            return ""  # Whisper's own verdict: this was noise, not speech
        tokens = [t for t in result.sequences_ids[0] if t < tokenizer.eot]
        return tokenizer.decode(tokens).strip()

    def _detect_language(self, encoded):
        """Most likely language, preferring the ones offered in the menu."""
        ranked = self.model.model.detect_language(encoded)[0]  # [("<|de|>", p), ...]
        for token, _ in ranked:
            if token[2:-2] in config.LANGUAGES:
                return token[2:-2]
        return ranked[0][0][2:-2]


class Echo:
    """A stand-in model for `bettervoice --check`: shows the process starts."""

    def __init__(self, name, device, path):
        self.name, self.device = name, device

    def warm_up(self):
        pass

    def transcribe(self, audio, language=None, prompt=""):
        return str(len(audio))


# ---------------------------------------------------------------- process ---


def serve(conn, name, device, path, model="bettervoice.stt.local_worker:Whisper"):
    """The worker process: load the model, then transcribe what the app sends.

    model names the class to load ("module:class"); tests pass a stand-in.
    """
    try:
        if device == "cuda":
            prepare_cuda()
        module, _, cls = model.partition(":")
        whisper = getattr(importlib.import_module(module), cls)(name, device, path)
        whisper.warm_up()
    except Exception as e:
        conn.send(("error", f"{type(e).__name__}: {e}"))
        return
    conn.send(("ready", device))
    while True:
        try:
            request = conn.recv()
        except (EOFError, OSError):
            return  # the app is gone
        if request is None:
            return
        audio, language, prompt = request
        try:
            reply = ("text", whisper.transcribe(np.frombuffer(audio, np.float32), language,
                                                prompt))
        except Exception as e:
            reply = ("error", f"{type(e).__name__}: {e}")
        try:
            conn.send(reply)
        except (EOFError, OSError):
            return
