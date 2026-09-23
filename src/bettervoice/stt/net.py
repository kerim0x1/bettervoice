"""Small HTTPS helpers for the batch engines (standard library only)."""

import http.client
import json
import logging
import ssl
import threading
import urllib.error
import urllib.request
import uuid

from bettervoice import brand
from bettervoice.stt.errors import AuthError, SttError

log = logging.getLogger(__name__)

REQUEST_TIMEOUT = 60  # s; long dictations take a while to upload and transcribe


def _error_detail(data):
    """The provider's own error text, from the usual JSON shapes."""
    try:
        body = json.loads(data)
    except (ValueError, TypeError):
        return data[:200].decode("utf-8", "replace") if data else ""
    shapes = (("detail", "message"), ("error", "message"), ("detail",), ("message",), ("error",))
    for path in shapes:
        value = body
        for part in path:
            value = value.get(part) if isinstance(value, dict) else None
        if isinstance(value, str):
            return value
    return str(body)[:200]


def raise_for_status(provider, status, data):
    if status < 300:
        return
    detail = f"HTTP {status}: {_error_detail(data)}"
    if status in (401, 403):
        raise AuthError(f"{provider}: invalid API key", detail)
    if status == 402:
        message = "out of credit"
    elif status == 429:
        message = "rate limited – try again shortly"
    elif status >= 500:
        message = "service unavailable"
    else:
        message = "request rejected"
    raise SttError(f"{provider}: {message}", detail)


def multipart(fields, files):
    """(body, content type) for a multipart/form-data upload.

    files: name -> (filename, bytes, content type)
    """
    boundary = uuid.uuid4().hex
    parts = []
    for name, value in fields.items():
        parts.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n'
            f"{value}\r\n".encode()
        )
    for name, (filename, data, content_type) in files.items():
        parts.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"; '
            f'filename="{filename}"\r\nContent-Type: {content_type}\r\n\r\n'.encode()
            + data + b"\r\n"
        )
    parts.append(f"--{boundary}--\r\n".encode())
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


class HttpClient:
    """Keeps one HTTPS connection to a host open between requests.

    warm() connects in the background while the user is still speaking, so
    the transcription request doesn't wait for the TLS handshake.
    """

    def __init__(self, host, provider, secure=True):
        self.host = host
        self.provider = provider
        self._connection_class = (
            http.client.HTTPSConnection if secure else http.client.HTTPConnection  # tests
        )
        self._conn = None
        self._lock = threading.Lock()

    def warm(self):
        threading.Thread(target=self._warm, daemon=True).start()

    def _warm(self):
        with self._lock:
            try:
                self._connect()
            except OSError as e:
                log.info("%s: pre-connect failed: %s", self.provider, e)
                self._close()

    def _connect(self):
        if self._conn is None:
            self._conn = self._connection_class(self.host, timeout=REQUEST_TIMEOUT)
        if self._conn.sock is None:
            self._conn.connect()

    def _close(self):
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def request(self, method, path, body=None, headers=None):
        """-> parsed JSON; raises SttError with a user-facing message."""
        with self._lock:
            for attempt in (1, 2):
                reused = self._conn is not None and self._conn.sock is not None
                try:
                    self._connect()
                    headers = {"User-Agent": brand.USER_AGENT, **(headers or {})}
                    self._conn.request(method, path, body=body, headers=headers)
                    response = self._conn.getresponse()
                    data = response.read()
                    status = response.status
                    if response.will_close:
                        self._close()
                    break
                except (http.client.RemoteDisconnected, ConnectionError,
                        http.client.CannotSendRequest, http.client.ResponseNotReady,
                        ssl.SSLEOFError) as e:
                    # ConnectionError covers reset/aborted (WinError 10053)/broken pipe
                    self._close()
                    if reused and attempt == 1:
                        continue  # the server dropped the idle connection: retry once
                    raise SttError(f"{self.provider}: no connection", str(e)) from e
                except TimeoutError as e:
                    self._close()
                    raise SttError(f"{self.provider}: no response", str(e)) from e
                except OSError as e:
                    self._close()
                    raise SttError(f"{self.provider}: no connection", str(e)) from e
        raise_for_status(self.provider, status, data)
        try:
            return json.loads(data)
        except ValueError:
            raise SttError(f"{self.provider}: unexpected response", data[:200]) from None

    def post_json(self, path, payload, headers):
        headers = {**headers, "Content-Type": "application/json"}
        return self.request("POST", path, json.dumps(payload).encode(), headers)


def check_status(request, timeout=10):
    """Send a one-off request to test a key: -> HTTP status, or None if unreachable."""
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status
    except urllib.error.HTTPError as e:
        return e.code
    except OSError:  # includes URLError and timeouts
        return None
