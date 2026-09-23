# Security

BetterVoice is beta software. Security fixes target the main branch and the latest published release; there is no long-term support for older versions.

## Report a vulnerability privately

Use GitHub's **Report a vulnerability** option in this repository's Security tab. Do not post vulnerability details in a public issue.

Include the affected version, your Windows version, the engine involved, the impact, and reproducible steps. Use dummy keys and synthetic audio; never submit working API keys or recordings of real conversations.

Ordinary bugs go through the [issue tracker](https://github.com/kerim0x1/bettervoice/issues).

## Areas that deserve particular care

- **API keys.** Keys are stored in plain text in the settings folder's `.env` (`%APPDATA%\BetterVoice` on Windows, `~/Library/Application Support/BetterVoice` on macOS, `~/.config/bettervoice` on Linux), protected by the user account: on macOS and Linux the file is readable by its owner only (mode 600). Keys must never reach logs, error messages, or requests to anyone but their provider.
- **Listening for the hotkey.** BetterVoice sees keystrokes to find its hotkey and, during a dictation, <kbd>Esc</kbd>: through a low-level keyboard hook on Windows, a Quartz event tap on macOS (which needs the Accessibility permission), and X11 key grabs on Linux, which deliver only the grabbed combinations. It must not record, log, or forward any other keystroke.
- **The clipboard and pasting.** BetterVoice writes to the clipboard and sends the paste shortcut to the focused window (on Linux through XTest, or wtype or ydotool under Wayland).
- **Commands from a second start.** `bettervoice --toggle` and its siblings reach the running copy through a Unix socket (a named pipe on Windows) in the user's own folder, authenticated with a random key that only the user can read. Messages are command names only and are never unpickled.
- **Audio and transcripts.** Audio goes only to the selected engine; transcripts only to the focused window and, with AI Polish, to OpenRouter.
- **Downloads.** Offline models are fetched over HTTPS from Hugging Face and checked for completeness. cuBLAS ships only in the Windows CUDA edition.
- **Release artifacts.** Releases are built and published by GitHub Actions from a version tag, with SHA-256 checksums in `SHA256SUMS.txt`. The downloads are not code-signed yet; the macOS app is signed ad hoc only, so Gatekeeper asks before its first start.
- **The installer.** It runs without administrator rights and writes only to the current user's profile: the app folder, Start menu, uninstall entry, and, on uninstall, the autostart entry and (when asked) `%APPDATA%\BetterVoice`.

## Local and CI configuration

Keep keys in the settings folder's `.env`, environment variables, or your CI secret store. `.env.example` contains documentation only. The default test run makes no network requests; integration tests (`RUN_INTEGRATION=1`) use the keys configured on the machine that runs them.
