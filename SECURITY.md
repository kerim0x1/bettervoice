# Security

BetterVoice is beta software. Security fixes target the main branch and the latest published release; there is no long-term support for older versions.

## Report a vulnerability privately

Use GitHub's **Report a vulnerability** option in this repository's Security tab. Do not post vulnerability details in a public issue.

Include the affected version, your Windows version, the engine involved, the impact, and reproducible steps. Use dummy keys and synthetic audio; never submit working API keys or recordings of real conversations.

Ordinary bugs go through the [issue tracker](https://github.com/kerim0x1/bettervoice/issues).

## Areas that deserve particular care

- **API keys.** Keys are stored in plain text in `%APPDATA%\BetterVoice\.env`, protected only by the Windows account. They must never reach logs, error messages, or requests to anyone but their provider.
- **The keyboard hook.** BetterVoice installs a global low-level keyboard hook and acts on <kbd>Win</kbd>+<kbd>O</kbd> and, during a dictation, <kbd>Esc</kbd>. It must not record, log, or forward any other keystroke.
- **The clipboard and pasting.** BetterVoice writes to the clipboard and sends <kbd>Ctrl</kbd>+<kbd>V</kbd> to the focused window.
- **Audio and transcripts.** Audio goes only to the selected engine; transcripts only to the focused window and, with AI Polish, to OpenRouter.
- **Downloads.** Offline models are fetched over HTTPS from Hugging Face and checked for completeness. cuBLAS ships only in the CUDA edition.
- **Release artifacts.** Releases are built and published by GitHub Actions from a version tag, with SHA-256 checksums in `SHA256SUMS.txt`. The installers and archives are not code-signed yet.
- **The installer.** It runs without administrator rights and writes only to the current user's profile: the app folder, Start menu, uninstall entry, and, on uninstall, the autostart entry and (when asked) `%APPDATA%\BetterVoice`.

## Local and CI configuration

Keep keys in `%APPDATA%\BetterVoice\.env`, environment variables, or your CI secret store. `.env.example` contains documentation only. The default test run makes no network requests; integration tests (`RUN_INTEGRATION=1`) use the keys configured on the machine that runs them.
