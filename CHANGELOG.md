# Changelog

All notable changes to BetterVoice are documented here. Versions follow [Semantic Versioning](https://semver.org/); pre-releases carry a beta number, as in `0.1.0b1` (0.1.0 beta 1). Each heading is the exact version: the release workflow takes the release notes from it.

## 0.1.0b1 — 2026-09-23

The first public release, and the first under the BetterVoice name.

### Added

- Four recognition engines: **Local** (Whisper, offline, GPU-accelerated on NVIDIA cards), **Deepgram** (nova-3, live streaming), **ElevenLabs** (Scribe v2), and **OpenRouter** (audio-capable AI models such as Gemini Flash).
- 13 languages and automatic language detection.
- A first-start setup and a settings window: engine choice, API key check, offline model download with progress and resume, language, and autostart.
- **AI Polish**: optional removal of filler words and slips through OpenRouter, with a fallback to the original text.
- Transcription at pauses while you speak, and pre-opened connections, so text is ready shortly after you stop.
- <kbd>Esc</kbd> cancels a dictation, also while a model is still loading.
- The tray menu switches engine, language, and AI Polish, and opens the settings and the log.
- An installer for your Windows account, without administrator rights: Start menu entry, updates in place, and a clean uninstall that can also remove your settings and models. Zip archives remain for use without installing. Both come in a standard and a CUDA edition for NVIDIA graphics cards.
- SHA-256 checksums for every download.
- Brand assets, Windows version information for the exe, sharp icons at every size, and the app's own taskbar identity.

### Changed

- Renamed from BetterTalk. On the first start, settings and downloaded models move from `%APPDATA%\Dictation` to `%APPDATA%\BetterVoice`.
- **Start with Windows** follows the copy of BetterVoice you run: after a switch from BetterTalk, or from the zip archive to the installer, the old copy no longer starts with Windows.
- The log is now `%APPDATA%\BetterVoice\bettervoice.log`. It never contains what you dictate.
