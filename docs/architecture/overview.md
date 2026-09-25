# Architecture overview

BetterVoice is a Python desktop app for Windows, macOS, and Linux. One process holds five kinds of threads: the tkinter main thread (overlay, setup and settings windows; on macOS also AppKit and the menu bar icon), a hotkey thread, the tray icon's thread (Windows and Linux), the command thread for `bettervoice --toggle` and its siblings, and one worker thread per dictation plus the engines' own helpers. The offline model runs in a second process, started on demand (`stt/local_worker.py`).

Everything that differs between the systems sits behind one interface in `bettervoice.desktop`; the rest of the code is the same everywhere.

## Code map

| Path | Responsibility |
| --- | --- |
| `src/bettervoice/cli.py` | The `bettervoice` command; hands `--toggle`, `--cancel`, `--settings`, and `--quit` to a running copy before the app loads. |
| `src/bettervoice/app.py` | The app's start, the dictation flow, the tray menu, and the event queue to the tk thread. |
| `src/bettervoice/desktop/` | The system layer: `windows.py` (keyboard hook, `keybd_event`, caret position, installer mutex), `macos.py` (Quartz event tap, ⌘V, Accessibility API, menu bar icon), `linux.py` (X11 key grabs, XTest, XShape, Wayland shortcut), `posix.py` (the lock file for one instance), `base.py` (the key filter and the way to the tk thread). |
| `src/bettervoice/ipc.py` | Commands from a second start: a Unix socket or named pipe with a per-user key. |
| `src/bettervoice/setup_ui.py` | Setup wizard and settings window (CustomTkinter). |
| `src/bettervoice/overlay.py` | The pill next to the text cursor. |
| `src/bettervoice/config.py` | Paths for each system, settings in the settings folder's `.env`, engine and language tables, migration from the old data folder. |
| `src/bettervoice/brand.py` | Name, tagline, colors, the mark (drawn in code), icon path, user agent. |
| `src/bettervoice/mic.py` | 16 kHz mono microphone capture (sounddevice). |
| `src/bettervoice/autostart.py` | Starting at sign-in: the Run key (Windows), a LaunchAgent (macOS), an XDG autostart entry (Linux); removes entries of older versions and points autostart at the copy that runs. |
| `src/bettervoice/stt/__init__.py` | The session interface and engine factory, key checks, AI Polish dispatch. |
| `src/bettervoice/stt/deepgram.py` | Live WebSocket streaming. |
| `src/bettervoice/stt/chunked.py` | Recording split at pauses, used by every other engine. |
| `src/bettervoice/stt/local.py` | The offline engine: model download, GPU detection, and the recognition process: started when a dictation begins, ended when idle. |
| `src/bettervoice/stt/local_worker.py` | The recognition process: loads Whisper (and CUDA) and transcribes what the app sends over a pipe. |
| `src/bettervoice/stt/elevenlabs.py`, `openrouter.py` | The HTTP engines; `openrouter.py` also holds AI Polish. |
| `src/bettervoice/stt/net.py` | A kept-alive HTTPS client, multipart encoding, error mapping. |
| `scripts/` | Brand asset generation, the build for each system (app, zip or disk image or archive, Windows installer, checksums), and the release notes. |
| `packaging/bettervoice.iss` | The Windows installer (Inno Setup): per-user install, updates in place, uninstall. |
| `packaging/linux/install.sh` | Adds the unpacked Linux app to the user's app menu. |
| `.github/` | CI and release workflows, and the shared build check. |
| `tests/` | Unit, UI smoke, and opt-in integration tests. |

## A dictation, end to end

1. The system's hotkey backend sees the hotkey, swallows it, and calls `on_hotkey()` (so does `bettervoice --toggle`, through the command thread), which starts a `Dictation` on a new thread and asks the tk thread to show the pill.
2. `stt.create_session()` builds the session for the selected engine. Every session offers `start()`, `finish()`, and `abort()`.
3. Deepgram streams microphone chunks over a WebSocket. The other engines use `ChunkedSession`: a worker looks for pauses with the Silero VAD and hands each finished passage to the engine's `Transcriber`, together with the previous text as context.
4. The second press ends recording; `finish()` returns the transcript. AI Polish runs if enabled, then `paste_text()` pastes through the clipboard with the system's paste shortcut. Where that's impossible (a Wayland app without wtype or ydotool), the text stays on the clipboard and the pill says so.
5. <kbd>Esc</kbd> calls `cancel()`: the dictation is detached at once, so a new one can start while the old worker winds down and discards its result. While a dictation runs, the backend knows <kbd>Esc</kbd> belongs to BetterVoice; on Linux it grabs the key only then.

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
- **GPU detection.** The GPU is used when CTranslate2 sees a CUDA device and its libraries load: on Windows cuBLAS from `PATH`, a `cuda` folder next to the exe, or the `nvidia-cublas-cu12` package; on Linux cuBLAS and cuDNN, which BetterVoice loads globally from NVIDIA's `pip` packages or the system before CTranslate2 asks for them. Otherwise the CPU runs `int8`; the GPU runs `float16`, since `int8` GEMMs fail on some GPUs. macOS always uses the CPU.
- **The model in a process of its own.** Once CUDA and cuBLAS are loaded, a process keeps about 600 MB of host memory, and there is no way to give it back short of ending the process. So Whisper runs in a spawned worker process (a fresh interpreter, never a fork of the tk process): `LocalTranscriber.prepare()` starts it when recording starts, the model loads while the user speaks, and an idle check ends it five minutes after the last transcription. The app itself never loads CUDA. If the app dies, the worker notices its pipe closing and exits. `bettervoice --check` starts a worker with a stand-in model, so a packaged build that can't start its recognition process fails in CI.
- **One key filter.** The Windows hook and the macOS event tap feed every key event to `desktop.base.KeyFilter`, which decides what to swallow: the hotkey with its release and autorepeat, and <kbd>Esc</kbd> during a dictation.
- **Wayland.** Apps can't grab keys or type into other apps there. The hotkey becomes a desktop shortcut to `bettervoice --toggle` (on GNOME BetterVoice writes it into the keyboard settings), X11 apps still get XTest, Wayland apps wtype or ydotool when installed. The X server doesn't know the pointer's position under Wayland, so the pill sits at the bottom of the screen.
- **Menu bar on macOS.** AppKit wants the main thread, which tk's event loop drives: the menu bar icon runs detached there, tray updates go through the tk thread, and the app hides its Dock icon.
- **Crisp small icons.** The ICO holds sizes drawn on the pixel grid, the tray icon loads the ICO's own small frame, windows get the icon before CustomTkinter can replace it, and an explicit AppUserModelID gives the app its own taskbar identity. On macOS the menu bar icon is a template image at twice its size, so it's sharp and follows light and dark mode.
- **Data folder migration.** `config.prepare_data_dir()` runs at startup, never on import, so tests and tools can't move user data.
