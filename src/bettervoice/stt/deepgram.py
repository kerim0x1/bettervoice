"""Deepgram: the microphone is streamed live, text arrives while speaking."""

import json
import logging
import queue
import select
import threading

import websocket

from bettervoice import brand, config
from bettervoice.mic import SAMPLE_RATE, Microphone
from bettervoice.stt.errors import AuthError, MissingKey, SttError

log = logging.getLogger(__name__)

PROVIDER = "Deepgram"
RECV_POLL_S = 0.1


def _url(language, model):
    return (
        "wss://api.deepgram.com/v1/listen"
        f"?model={model}"
        f"&language={language}"
        "&encoding=linear16"
        f"&sample_rate={SAMPLE_RATE}"
        "&channels=1"
        "&smart_format=true"
        "&interim_results=true"
    )


def _connect(key, language, model, timeout=10):
    try:
        return websocket.create_connection(
            _url(language, model),
            header=[f"Authorization: Token {key}", f"User-Agent: {brand.USER_AGENT}"],
            timeout=timeout,
        )
    except websocket.WebSocketBadStatusException as e:
        detail = str(e).split(" -+-+- ")[0]  # without the response headers
        if e.status_code in (401, 403):
            raise AuthError(f"{PROVIDER}: invalid API key", detail) from e
        raise SttError(f"{PROVIDER}: connection refused", detail) from e
    except (OSError, websocket.WebSocketException) as e:
        raise SttError(f"{PROVIDER}: no connection", str(e)) from e


def check_key(key):
    """True if Deepgram accepts the key for streaming, False if it rejects it,
    None if Deepgram can't be reached. Opening a stream costs nothing."""
    try:
        _connect(key, config.AUTO, config.get("deepgram_model"), timeout=8).close()
        return True
    except AuthError:
        return False
    except SttError:
        return None


class DeepgramSession:
    """One dictation: mic -> Deepgram live websocket -> transcript."""

    def __init__(self, language, on_level=None):
        self.key = config.get("deepgram_key")
        if not self.key:
            raise MissingKey(f"{PROVIDER}: API key missing")
        self.language = language
        self.model = config.get("deepgram_model")
        self.mic = Microphone(self._on_audio, on_level)
        self.audio_queue = queue.Queue()
        self.finals = []
        self.error = None
        self.ws = None
        self.sender = None
        self.receiver = None

    def start(self):
        # start the mic first: the queue buffers audio while the websocket
        # connects, so the first words aren't lost
        self.mic.start()
        try:
            self.ws = _connect(self.key, self.language, self.model)
        except SttError:
            self.mic.stop()
            raise
        # the timeout is for connecting only; the receiver waits via select()
        self.ws.settimeout(None)
        self.receiver = threading.Thread(target=self._receive_loop, daemon=True)
        self.receiver.start()
        self.sender = threading.Thread(target=self._send_loop, daemon=True)
        self.sender.start()

    def _on_audio(self, chunk):
        self.audio_queue.put(chunk)

    def _send_loop(self):
        while True:
            chunk = self.audio_queue.get()
            if chunk is None:
                break
            try:
                self.ws.send_binary(chunk)
            except Exception as e:
                self.error = SttError(f"{PROVIDER}: connection lost", str(e))
                return
        try:
            self.ws.send(json.dumps({"type": "CloseStream"}))
        except Exception:
            pass

    def _readable(self):
        """Wait up to RECV_POLL_S for data.

        Python 3.13 serializes reads and writes on an SSL socket, so a recv()
        that blocks while the user pauses would also block sending audio.
        """
        sock = self.ws.sock
        if sock is None:
            raise websocket.WebSocketConnectionClosedException("socket closed")
        return sock.pending() or select.select([sock], [], [], RECV_POLL_S)[0]

    def _receive_loop(self):
        try:
            while True:
                if not self._readable():
                    continue
                msg = self.ws.recv()
                if not msg:
                    break  # server closed the stream
                data = json.loads(msg)
                if data.get("type") != "Results" or not data.get("is_final"):
                    continue
                transcript = data["channel"]["alternatives"][0].get("transcript", "")
                if transcript:
                    self.finals.append(transcript)
        except (websocket.WebSocketConnectionClosedException, OSError, ValueError):
            pass  # normal shutdown (ValueError: select() on a closed socket)
        except Exception as e:
            self.error = SttError(f"{PROVIDER}: receive error", str(e))

    def finish(self):
        """Stop recording, wait for the last results, return the transcript.

        Text recognized before a connection error is still returned; the
        error is only raised if nothing was recognized at all.
        """
        self.mic.stop()
        self.audio_queue.put(None)  # sender flushes queue, then sends CloseStream
        self.sender.join(timeout=5)
        self.receiver.join(timeout=6)  # server sends remaining finals, then closes
        text = config.join_transcripts(self.finals)
        error = self.error
        self._close()
        if error is not None:
            if not text:
                raise error
            log.warning("connection error, keeping the text recognized so far: %s", error)
        return text

    def abort(self):
        """Stop recording and drop everything; returns immediately."""
        self.mic.stop()
        self.audio_queue.put(None)
        try:
            self.ws.shutdown()  # unlike close(), doesn't wait for the server
        except Exception:
            pass

    def _close(self):
        try:
            self.ws.close()
        except Exception:
            pass
