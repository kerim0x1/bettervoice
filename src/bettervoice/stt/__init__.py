"""Speech-to-text engines behind one session interface:

    session = create_session(engine, language, on_level)
    session.start()          # start recording; may raise SttError
    text = session.finish()  # stop recording, return the transcript
    session.abort()          # stop recording, drop everything; returns at once

Engine modules are imported lazily, so unused engines cost nothing.
"""

import importlib.util
import sys
import types

# ctranslate2 (under faster-whisper) imports torch and transformers, when
# installed, for its model converters only. We need neither: importing them
# costs ~2 s and brings torch's own CUDA DLLs, which clash with the cuBLAS
# the local engine uses. This must run before faster-whisper is imported.
for _unused in ("torch", "transformers"):
    sys.modules.setdefault(_unused, None)

# faster-whisper imports PyAV when it loads, but only uses it to decode audio
# files, which BetterVoice never does. The packaged app leaves PyAV and its
# ~60 MB of FFmpeg out; an empty module stands in for it there.
if importlib.util.find_spec("av") is None:
    sys.modules.setdefault("av", types.ModuleType("av"))

from bettervoice import config  # noqa: E402

KEY_URLS = {
    config.DEEPGRAM: "https://console.deepgram.com/",
    config.ELEVENLABS: "https://elevenlabs.io/app/settings/api-keys",
    config.OPENROUTER: "https://openrouter.ai/settings/keys",
}


def create_session(engine, language, on_level=None):
    if engine == config.DEEPGRAM:
        from bettervoice.stt.deepgram import DeepgramSession

        return DeepgramSession(language, on_level)
    from bettervoice.stt.chunked import ChunkedSession

    return ChunkedSession(transcriber(engine), language, on_level)


def transcriber(engine):
    if engine == config.LOCAL:
        from bettervoice.stt.local import LocalTranscriber

        return LocalTranscriber()
    if engine == config.ELEVENLABS:
        from bettervoice.stt.elevenlabs import ElevenLabsTranscriber

        return ElevenLabsTranscriber()
    if engine == config.OPENROUTER:
        from bettervoice.stt.openrouter import OpenRouterTranscriber

        # with AI Polish on, the model cleans up while transcribing
        return OpenRouterTranscriber(cleanup=config.enabled("polish"))
    raise ValueError(f"unknown engine {engine!r}")


def check_key(engine, key):
    """True = accepted, False = rejected, None = provider unreachable."""
    if engine == config.DEEPGRAM:
        from bettervoice.stt.deepgram import check_key
    elif engine == config.ELEVENLABS:
        from bettervoice.stt.elevenlabs import check_key
    elif engine == config.OPENROUTER:
        from bettervoice.stt.openrouter import check_key
    else:
        raise ValueError(f"{engine!r} has no key")
    return check_key(key)


def polish(text, engine):
    """Apply AI Polish if it's on (OpenRouter already did it while transcribing)."""
    if not config.enabled("polish") or engine == config.OPENROUTER:
        return text
    from bettervoice.stt.openrouter import polish

    return polish(text)
