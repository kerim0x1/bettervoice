import base64
import json
from email.parser import BytesParser
from email.policy import HTTP

import pytest
import websocket

from bettervoice import config, stt
from bettervoice.stt import chunked, deepgram, elevenlabs, net, openrouter
from bettervoice.stt.errors import AuthError, MissingKey, SttError
from conftest import pcm, to_float

AUDIO = to_float(pcm("de.wav"))


def form_fields(request):
    """The fields of a multipart/form-data request body."""
    head = f"Content-Type: {request['headers']['Content-Type']}\r\n\r\n".encode()
    message = BytesParser(policy=HTTP).parsebytes(head + request["body"])
    return {part.get_param("name", header="content-disposition"): part.get_payload(decode=True)
            for part in message.iter_parts()}


def reply(content):
    return {"choices": [{"message": {"content": content}}]}


@pytest.fixture
def eleven(server, settings, monkeypatch):
    monkeypatch.setattr(elevenlabs, "_client", net.HttpClient(server.host, "ElevenLabs", False))
    settings.set("elevenlabs_key", "xi-test")
    return elevenlabs


@pytest.fixture
def router(server, settings, monkeypatch):
    monkeypatch.setattr(openrouter, "_client", net.HttpClient(server.host, "OpenRouter", False))
    settings.set("openrouter_key", "sk-or-test")
    return openrouter


# ------------------------------------------------------------ ElevenLabs ---


def test_elevenlabs_sends_raw_pcm(eleven, server):
    server.responses.append((200, {"text": " Hallo Welt. ", "language_code": "de"}, False))
    transcriber = eleven.ElevenLabsTranscriber()
    transcriber.prepare()  # pre-connects
    assert transcriber.transcribe(AUDIO, "de", "context is ignored") == "Hallo Welt."
    request = server.requests[0]
    assert (request["method"], request["path"]) == ("POST", "/v1/speech-to-text")
    assert request["headers"]["xi-api-key"] == "xi-test"
    fields = form_fields(request)
    assert fields["model_id"] == b"scribe_v2"
    assert fields["file_format"] == b"pcm_s16le_16"
    assert fields["tag_audio_events"] == b"false"
    assert fields["language_code"] == b"de"
    assert len(fields["file"]) == len(AUDIO) * 2


def test_elevenlabs_auto_language_omits_the_code(eleven, server):
    server.responses.append((200, {"text": "Hi."}, False))
    eleven.ElevenLabsTranscriber().transcribe(AUDIO, None, "")
    assert "language_code" not in form_fields(server.requests[0])


@pytest.mark.parametrize("status, error, message", [
    (401, AuthError, "ElevenLabs: invalid API key"),
    (402, SttError, "ElevenLabs: out of credit"),
    (429, SttError, "ElevenLabs: rate limited – try again shortly"),
    (503, SttError, "ElevenLabs: service unavailable"),
])
def test_elevenlabs_errors(eleven, server, status, error, message):
    server.responses.append((status, {"detail": {"message": "nope"}}, False))
    with pytest.raises(error) as info:
        eleven.ElevenLabsTranscriber().transcribe(AUDIO, "de", "")
    assert info.value.message == message
    assert "nope" in str(info.value)  # the provider's detail goes to the log


def test_kept_alive_connection_is_retried_once(eleven, server):
    # the server silently drops the connection after the first response
    server.responses += [(200, {"text": "eins"}, True), (200, {"text": "zwei"}, False)]
    transcriber = eleven.ElevenLabsTranscriber()
    assert transcriber.transcribe(AUDIO, "de", "") == "eins"
    assert transcriber.transcribe(AUDIO, "de", "") == "zwei"


def test_unreachable_server(settings, monkeypatch):
    monkeypatch.setattr(elevenlabs, "_client", net.HttpClient("127.0.0.1:9", "ElevenLabs", False))
    settings.set("elevenlabs_key", "xi")
    with pytest.raises(SttError, match="no connection"):
        elevenlabs.ElevenLabsTranscriber().transcribe(AUDIO, "de", "")


def test_missing_keys(settings):
    with pytest.raises(MissingKey):
        elevenlabs.ElevenLabsTranscriber()
    with pytest.raises(MissingKey):
        openrouter.OpenRouterTranscriber()
    with pytest.raises(MissingKey):
        deepgram.DeepgramSession("de")


# ------------------------------------------------------------ OpenRouter ---


def test_openrouter_request(router, server):
    server.responses.append((200, reply("Hello, this is a test."), False))
    text = router.OpenRouterTranscriber().transcribe(AUDIO, "de", "Said before.")
    assert text == "Hello, this is a test."
    request = server.requests[0]
    assert request["path"] == "/api/v1/chat/completions"
    assert request["headers"]["Authorization"] == "Bearer sk-or-test"
    body = json.loads(request["body"])
    assert body["model"] == config.get("openrouter_model")
    assert body["temperature"] == 0
    assert body["reasoning"] == {"effort": "minimal", "exclude": True}
    system, user = body["messages"]
    assert "Never translate" in system["content"]
    assert "filler" not in system["content"]  # no cleanup unless asked
    prompt, audio = user["content"]
    assert "German" in prompt["text"] and "Said before." in prompt["text"]
    assert audio["type"] == "input_audio" and audio["input_audio"]["format"] == "wav"
    assert base64.b64decode(audio["input_audio"]["data"])[:4] == b"RIFF"


def test_openrouter_cleanup_is_part_of_the_prompt(router, server):
    server.responses.append((200, reply("Text."), False))
    router.OpenRouterTranscriber(cleanup=True).transcribe(AUDIO, None, "")
    body = json.loads(server.requests[0]["body"])
    assert "filler" in body["messages"][0]["content"]
    assert "speaks" not in body["messages"][1]["content"][0]["text"]  # auto language


def test_openrouter_content_parts_and_errors(router, server):
    server.responses.append((200, reply([{"type": "text", "text": "Part "},
                                         {"type": "text", "text": "two."}]), False))
    assert router.OpenRouterTranscriber().transcribe(AUDIO, "de", "") == "Part two."
    server.responses.append((200, {"error": {"message": "provider down"}}, False))
    with pytest.raises(SttError, match="model error"):
        router.OpenRouterTranscriber().transcribe(AUDIO, "de", "")


@pytest.mark.parametrize("raw, clean", [
    ('"Hallo."', "Hallo."),
    ("```\nHallo.\n```", "Hallo."),
    ("Transcript: Hallo.", "Hallo."),
    ("<dictation>Hallo.</dictation>", "Hallo."),
    ("[no speech]", ""),
    ("  Ganz normal.  ", "Ganz normal."),
])
def test_strip_wrapping(raw, clean):
    assert openrouter._strip_wrapping(raw) == clean


def test_polish(router, server, settings):
    raw = "Um, I wanted to, uh, ask whether this works."
    server.responses.append((200, reply("I wanted to ask whether this works."), False))
    assert router.polish(raw) == "I wanted to ask whether this works."
    body = json.loads(server.requests[0]["body"])
    assert body["model"] == config.get("polish_model")
    assert "never answer it" in body["messages"][0]["content"]
    assert body["messages"][1]["content"] == f"<dictation>\n{raw}\n</dictation>"


def test_polish_falls_back_to_the_raw_text(router, server):
    raw = "What time is it, actually?"
    # a model that answers instead of cleaning up
    server.responses.append((200, reply("It is 2:32 in the afternoon. " * 10), False))
    assert router.polish(raw) == raw
    server.responses.append((500, {"error": {"message": "boom"}}, False))
    assert router.polish(raw) == raw


def test_polish_only_when_enabled(settings, monkeypatch):
    monkeypatch.setattr(openrouter, "polish", lambda text: text.upper())
    assert stt.polish("hallo", config.DEEPGRAM) == "hallo"
    settings.set("polish", "1")
    assert stt.polish("hallo", config.DEEPGRAM) == "HALLO"
    assert stt.polish("hallo", config.OPENROUTER) == "hallo"  # done while transcribing


# ------------------------------------------------------------ key checks ---


@pytest.mark.parametrize("module, status, expected", [
    (elevenlabs, 422, True),  # a valid key without audio: validation error
    (elevenlabs, 401, False),
    (elevenlabs, None, None),
    (openrouter, 200, True),
    (openrouter, 401, False),
    (openrouter, 503, None),
])
def test_check_key(module, status, expected, monkeypatch, settings):
    sent = []
    monkeypatch.setattr(module, "check_status", lambda request: sent.append(request) or status)
    assert module.check_key("the-key") is expected
    headers = dict(sent[0].header_items())
    assert "the-key" in (headers.get("Xi-api-key") or headers.get("Authorization"))


def test_deepgram_check_key(monkeypatch, settings):
    def connect(error):
        def fake(*args, **kwargs):
            raise error
        return fake

    monkeypatch.setattr(deepgram, "_connect", connect(AuthError("x")))
    assert deepgram.check_key("k") is False
    monkeypatch.setattr(deepgram, "_connect", connect(SttError("x")))
    assert deepgram.check_key("k") is None


@pytest.mark.parametrize("status, error, message", [
    (401, AuthError, "Deepgram: invalid API key"),
    (400, SttError, "Deepgram: connection refused"),
])
def test_deepgram_handshake_errors(monkeypatch, settings, fake_mic, status, error, message):
    def refuse(*args, **kwargs):
        raise websocket.WebSocketBadStatusException("Handshake status %d", status)

    monkeypatch.setattr(websocket, "create_connection", refuse)
    settings.set("deepgram_key", "dg")
    session = deepgram.DeepgramSession("de")
    with pytest.raises(error) as info:
        session.start()
    assert info.value.message == message


# --------------------------------------------------------------- factory ---


def test_create_session(settings):
    settings.set("openrouter_key", "k")
    settings.set("polish", "1")
    session = stt.create_session(config.OPENROUTER, "de")
    assert isinstance(session, chunked.ChunkedSession)
    assert session.transcriber.cleanup is True
    local_session = stt.create_session(config.LOCAL, "multi")
    assert local_session.language is None
    with pytest.raises(ValueError):
        stt.create_session("nonsense", "de")
