"""Paths, persisted settings, engines and languages.

Settings live as KEY=value lines in %APPDATA%\\BetterVoice\\.env (a .env in
the repository root is read too, for development). Real environment
variables always win.
"""

import os
import shutil
import sys
import threading

# ----------------------------------------------------------------- paths ---

if getattr(sys, "frozen", False):  # the packaged app: next to BetterVoice.exe
    APP_DIR = os.path.dirname(sys.executable)
else:  # a source checkout: the repository root (src/bettervoice/../..)
    APP_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_APPDATA = os.environ.get("APPDATA", APP_DIR)
CONFIG_DIR = os.path.join(_APPDATA, "BetterVoice")
LEGACY_DIR = os.path.join(_APPDATA, "Dictation")  # the data folder before the rename
CONFIG_ENV = os.path.join(CONFIG_DIR, ".env")
LOG_PATH = os.path.join(CONFIG_DIR, "bettervoice.log")
MODELS_DIR = os.path.join(CONFIG_DIR, "models")


def prepare_data_dir():
    """Create the data folder; on the first start after the rename, take over
    the settings and models of the old one. Called when the app starts, never
    on import, so tests and tools don't touch real user data."""
    if not os.path.exists(CONFIG_DIR) and os.path.isdir(LEGACY_DIR):
        os.makedirs(CONFIG_DIR)
        legacy_env = os.path.join(LEGACY_DIR, ".env")
        if os.path.exists(legacy_env):
            shutil.copy2(legacy_env, CONFIG_ENV)  # copied: an old version keeps working
            _load_env()
        try:
            os.replace(os.path.join(LEGACY_DIR, "models"), MODELS_DIR)  # moved: gigabytes
        except OSError:
            pass  # none there, or in use: downloaded again when needed
    os.makedirs(CONFIG_DIR, exist_ok=True)


# --------------------------------------------------------------- engines ---

LOCAL, DEEPGRAM, ELEVENLABS, OPENROUTER = "local", "deepgram", "elevenlabs", "openrouter"

# engine -> (menu label, setting holding its API key or None)
ENGINES = {
    LOCAL: ("Local (offline)", None),
    DEEPGRAM: ("Deepgram", "deepgram_key"),
    ELEVENLABS: ("ElevenLabs", "elevenlabs_key"),
    OPENROUTER: ("OpenRouter", "openrouter_key"),
}

# ------------------------------------------------------------- languages ---

AUTO = "multi"  # auto-detect (Deepgram's name for it)

# code -> menu label; the codes work for every engine
LANGUAGES = {
    AUTO: "Automatic",
    "en": "English",
    "de": "German",
    "fr": "French",
    "es": "Spanish",
    "it": "Italian",
    "pt": "Portuguese",
    "nl": "Dutch",
    "pl": "Polish",
    "tr": "Turkish",
    "ru": "Russian",
    "zh": "Chinese",
    "ja": "Japanese",
    "ar": "Arabic",
}


def _is_cjk(ch):
    return "\u3000" <= ch <= "\u9fff" or "\uff00" <= ch <= "\uffef"


def join_transcripts(parts):
    """Join recognized pieces; Chinese and Japanese are written without spaces."""
    text = ""
    for part in parts:
        part = part.strip()
        if not part:
            continue
        if text and not (_is_cjk(text[-1]) or _is_cjk(part[0])):
            text += " "
        text += part
    return text


# ----------------------------------------------------------- local models ---

LOCAL_AUTO = "auto"  # large-v3-turbo on an NVIDIA GPU, small on the CPU

# Whisper model -> (menu label, download size)
LOCAL_MODELS = {
    LOCAL_AUTO: ("Automatic (recommended)", ""),
    "base": ("Fast", "150 MB"),
    "small": ("Balanced", "490 MB"),
    "large-v3-turbo": ("Best quality", "1.6 GB"),
}

# -------------------------------------------------------------- settings ---

KEY_PLACEHOLDER = "paste_your_key_here"

# setting -> (env/.env names, first one is written; default)
_SETTINGS = {
    "engine": (("DICTATE_ENGINE",), None),  # default: see get()
    "language": (("DICTATE_LANGUAGE",), AUTO),
    "polish": (("DICTATE_POLISH",), "0"),
    "setup_done": (("DICTATE_SETUP_DONE",), "0"),
    "local_model": (("DICTATE_LOCAL_MODEL",), LOCAL_AUTO),
    "deepgram_key": (("DEEPGRAM_API_KEY",), ""),
    "deepgram_model": (("DEEPGRAM_MODEL", "DICTATE_MODEL"), "nova-3"),
    "elevenlabs_key": (("ELEVENLABS_API_KEY",), ""),
    "elevenlabs_model": (("ELEVENLABS_MODEL",), "scribe_v2"),
    "openrouter_key": (("OPENROUTER_API_KEY",), ""),
    "openrouter_model": (("OPENROUTER_MODEL",), "google/gemini-3.8-flash"),
    "polish_model": (("OPENROUTER_POLISH_MODEL",), "google/gemini-3.5-flash-lite"),
}

_lock = threading.Lock()


def _load_env():
    """Env vars win; then %APPDATA%\\BetterVoice\\.env; then the repository's .env."""
    for path in (CONFIG_ENV, os.path.join(APP_DIR, ".env")):
        if not os.path.exists(path):
            continue
        with open(path, encoding="utf-8-sig") as f:  # -sig: tolerate BOM
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                value = value.split(" #")[0].strip().strip('"').strip("'")
                if value and value != KEY_PLACEHOLDER:
                    os.environ.setdefault(key.strip(), value)


_load_env()


def get(name):
    env_names, default = _SETTINGS[name]
    for env_name in env_names:
        value = os.environ.get(env_name)
        if value:
            break
    else:
        value = default
    if name == "engine":
        if value == "cloud":  # the only cloud engine before ElevenLabs/OpenRouter
            value = DEEPGRAM
        if value not in ENGINES:
            value = DEEPGRAM if get("deepgram_key") else LOCAL
    return value


def set(name, value):  # noqa: A001 - config.set() reads naturally
    """Change a setting for this run and persist it to %APPDATA%."""
    env_names, _ = _SETTINGS[name]
    with _lock:
        os.environ[env_names[0]] = value
        for legacy in env_names[1:]:
            os.environ.pop(legacy, None)
        lines = []
        if os.path.exists(CONFIG_ENV):
            with open(CONFIG_ENV, encoding="utf-8-sig") as f:
                lines = [
                    line for line in f.read().splitlines()
                    if line.partition("=")[0].strip() not in env_names
                ]
        lines.insert(0, f"{env_names[0]}={value}")
        os.makedirs(os.path.dirname(CONFIG_ENV), exist_ok=True)
        with open(CONFIG_ENV, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")


def enabled(name):
    return get(name) == "1"


def key_setting(engine):
    """Name of the setting holding the engine's API key, or None."""
    return ENGINES[engine][1]


def has_key(engine):
    setting = key_setting(engine)
    return setting is None or bool(get(setting))


def engine_label(engine):
    return ENGINES[engine][0]
