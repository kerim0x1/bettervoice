# Install and set up BetterVoice

This guide covers the downloadable app and a source checkout for development. Run the commands from the repository root in PowerShell.

## Use the app

Download the installer from the [GitHub Releases page](https://github.com/kerim0x1/bettervoice/releases) and run it, or unzip a zip archive and start `BetterVoice.exe`. The [getting-started guide](GETTING_STARTED.md) explains which file to choose and the setup. Releases are published by the release workflow when a version tag is pushed; CI builds of `main` are available as workflow artifacts for testing.

| | Installer | Zip archive |
| --- | --- | --- |
| Location | `%LOCALAPPDATA%\Programs\BetterVoice`, for the current Windows account; no administrator rights | Any folder you choose |
| Start menu entry | Yes, and optionally a desktop shortcut | — |
| Update | Run the newer installer; it replaces the previous version in place | Quit BetterVoice and replace the folder |
| Uninstall | *Windows Settings → Apps*; optionally deletes settings, keys, and models too | Delete the folder |

Settings, keys, and models live in `%APPDATA%\BetterVoice` in both cases, so updates and switching between installer and zip keep them. **Start with Windows** follows the copy you run.

Installers for scripted setups accept Inno Setup's standard options, for example `/VERYSILENT /SUPPRESSMSGBOXES /NORESTART` and `/DIR="<folder>"`. A silent install does not start BetterVoice and aborts while it is running.

## Requirements for a source checkout

- Windows 10 or 11, 64-bit. BetterVoice uses the Windows keyboard hook, clipboard, and tray APIs; it does not run on other systems.
- **Python 3.10.1 or newer**; CI and the release builds use Python 3.13. Python 3.10.0 itself can't build the app (a bug in its `dis` module breaks PyInstaller).
- Git.
- Optional: an NVIDIA graphics card for GPU acceleration of the offline engine.

## Install

```powershell
git clone https://github.com/kerim0x1/bettervoice.git
cd bettervoice
py -3.13 -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
```

Use a dedicated virtual environment. If packages such as torch or jax are installed next to BetterVoice, PyInstaller picks them up and the build breaks or grows by gigabytes.

For GPU acceleration of the offline engine, also install NVIDIA's cuBLAS (about 700 MB):

```powershell
pip install -e ".[gpu]"
```

## Run

```powershell
bettervoice             # start; the first start opens the setup
bettervoice --setup     # show the setup again
bettervoice --test      # record 5 s with the configured engine and print the text
bettervoice --version
```

`python -m bettervoice` works the same. Without a console (`pythonw`), output goes to `%APPDATA%\BetterVoice\bettervoice.log`.

Only one BetterVoice runs at a time. Quit a running copy, including an installed release, from its tray icon before starting another.

## Configure

The setup and settings window cover everything. For development you can also put values in a `.env` file in the repository root; see [`.env.example`](.env.example) for every option. Real environment variables win over `%APPDATA%\BetterVoice\.env`, which wins over the repository's `.env`.

## Build the app

```powershell
pip install -e ".[build]"
python scripts/build.py              # dist\BetterVoice\ and BetterVoice-<version>-win-x64.zip
python scripts/build.py --installer  # also BetterVoice-<version>-win-x64-setup.exe
python scripts/build.py --with-cuda  # the CUDA edition, with cuBLAS for NVIDIA GPUs (needs .[gpu])
python scripts/build.py --release    # everything a release publishes (needs .[gpu])
```

The build is a folder, not a single exe: a one-file build would unpack about 200 MB to a temporary folder on every start. The script also writes the exe's version information (name, publisher, version) and leaves out components BetterVoice never uses.

The installers need [Inno Setup](https://jrsoftware.org/isinfo.php) 6.7 or newer. `build.py` finds it in its default install folders or on `PATH`; set `ISCC` to the path of `ISCC.exe` for another location. The installer script is [`packaging/bettervoice.iss`](packaging/bettervoice.iss); `build.py` passes it the version and renders its wizard images from the mark. `--release` builds the standard and the CUDA edition as zip and installer and writes `SHA256SUMS.txt`.

## Test

```powershell
python -m pytest                              # offline: fake microphone, local mock servers
$env:RUN_INTEGRATION = "1"; python -m pytest  # also against the real services and models
```

Integration tests use the keys from your settings and skip engines without one. The [development guide](docs/development/README.md) describes the suites in detail.
