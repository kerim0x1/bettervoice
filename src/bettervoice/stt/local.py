"""Local recognition with Whisper (faster-whisper / CTranslate2), fully offline.

The model is downloaded once (with progress), then loaded in the background
and kept in memory. faster-whisper is imported lazily: using only a cloud
engine doesn't pay for it.
"""

import ctypes.util
import glob
import json
import logging
import os
import sys
import threading
import time
import urllib.request

import numpy as np

from bettervoice import brand, config
from bettervoice.mic import SAMPLE_RATE
from bettervoice.stt.chunked import Transcriber
from bettervoice.stt.errors import SttError

log = logging.getLogger(__name__)

BEAM_SIZE = 5
GPU_AUTO_MODEL = "large-v3-turbo"
CPU_AUTO_MODEL = "small"

HUB = "https://huggingface.co"

MODEL_REPOS = {
    "base": "Systran/faster-whisper-base",
    "small": "Systran/faster-whisper-small",
    "large-v3-turbo": "mobiuslabsgmbh/faster-whisper-large-v3-turbo",
}
_MODEL_FILES = ("config.json", "preprocessor_config.json", "model.bin", "tokenizer.json")

# the GPU needs CUDA 12's cuBLAS (pip install nvidia-cublas-cu12); on Windows
# CTranslate2 ships the rest itself, on Linux it also needs cuDNN 9
if sys.platform == "win32":
    _CUDA_LIBS = ("cublas64_12.dll", "cublasLt64_12.dll")
else:
    _CUDA_LIBS = ("libcublas.so.12", "libcublasLt.so.12", "libcudnn.so.9")


# ------------------------------------------------------------------- GPU ---


def _cuda_dll_dirs():
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


def _load_globally(name):
    """Load a CUDA library for CTranslate2: it then finds it by name."""
    for folder in _cuda_dll_dirs():
        path = os.path.join(folder, name)
        if os.path.exists(path):
            try:
                ctypes.CDLL(path, mode=ctypes.RTLD_GLOBAL)
                return True
            except OSError as e:
                log.info("could not load %s: %s", path, e)
    try:
        ctypes.CDLL(name, mode=ctypes.RTLD_GLOBAL)  # installed system-wide
        return True
    except OSError:
        return False


def gpu_status():
    """"ok", "no_cublas" (NVIDIA GPU but CUDA libraries missing) or "none"."""
    if sys.platform == "darwin":
        return "none"  # CTranslate2 has no Metal backend: the CPU it is
    import ctranslate2

    if ctranslate2.get_cuda_device_count() == 0:
        return "none"
    if sys.platform == "win32":
        for d in _cuda_dll_dirs():
            if d not in os.environ["PATH"]:  # CTranslate2 looks the DLLs up via PATH
                os.environ["PATH"] = d + os.pathsep + os.environ["PATH"]
        missing = [lib for lib in _CUDA_LIBS if ctypes.util.find_library(lib) is None]
    else:
        missing = [lib for lib in _CUDA_LIBS if not _load_globally(lib)]
    if missing:
        log.info("GPU found, but not %s: using the CPU", ", ".join(missing))
        return "no_cublas"
    return "ok"


def resolve(choice, gpu):
    """The Whisper model a config.LOCAL_MODELS choice stands for."""
    if choice == config.LOCAL_AUTO:
        return GPU_AUTO_MODEL if gpu else CPU_AUTO_MODEL
    return choice


# -------------------------------------------------------------- download ---


def _model_dir(name):
    return os.path.join(config.MODELS_DIR, name)


def _legacy_path(name):
    """A model fetched by an earlier version into the Hugging Face cache."""
    from faster_whisper.utils import download_model

    try:
        return download_model(name, cache_dir=config.MODELS_DIR, local_files_only=True)
    except Exception:
        return None


def model_path(name):
    """Local folder of a downloaded model, or None."""
    folder = _model_dir(name)
    if os.path.exists(os.path.join(folder, ".complete")):
        return folder
    return _legacy_path(name)


def download(name, on_progress=None):
    """Download a model with byte-exact progress; resumes an interrupted download.

    on_progress(done_bytes, total_bytes) is called from this thread.
    """
    repo = MODEL_REPOS.get(name)
    if repo is None:  # e.g. "medium" set in .env: let faster-whisper fetch it
        from faster_whisper.utils import download_model

        return download_model(name, cache_dir=config.MODELS_DIR)
    listing_request = urllib.request.Request(f"{HUB}/api/models/{repo}/tree/main",
                                             headers={"User-Agent": brand.USER_AGENT})
    with urllib.request.urlopen(listing_request, timeout=20) as r:
        listing = json.load(r)
    files = [
        (f["path"], f["size"]) for f in listing
        if f["type"] == "file"
        and (f["path"] in _MODEL_FILES or f["path"].startswith("vocabulary."))
    ]
    folder = _model_dir(name)
    os.makedirs(folder, exist_ok=True)
    total = sum(size for _, size in files)
    done = 0
    for path, size in files:
        target = os.path.join(folder, path)
        if os.path.exists(target) and os.path.getsize(target) == size:
            done += size
            continue
        partial = target + ".part"
        have = os.path.getsize(partial) if os.path.exists(partial) else 0
        request = urllib.request.Request(
            f"{HUB}/{repo}/resolve/main/{path}",
            headers={"User-Agent": brand.USER_AGENT,
                     **({"Range": f"bytes={have}-"} if have else {})},
        )
        with urllib.request.urlopen(request, timeout=30) as r:
            if have and r.status != 206:  # server ignored the range: start over
                have = 0
            with open(partial, "ab" if have else "wb") as out:
                done += have
                last = 0.0
                while True:
                    block = r.read(1 << 20)
                    if not block:
                        break
                    out.write(block)
                    done += len(block)
                    if on_progress and time.monotonic() - last > 0.1:
                        on_progress(done, total)
                        last = time.monotonic()
        if os.path.getsize(partial) != size:
            got = os.path.getsize(partial)
            raise SttError("Download incomplete", f"{path}: {got} of {size} bytes")
        os.replace(partial, target)
    if on_progress:
        on_progress(total, total)
    with open(os.path.join(folder, ".complete"), "w") as f:
        f.write(repo)
    return folder


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
        self.transcribe(np.zeros(SAMPLE_RATE, np.float32), "en")

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


class LocalEngine:
    """Owns the Whisper model: downloads and loads it in the background and
    keeps it resident. The status fields are read by the tray and the UI."""

    def __init__(self):
        self.on_status = None  # called (from any thread) when status changes
        self.state = "off"  # off | downloading | loading | ready | error
        self.status = "off"  # a short text for the tray and the UI
        self.progress = None  # 0..1 while downloading
        self._lock = threading.Lock()
        self._wanted = None  # model choice currently loaded or loading
        self._whisper = None
        self._error = None
        self._ready = threading.Event()

    @property
    def ready(self):
        return self.state == "ready"

    @property
    def error_message(self):
        """Why the last load failed (user-facing), or None."""
        return getattr(self._error, "message", None) if self.state == "error" else None

    def load(self, choice):
        """Switch to this model choice; returns immediately. A failed load
        of the same choice is retried."""
        with self._lock:
            if choice == self._wanted and self.state != "error":
                return
            self._wanted = choice
            self._whisper = self._error = None
            self._ready.clear()
        self._set("loading", "starting…")
        threading.Thread(target=self._load, args=(choice,), daemon=True).start()

    def unload(self):
        """Free the (V)RAM, e.g. when switching to a cloud engine."""
        with self._lock:
            if self._wanted is None:
                return
            self._wanted = self._whisper = None
            self._error = SttError("The local model is switched off")
            self._ready.set()  # a session still waiting gives up instead of hanging
        self._set("off", "off")

    def wait(self):
        """The loaded model; blocks while it's still downloading or loading."""
        self._ready.wait()
        with self._lock:
            if self._whisper is None:
                raise self._error or SttError("Local model not available")
            return self._whisper

    def _load(self, choice):
        def still_wanted():
            return self._wanted == choice

        try:
            whisper = self._load_whisper(choice, still_wanted)
            error = None
        except SttError as e:
            log.error("could not load the local model: %s", e)
            whisper, error = None, e
        except Exception as e:
            log.exception("could not load the local model")
            whisper, error = None, SttError("Local model failed to load", str(e))
        with self._lock:
            if not still_wanted():
                return  # superseded by another load() or unload()
            self._whisper, self._error = whisper, error
            self._ready.set()
        if whisper is None:
            self._set("error", "error – see the log")
        else:
            device = "GPU" if whisper.device == "cuda" else "CPU"
            log.info("local model ready: %s on %s", whisper.name, device)
            self._set("ready", f"ready – {whisper.name} ({device})")

    def _load_whisper(self, choice, still_wanted):
        gpu = gpu_status() == "ok"
        name = resolve(choice, gpu)
        path = self._fetch(name, still_wanted)
        if gpu:
            try:
                self._set("loading", f"loading {name}…")
                whisper = Whisper(name, "cuda", path)
                whisper.warm_up()
                return whisper
            except Exception as e:
                log.warning("GPU failed, using the CPU instead: %s", e)
                if choice == config.LOCAL_AUTO and name != CPU_AUTO_MODEL:
                    name = CPU_AUTO_MODEL
                    path = self._fetch(name, still_wanted)
        self._set("loading", f"loading {name}…")
        whisper = Whisper(name, "cpu", path)
        whisper.warm_up()
        return whisper

    def _fetch(self, name, still_wanted):
        path = model_path(name)
        if path is not None:
            return path

        def on_progress(done, total):
            if still_wanted():
                self._set("downloading", f"downloading {name}… {done * 100 // total}%",
                          done / total)

        self._set("downloading", f"downloading {name}…", 0.0)
        try:
            return download(name, on_progress)
        except SttError:
            raise
        except OSError as e:
            raise SttError("Model download failed – check your internet connection", str(e)) from e

    def _set(self, state, status, progress=None):
        self.state, self.status, self.progress = state, status, progress
        if self.on_status is not None:
            self.on_status()


ENGINE = LocalEngine()


class LocalTranscriber(Transcriber):
    """Whisper on this PC; waits for the model if it's still loading."""

    min_chunk_s = 6
    max_chunk_s = 25  # Whisper only sees 30 s at a time
    min_pause_s = 0.5

    def prepare(self):
        ENGINE.load(config.get("local_model"))  # no-op if loaded; retries a failed load

    def transcribe(self, audio, language, prompt):
        return ENGINE.wait().transcribe(audio, language, prompt)
