"""Local recognition with Whisper (faster-whisper / CTranslate2), fully offline.

The model is downloaded once (with progress). It runs in a process of its own
(local_worker.py), started when a dictation begins - the model loads while
the user speaks - and ended a few minutes after the last dictation, so the
memory it and CUDA take is given back while BetterVoice sits idle.
"""

import json
import logging
import multiprocessing
import os
import sys
import threading
import time
import urllib.request

import numpy as np

from bettervoice import brand, config
from bettervoice.stt import local_worker
from bettervoice.stt.chunked import Transcriber
from bettervoice.stt.errors import SttError

log = logging.getLogger(__name__)

GPU_AUTO_MODEL = "large-v3-turbo"
CPU_AUTO_MODEL = "small"
IDLE_UNLOAD_S = 5 * 60  # the model is freed this long after the last dictation
IDLE_CHECK_S = 15
LOAD_TIMEOUT_S = 600  # a large model on a slow CPU

HUB = "https://huggingface.co"

MODEL_REPOS = {
    "base": "Systran/faster-whisper-base",
    "small": "Systran/faster-whisper-small",
    "large-v3-turbo": "mobiuslabsgmbh/faster-whisper-large-v3-turbo",
}
_MODEL_FILES = ("config.json", "preprocessor_config.json", "model.bin", "tokenizer.json")


# ------------------------------------------------------------------- GPU ---


def gpu_status():
    """"ok", "no_cublas" (NVIDIA GPU but CUDA libraries missing) or "none".

    Only looks: CUDA itself is loaded by the worker process, never here.
    """
    if sys.platform == "darwin":
        return "none"  # CTranslate2 has no Metal backend: the CPU it is
    import ctranslate2

    if ctranslate2.get_cuda_device_count() == 0:
        return "none"
    missing = [lib for lib in local_worker.CUDA_LIBS if not local_worker.find_cuda_lib(lib)]
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


class WorkerModel:
    """The loaded model, in a process of its own (local_worker.serve).

    Creating one starts the process and blocks until the model is loaded;
    close() ends it, which frees its memory and the GPU's.
    """

    def __init__(self, name, device, path, model=None):
        self.name, self.device = name, device
        self._lock = threading.Lock()
        ctx = multiprocessing.get_context("spawn")  # a fresh interpreter: no tk, no threads
        self._conn, child = ctx.Pipe()
        args = (child, name, device, path) + ((model,) if model else ())
        self._process = ctx.Process(target=local_worker.serve, args=args, daemon=True,
                                    name="BetterVoice recognition")
        self._process.start()
        child.close()
        try:
            if not self._conn.poll(LOAD_TIMEOUT_S):
                raise SttError("Local model failed to load", "it took too long")
            kind, detail = self._conn.recv()
        except (EOFError, OSError) as e:
            self.close()
            raise SttError("Local model failed to load",
                           f"the recognition process ended: {e!r}") from e
        except SttError:
            self.close()
            raise
        if kind != "ready":
            self.close()
            raise SttError("Local model failed to load", detail)

    def transcribe(self, audio, language=None, prompt=""):
        """audio: float32, 16 kHz mono, <= 30 s. language None = detect it."""
        with self._lock:
            try:
                self._conn.send((np.ascontiguousarray(audio, np.float32).tobytes(), language,
                                 prompt))
                kind, value = self._conn.recv()
            except (EOFError, OSError) as e:
                raise SttError("Local recognition stopped", repr(e)) from e
        if kind != "text":
            raise SttError("Recognition failed", value)
        return value

    def close(self):
        """End the process (after a transcription still running)."""
        with self._lock:
            try:
                self._conn.send(None)
            except OSError:
                pass
            self._process.join(5)
            if self._process.is_alive():
                self._process.terminate()
                self._process.join(5)
            self._conn.close()


class LocalEngine:
    """Owns the local model: downloads it, loads it in its process when a
    dictation starts, and frees it after IDLE_UNLOAD_S without use (setting
    "local_unload"). The status fields are read by the tray and the UI."""

    def __init__(self):
        self.on_status = None  # called (from any thread) when status changes
        self.state = "off"  # off | downloading | loading | ready | error
        self.status = "off"  # a short text for the tray and the UI
        self.progress = None  # 0..1 while downloading
        self._lock = threading.Lock()
        self._download_lock = threading.Lock()  # a fetch and a load may both want it
        self._wanted = None  # model choice currently loaded or loading
        self._whisper = None
        self._error = None
        self._ready = threading.Event()
        self._last_used = time.monotonic()
        self._idle_watch = None

    @property
    def ready(self):
        return self.state == "ready"

    @property
    def error_message(self):
        """Why the last load failed (user-facing), or None."""
        return getattr(self._error, "message", None) if self.state == "error" else None

    def has_model(self, choice):
        """Whether the model for this choice is downloaded."""
        return model_path(resolve(choice, gpu_status() == "ok")) is not None

    def fetch(self, choice):
        """Have the model on disk, downloading it in the background if needed,
        without loading it: that happens when a dictation starts."""
        threading.Thread(target=self._fetch_only, args=(choice,), daemon=True).start()

    def load(self, choice):
        """Load this model choice in its process; returns immediately. A
        failed load of the same choice is retried."""
        with self._lock:
            self._last_used = time.monotonic()
            if choice == self._wanted and self.state != "error":
                return
            old, self._whisper = self._whisper, None
            self._wanted = choice
            self._error = None
            self._ready.clear()
            if self._idle_watch is None:
                self._idle_watch = threading.Thread(target=self._watch_idle, daemon=True)
                self._idle_watch.start()
        self._close_later(old)
        self._set("loading", "starting…")
        threading.Thread(target=self._load, args=(choice,), daemon=True).start()

    def unload(self):
        """Free the memory, e.g. when switching to a cloud engine."""
        with self._lock:
            if self._wanted is None:
                return
            old, self._whisper, self._wanted = self._whisper, None, None
            self._error = SttError("The local model is switched off")
            self._ready.set()  # a session still waiting gives up instead of hanging
        self._close_later(old)
        self._set("off", "off")

    def wait(self):
        """The loaded model; blocks while it's still downloading or loading."""
        self._ready.wait()
        with self._lock:
            if self._whisper is None:
                raise self._error or SttError("Local model not available")
            return self._whisper

    def transcribe(self, audio, language, prompt):
        """Transcribe with the loaded model; after an idle unload, load it again."""
        with self._lock:
            unloaded = self._wanted is None
        if unloaded:
            self.load(config.get("local_model"))
        whisper = self.wait()
        self._touch()
        try:
            return whisper.transcribe(audio, language, prompt)
        finally:
            self._touch()

    def _touch(self):
        with self._lock:
            self._last_used = time.monotonic()

    @staticmethod
    def _close_later(whisper):
        if whisper is not None:  # ending a process takes a moment: not on the caller's time
            threading.Thread(target=whisper.close, daemon=True).start()

    def _watch_idle(self):
        while True:
            time.sleep(IDLE_CHECK_S)
            if not config.enabled("local_unload"):
                continue
            with self._lock:
                if (self.state != "ready" or self._whisper is None
                        or time.monotonic() - self._last_used < IDLE_UNLOAD_S):
                    continue
                old, self._whisper, self._wanted = self._whisper, None, None
            log.info("freed the local model after %d minutes without dictation",
                     IDLE_UNLOAD_S // 60)
            self._close_later(old)
            self._set("off", f"{old.name} – loads when you dictate")

    def _fetch_only(self, choice):
        try:
            name = resolve(choice, gpu_status() == "ok")
            self._fetch(name, lambda: self._wanted in (None, choice))
        except Exception as e:
            error = e if isinstance(e, SttError) else SttError("Model download failed", str(e))
            log.error("could not download the local model: %s", error)
            with self._lock:
                if self._wanted is None:  # a load reports its own errors
                    self._error = error
                    self._set("error", "error – see the log")
            return
        with self._lock:
            if self._wanted is None:
                self._error = None
                self._set("off", f"{name} – loads when you dictate")

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
            superseded = not still_wanted()
            if not superseded:
                self._whisper, self._error = whisper, error
                self._last_used = time.monotonic()
                self._ready.set()
        if superseded:  # by another load() or unload() meanwhile
            self._close_later(whisper)
            return
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
                return WorkerModel(name, "cuda", path)
            except SttError as e:
                log.warning("GPU failed, using the CPU instead: %s", e)
                if choice == config.LOCAL_AUTO and name != CPU_AUTO_MODEL:
                    name = CPU_AUTO_MODEL
                    path = self._fetch(name, still_wanted)
        self._set("loading", f"loading {name}…")
        return WorkerModel(name, "cpu", path)

    def _fetch(self, name, still_wanted):
        with self._download_lock:
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
                raise SttError("Model download failed – check your internet connection",
                               str(e)) from e

    def _set(self, state, status, progress=None):
        self.state, self.status, self.progress = state, status, progress
        if self.on_status is not None:
            self.on_status()


ENGINE = LocalEngine()


class LocalTranscriber(Transcriber):
    """Whisper on this computer; waits for the model if it's still loading."""

    min_chunk_s = 6
    max_chunk_s = 25  # Whisper only sees 30 s at a time
    min_pause_s = 0.5

    def prepare(self):
        # the model loads while the user speaks; no-op if it's loaded already
        ENGINE.load(config.get("local_model"))

    def transcribe(self, audio, language, prompt):
        return ENGINE.transcribe(audio, language, prompt)
