# Changelog

All notable changes to BetterVoice are documented here. Versions follow [Semantic Versioning](https://semver.org/); pre-releases carry a beta number, as in `0.1.0b1` (0.1.0 beta 1). Each heading is the exact version: the release workflow takes the release notes from it.

## 0.1.0b1 — 2026-09-23

The first public release, and the first under the BetterVoice name. BetterVoice runs on Windows, macOS, and Linux.

### Added

- **Windows, macOS, and Linux.** The hotkey is <kbd>Win</kbd>+<kbd>O</kbd> on Windows, <kbd>⌃</kbd>+<kbd>⌥</kbd>+<kbd>O</kbd> on a Mac, and <kbd>Ctrl</kbd>+<kbd>Alt</kbd>+<kbd>O</kbd> on Linux. Under Wayland it's a desktop shortcut to `bettervoice --toggle`, which the setup adds on GNOME. On a Mac the setup asks for the Accessibility permission, and BetterVoice lives in the menu bar.
- `bettervoice --toggle`, `--cancel`, `--settings`, and `--quit` control the running copy; starting BetterVoice again opens its settings.
- Four recognition engines: **Local** (Whisper, offline, GPU-accelerated on NVIDIA cards), **Deepgram** (nova-3, live streaming), **ElevenLabs** (Scribe v2), and **OpenRouter** (audio-capable AI models such as Gemini Flash).
- 13 languages and automatic language detection.
- The offline engine uses an NVIDIA GPU on Windows (CUDA edition) and on Linux (with CUDA 12's cuBLAS and cuDNN 9).
- A first-start setup and a settings window: engine choice, API key check, offline model download with progress and resume, language, and autostart.
- **AI Polish**: optional removal of filler words and slips through OpenRouter, with a fallback to the original text.
- Transcription at pauses while you speak, and pre-opened connections, so text is ready shortly after you stop.
- <kbd>Esc</kbd> cancels a dictation, also while a model is still loading.
- The tray menu switches engine, language, and AI Polish, and opens the settings and the log.
- Downloads for every system: for Windows an installer for your account, without administrator rights (Start menu entry, updates in place, and a clean uninstall that can also remove your settings and models) and zip archives, each in a standard and a CUDA edition; for macOS disk images for Apple silicon and Intel; for Linux an archive with a script that adds BetterVoice to the app menu.
- SHA-256 checksums for every download.
- Brand assets, Windows version information for the exe, sharp icons at every size, and the app's own taskbar identity.

### Changed

- Renamed from BetterTalk. On the first start, settings and downloaded models move from `%APPDATA%\Dictation` to `%APPDATA%\BetterVoice`.
- Starting at sign-in follows the copy of BetterVoice you run: after a switch from BetterTalk, or from the zip archive to the installer, the old copy no longer starts.
- On Windows, the log is now `%APPDATA%\BetterVoice\bettervoice.log`. It never contains what you dictate.
