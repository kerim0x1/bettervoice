# Architecture overview

BetterVoice is a Python desktop app for Windows. One process holds four kinds of threads: the tkinter main thread (overlay, setup and settings windows), a keyboard-hook thread, the tray icon's thread, and one worker thread per dictation plus the engines' own helpers.

## Code map

| Path | Responsibility |
| --- | --- |
| `src/bettervoice/app.py` | Entry point, keyboard hook (<kbd>Win</kbd>+<kbd>O</kbd>, <kbd>Esc</kbd>), the dictation flow, pasting, tray menu, single-instance guard. |
| `src/bettervoice/setup_ui.py` | Setup wizard and settings window (CustomTkinter). |
| `src/bettervoice/overlay.py` | The pill next to the text cursor. |
| `src/bettervoice/config.py` | Paths, settings in `%APPDATA%\BetterVoice\.env`, engine and language tables, migration from the old data folder. |
| `src/bettervoice/brand.py` | Name, tagline, colors, the mark (drawn in code), icon path, user agent. |
| `src/bettervoice/mic.py` | 16 kHz mono microphone capture (sounddevice). |
| `src/bettervoice/autostart.py` | The per-user Run key; removes autostart entries of older versions and points autostart at the copy that runs. |
| `src/bettervoice/stt/__init__.py` | The session interface and engine factory, key checks, AI Polish dispatch. |
| `src/bettervoice/stt/deepgram.py` | Live WebSocket streaming. |
| `src/bettervoice/stt/chunked.py` | Recording split at pauses, used by every other engine. |
| `src/bettervoice/stt/local.py` | Whisper: model download, GPU detection, loading, transcription. |
| `src/bettervoice/stt/elevenlabs.py`, `openrouter.py` | The HTTP engines; `openrouter.py` also holds AI Polish. |
| `src/bettervoice/stt/net.py` | A kept-alive HTTPS client, multipart encoding, error mapping. |
| `scripts/` | Brand asset generation, the Windows build (app, zip, installer, checksums), and the release notes. |
| `packaging/bettervoice.iss` | The installer (Inno Setup): per-user install, updates in place, uninstall. |
| `.github/` | CI and release workflows, and the shared build check. |
| `tests/` | Unit, UI smoke, and opt-in integration tests. |

## A dictation, end to end

1. The keyboard hook sees <kbd>Win</kbd>+<kbd>O</kbd>, swallows it, and calls `on_hotkey()`, which starts a `Dictation` on a new thread and asks the tk thread to show the pill.
2. `stt.create_session()` builds the session for the selected engine. Every session offers `start()`, `finish()`, and `abort()`.
3. Deepgram streams microphone chunks over a WebSocket. The other engines use `ChunkedSession`: a worker looks for pauses with the Silero VAD and hands each finished passage to the engine's `Transcriber`, together with the previous text as context.
4. The second <kbd>Win</kbd>+<kbd>O</kbd> ends recording; `finish()` returns the transcript. AI Polish runs if enabled, then `paste_text()` pastes through the clipboard.
5. <kbd>Esc</kbd> calls `cancel()`: the dictation is detached at once, so a new one can start while the old worker winds down and discards its result.

Only the tk thread touches tkinter. Other threads post events to `ui_q`, which the main loop drains every 25 ms; the setup window uses its own queue the same way.

## Engines

A cloud engine is a session (Deepgram) or a `Transcriber` subclass with a splitting policy:

| Engine | Splits after at least | at a pause of | at most |
| --- | --- | --- | --- |
| Local | 6 s | 0.5 s | 25 s (Whisper sees 30 s windows) |
| ElevenLabs, OpenRouter | 20 s | 0.7 s | 300 s |

Short dictations are therefore a single request for the cloud engines, which keeps context and accuracy; long ones are mostly transcribed before the user stops.

Errors are `SttError`s: a short message for the overlay and technical detail for the log. `AuthError` marks a rejected key and `MissingKey` a key that was never entered; the latter opens the settings.

## Decisions worth knowing

- **Receiving with `select()`.** Python 3.13 serializes reads and writes on an SSL socket. A blocking `recv()` during a pause would stop audio from being sent, so the Deepgram receiver waits with `select()` and short timeouts.
- **Retrying kept-alive connections once.** Servers close idle HTTPS connections; Windows then reports `WinError 10053` on the next send. `HttpClient` retries once on a fresh connection.
- **No torch.** CTranslate2 imports torch and transformers for its model converters when they are installed. `stt/__init__.py` blocks both before faster-whisper loads: it saves about 2 s and avoids torch's CUDA DLLs clashing with cuBLAS.
- **No PyAV in the app.** faster-whisper imports PyAV only to decode audio files. The build leaves PyAV and its FFmpeg libraries out, and an empty module stands in.
- **One encoder pass.** For automatic language detection the local engine detects the language on the same encoder output it decodes, instead of letting faster-whisper encode twice.
- **GPU detection.** The GPU is used when CTranslate2 sees a CUDA device and cuBLAS can be found on `PATH`, in a `cuda` folder next to the exe, or in the `nvidia-cublas-cu12` package. Otherwise the CPU runs `int8`; the GPU runs `float16`, since `int8` GEMMs fail on some GPUs.
- **Crisp small icons.** The ICO holds sizes drawn on the pixel grid, the tray icon loads the ICO's own small frame, windows get the icon before CustomTkinter can replace it, and an explicit AppUserModelID gives the app its own taskbar identity.
- **Data folder migration.** `config.prepare_data_dir()` runs at startup, never on import, so tests and tools can't move user data.
