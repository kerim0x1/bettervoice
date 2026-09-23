# Development guide

Set up a checkout with [INSTALL.md](../../INSTALL.md) first. Commands run from the repository root with the virtual environment active.

## Everyday loop

```powershell
bettervoice               # run from source; quit a released copy first
ruff check .              # lint and import order
python -m pytest          # unit and UI smoke tests, offline
```

Run from a console to see the log live. `bettervoice --setup` shows the setup wizard again, `bettervoice --test` records five seconds with the configured engine and prints the result.

## Tests

| Suite | What it covers | Needs |
| --- | --- | --- |
| `test_config.py` | Settings, legacy names, `.env` parsing, joining transcripts | — |
| `test_chunked.py` | Splitting at pauses, context, silence, errors, cancelling | — |
| `test_engines.py` | ElevenLabs and OpenRouter requests against a local mock server, error mapping, keep-alive retry, key checks, AI Polish | — |
| `test_local.py` | Model download with resume against a local mock hub, retry after a failed load, unload | — |
| `test_app.py` | Hotkey, <kbd>Esc</kbd>, errors, and pasting with fake sessions | — |
| `test_autostart.py` | Run key, removal of old autostart entries, and autostart following the running copy, on a fake registry | — |
| `test_setup_ui.py` | Every page of the wizard and the settings window renders; callback errors fail the test | A desktop session |
| `test_packaging.py` | Installer script against the app, wizard images, version numbers, checksums, release notes, and the changelog entry for the current version | — |
| `test_integration.py` | Real key checks and transcriptions | `RUN_INTEGRATION=1`, keys, a downloaded model |

The default run makes no network requests and never touches `%APPDATA%\BetterVoice`: the `settings` fixture moves settings to a temporary folder, and the microphone is replaced by a fake that plays the clips in `tests/data`.

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

`python scripts/build.py` builds `dist\BetterVoice\` and a zip, `--installer` adds the installer; see [INSTALL.md](../../INSTALL.md#build-the-app) for every option. Releases follow the [release checklist](../release-checklist.md).

GitHub Actions runs two workflows on Windows runners:

| Workflow | Runs on | What it does |
| --- | --- | --- |
| [CI](../../.github/workflows/ci.yml) | Pushes to `main`, pull requests, by hand | Lint and tests on Python 3.10 and 3.13; then builds the app, zip, and installer, checks them, and uploads them as the `BetterVoice-win-x64` artifact for 14 days. |
| [Release](../../.github/workflows/release.yml) | `v*` tags; by hand for a trial run | Lint and tests, both editions as installer and zip, checksums and release notes; on a tag, publishes them as a GitHub release. |

Both use the [build check](../../.github/actions/check-windows-build/action.yml): the exe's version information, a start of the packaged app, and a silent install and uninstall of the standard installer, including Start menu entry and autostart. `scripts/release_notes.py` writes the release notes from the version's changelog section and the download table.

## Debugging

- The log is `%APPDATA%\BetterVoice\bettervoice.log` when BetterVoice runs without a console. It records engine choice, timings, and errors, never transcripts or keys.
- `LocalEngine.status` and the tray tooltip show the offline model's state.
- To test a clean first start, point `APPDATA` at an empty folder for one run: `$env:APPDATA = "$env:TEMP\bv-test"; bettervoice`.
