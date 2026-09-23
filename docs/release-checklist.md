# Release checklist

A release is published by pushing a `v<version>` tag, where `<version>` is `__version__` in `src/bettervoice/__init__.py` (for example `v0.1.0b1`). The [release workflow](../.github/workflows/release.yml) does the rest.

## Before tagging

1. Set `__version__` and add a `## <version> — <date>` section to [CHANGELOG.md](../CHANGELOG.md). The section becomes the release notes; the tests fail if it is missing.
2. Push to `main` and wait for CI to pass: lint and tests on Windows, macOS, and Linux with Python 3.10 and 3.13, and the build on each system with its checks.
3. Run the integration tests with keys for every engine: `$env:RUN_INTEGRATION = "1"; python -m pytest tests/test_integration.py`. Note any engine you could not test in the release notes.
4. Test a build by hand on each system you can. Download the `BetterVoice-Windows`, `-macOS`, or `-Linux` artifact of the CI run on `main`, or run the release workflow from the Actions tab (**Release → Run workflow**): run by hand, it builds every release file as an artifact and publishes nothing. On a clean account, or with empty settings folders, check:
   - the installer: install, the Start menu entry, and starting BetterVoice from the last page;
   - the setup wizard with **Local** and one cloud engine;
   - dictation into Notepad and a browser, <kbd>Esc</kbd> to cancel;
   - switching engine and language from the tray;
   - **Start with Windows**, then sign out and in again;
   - an update over the previous release: settings and models are kept, and the installer asks to quit a running BetterVoice first;
   - uninstalling, once keeping and once deleting settings and models;
   - on a Mac: the first start through Gatekeeper, the Accessibility step of the setup, the menu bar icon in light and dark mode, and pasting into a native app and a browser;
   - on Linux: `install.sh`, the hotkey under X11, the shortcut under Wayland (GNOME: added by the setup), and pasting into a terminal (<kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>V</kbd>).

## Tag and publish

```powershell
git tag v<version>
git push origin v<version>
```

On Windows, macOS (Apple silicon and Intel), and Linux, the workflow checks that the tag matches the version, lints and tests, and builds and checks every download; the Windows installer is installed and uninstalled once. Then it publishes the release with `SHA256SUMS.txt` and the changelog entry as notes. A release goes out complete or not at all. Versions with `a`, `b`, or `rc` in them (such as `0.1.0b1`) become pre-releases.

If a step fails, fix the cause and run the failed jobs again. A re-run replaces the files of an existing release and keeps its text. To release a changed commit, raise the version and tag again instead of moving the tag.

## After publishing

1. Download the installer from the release page, install it, and start BetterVoice once.
2. Check that the release notes list the right downloads and that `SHA256SUMS.txt` matches: `Get-FileHash <file>` in PowerShell.
3. Record known issues and anything you could not verify in the release notes.
