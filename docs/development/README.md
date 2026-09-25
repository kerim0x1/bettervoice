# Development guide

Set up a checkout with [INSTALL.md](../../INSTALL.md) first. Commands run from the repository root with the virtual environment active.

## Everyday loop

```powershell
bettervoice               # run from source; quit a released copy first
ruff check .              # lint and import order
python -m pytest          # unit and UI smoke tests, offline (Linux: xvfb-run -a python -m pytest)
```

Run from a console to see the log live. `bettervoice --setup` shows the setup wizard again, `bettervoice --test` records five seconds with the configured engine and prints the result.

## Tests

| Suite | What it covers | Needs |
| --- | --- | --- |
| `test_config.py` | Settings, legacy names, `.env` parsing, joining transcripts | — |
| `test_chunked.py` | Splitting at pauses, context, silence, errors, cancelling | — |
| `test_engines.py` | ElevenLabs and OpenRouter requests against a local mock server, error mapping, keep-alive retry, key checks, AI Polish | — |
| `test_local.py` | Model download with resume against a local mock hub, retry after a failed load, unload, freeing the model when idle and loading it again, and the recognition process itself (with a stand-in model from `fake_model.py`) | — |
| `test_app.py` | Hotkey, <kbd>Esc</kbd>, commands, errors, and pasting with fake sessions | — |
| `test_desktop.py` | The key filter, the way to the tk thread, and the system's own parts: the Windows keyboard hook, the macOS event tap, and on Linux the Wayland shortcut, a real X11 key grab, and pasting into a text field with XTest | Linux: an X display and xdotool |
| `test_ipc.py` | Commands from a second start, the key check, one instance per user | — |
| `test_autostart.py` | Run key, LaunchAgent, and XDG autostart entry, removal of old entries, and autostart following the running copy, on a fake registry and temporary folders | — |
| `test_setup_ui.py` | Every page of the wizard and the settings window renders; callback errors fail the test | A desktop session |
| `test_packaging.py` | Installer script against the app, wizard images, version numbers, checksums, release notes, and the changelog entry for the current version | — |
| `test_integration.py` | Real key checks and transcriptions | `RUN_INTEGRATION=1`, keys, a downloaded model |

The default run makes no network requests and never touches the real settings folder: the `settings` fixture moves settings to a temporary folder, the command tests use their own socket folder, and the microphone is replaced by a fake that plays the clips in `tests/data`. Tests for another system's code are skipped; CI runs the suite on all three.

```powershell
$env:RUN_INTEGRATION = "1"; python -m pytest tests/test_integration.py
```

Integration tests check that each provider rejects a bogus key, then transcribe a German clip with every engine that has a key configured, and with the offline engine if a model is downloaded.

## Brand assets

The mark is defined in `src/bettervoice/brand.py`. After changing it, regenerate every asset and commit them together:

```powershell
python scripts/generate_brand_assets.py
```

Documentation screenshots live in `assets/screenshots/`. Take them from the running app with a fresh data folder, so no keys or personal settings appear.

## Builds and releases

`python scripts/build.py` builds the app and its download for the system it runs on; on Windows `--installer` adds the installer. See [INSTALL.md](../../INSTALL.md#build-the-app) for every option. Releases follow the [release checklist](../release-checklist.md).

GitHub Actions runs two workflows:

| Workflow | Runs on | What it does |
| --- | --- | --- |
| [CI](../../.github/workflows/ci.yml) | Pushes to `main`, pull requests, by hand | Lint and tests on Windows, macOS, and Linux with Python 3.10 and 3.13 (Linux on a virtual display); then builds on each system, checks the build, and uploads it as the `BetterVoice-Windows`, `-macOS`, and `-Linux` artifacts for 14 days. |
| [Release](../../.github/workflows/release.yml) | `v*` tags; by hand for a trial run | On each system: lint, tests, and every download (Windows: both editions as installer and zip; macOS: disk images for Apple silicon and Intel; Linux: the archive), checked; then checksums and release notes, and on a tag a GitHub release. |

The Windows builds go through the [build check](../../.github/actions/check-windows-build/action.yml): the exe's version information, `BetterVoice.exe --check`, and a silent install and uninstall of the standard installer, including Start menu entry and autostart. The macOS build is checked with `codesign --verify`, `--check`, and `hdiutil verify`, the Linux build with `--check` on a virtual display. `--check` loads every part of the app, including the voice activity model, and fails on anything missing from the build. `scripts/release_notes.py` writes the release notes from the version's changelog section and the download table.

## Debugging

- The log is `bettervoice.log` in the log folder ([INSTALL.md](../../INSTALL.md#use-the-app) lists it for each system) when BetterVoice runs without a terminal. It records engine choice, timings, and errors, never transcripts or keys.
- `LocalEngine.status` and the tray tooltip show the offline model's state.
- To test a clean first start, point the settings at an empty folder for one run: on Windows `$env:APPDATA = "$env:TEMP\bv-test"; bettervoice`, on Linux `XDG_CONFIG_HOME=/tmp/bv-test bettervoice`.
- `bettervoice --toggle` starts and stops a dictation in the running copy, handy where the hotkey is taken or under Wayland.
