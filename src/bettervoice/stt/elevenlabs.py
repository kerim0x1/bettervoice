"""ElevenLabs Scribe: finished audio is transcribed with the batch API."""

import urllib.request

from bettervoice import brand, config
from bettervoice.stt.audio import to_pcm16
from bettervoice.stt.chunked import Transcriber
from bettervoice.stt.errors import MissingKey
from bettervoice.stt.net import HttpClient, check_status, multipart

PROVIDER = "ElevenLabs"
HOST = "api.elevenlabs.io"
PATH = "/v1/speech-to-text"

_client = HttpClient(HOST, PROVIDER)


class ElevenLabsTranscriber(Transcriber):
    # one request per dictation unless it's long: fewer cuts, more context
    min_chunk_s = 20
    max_chunk_s = 300
    min_pause_s = 0.7

    def __init__(self):
        self.key = config.get("elevenlabs_key")
        if not self.key:
            raise MissingKey(f"{PROVIDER}: API key missing")
        self.model = config.get("elevenlabs_model")

    def prepare(self):
        _client.warm()

    def transcribe(self, audio, language, prompt):
        fields = {
            "model_id": self.model,
            "file_format": "pcm_s16le_16",  # raw 16 kHz PCM: skips decoding, lower latency
            "tag_audio_events": "false",  # no "(laughter)" in dictated text
        }
        if language:
            fields["language_code"] = language
        body, content_type = multipart(
            fields, {"file": ("audio.pcm", to_pcm16(audio), "application/octet-stream")}
        )
        data = _client.request(
            "POST", PATH, body, {"xi-api-key": self.key, "Content-Type": content_type}
        )
        return (data.get("text") or "").strip()


def check_key(key):
    """True if ElevenLabs accepts the key, False if not, None if unreachable.

    Sends a request without audio: rejected keys get 401, valid ones a
    validation error, and nothing is transcribed or billed.
    """
    body, content_type = multipart({"model_id": config.get("elevenlabs_model")}, {})
    request = urllib.request.Request(
        f"https://{HOST}{PATH}", data=body, method="POST",
        headers={"xi-api-key": key, "Content-Type": content_type,
                 "User-Agent": brand.USER_AGENT},
    )
    status = check_status(request)
    if status is None or status >= 500:
        return None
    return status not in (401, 403)
