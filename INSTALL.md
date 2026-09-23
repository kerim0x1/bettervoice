# Install and set up BetterVoice

This guide covers the downloadable app and a source checkout for development on Windows, macOS, and Linux. Run the commands from the repository root: in PowerShell on Windows, in a terminal on macOS and Linux.

## Use the app

Download BetterVoice for your system from the [GitHub Releases page](https://github.com/kerim0x1/bettervoice/releases); the [getting-started guide](GETTING_STARTED.md) explains which file to choose, the first start on each system, and the setup. Releases are published by the release workflow when a version tag is pushed; CI builds of `main` are available as workflow artifacts for testing.

| | Windows installer | Windows zip | macOS | Linux |
| --- | --- | --- | --- | --- |
| Location | `%LOCALAPPDATA%\Programs\BetterVoice`, no administrator rights | Any folder | Applications | Any folder; `install.sh` adds it to the app menu |
| Update | Run the newer installer | Replace the folder | Replace the app | Unpack over the folder |
| Uninstall | *Windows Settings → Apps*; optionally with settings, keys, and models | Delete the folder | Move the app to the Trash | `./install.sh --uninstall`, then delete the folder |

Settings, keys, and models stay where they are through updates and uninstalls (except when the Windows uninstaller is asked to remove them):

| | Settings and keys (`.env`) | Models | Log |
| --- | --- | --- | --- |
| Windows | `%APPDATA%\BetterVoice` | `%APPDATA%\BetterVoice\models` | `%APPDATA%\BetterVoice\bettervoice.log` |
| macOS | `~/Library/Application Support/BetterVoice` | `…/BetterVoice/models` | `~/Library/Logs/BetterVoice/bettervoice.log` |
| Linux | `~/.config/bettervoice` | `~/.local/share/bettervoice/models` | `~/.local/state/bettervoice/bettervoice.log` |

Starting at sign-in follows the copy you run, so a move between copies keeps it working.

Windows installers for scripted setups accept Inno Setup's standard options, for example `/VERYSILENT /SUPPRESSMSGBOXES /NORESTART` and `/DIR="<folder>"`. A silent install does not start BetterVoice and aborts while it is running.

## Requirements for a source checkout

- **Windows** 10 or 11, 64-bit; **macOS** 12 or newer; or **Linux** with X11 or Wayland (an X server, XWayland included, is needed for the windows).
- **Python 3.10.1 or newer**, with tkinter; CI and the release builds use Python 3.13. Python 3.10.0 itself can't build the app (a bug in its `dis` module breaks PyInstaller). On Linux, install PortAudio as well: `sudo apt install libportaudio2` (Debian, Ubuntu) or `sudo dnf install portaudio` (Fedora).
- Git.
- Optional: an NVIDIA graphics card for GPU acceleration of the offline engine (Windows and Linux).

## Install

```sh
git clone https://github.com/kerim0x1/bettervoice.git
cd bettervoice
python3 -m venv .venv                # Windows: py -3.13 -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

Use a dedicated virtual environment. If packages such as torch or jax are installed next to BetterVoice, PyInstaller picks them up and the build breaks or grows by gigabytes.

For GPU acceleration of the offline engine, also install NVIDIA's libraries: cuBLAS on Windows (about 700 MB), cuBLAS and cuDNN on Linux (about 1.5 GB):

```sh
pip install -e ".[gpu]"
```

On a Mac, the terminal you run BetterVoice from needs the **Accessibility** permission (*System Settings → Privacy & Security → Accessibility*), and it asks for the microphone on the first dictation.

## Run

```sh
bettervoice             # start; the first start opens the setup
bettervoice --setup     # show the setup again
bettervoice --test      # record 5 s with the configured engine and print the text
bettervoice --version
bettervoice --check     # load every part of the app, then quit (used on packaged builds)
```

`python -m bettervoice` works the same. Without a terminal (`pythonw`, the packaged app, a start from the desktop), output goes to the log file listed above.

Only one BetterVoice runs at a time. A second start hands its command to the running copy:

```sh
bettervoice --toggle    # start or stop a dictation, like the hotkey
bettervoice --cancel    # cancel it, like Esc
bettervoice --settings  # open the settings
bettervoice --quit      # quit
```

Under Wayland, a keyboard shortcut in the desktop's settings that runs `bettervoice --toggle` is the hotkey.

## Configure

The setup and settings window cover everything. For development you can also put values in a `.env` file in the repository root; see [`.env.example`](.env.example) for every option. Real environment variables win over the settings folder's `.env`, which wins over the repository's `.env`.

## Build the app

```sh
pip install -e ".[build]"
python scripts/build.py              # the app and its archive for this system
python scripts/build.py --release    # everything this system publishes, and SHA256SUMS.txt
```

| System | Output in `dist` | Also |
| --- | --- | --- |
| Windows | `BetterVoice\` and `BetterVoice-<version>-win-x64.zip` | `--installer` adds `…-win-x64-setup.exe`; `--with-cuda` builds the CUDA edition (needs `.[gpu]`); `--release` builds both editions as zip and installer (needs `.[gpu]`) |
| macOS | `BetterVoice.app` and `BetterVoice-<version>-macos-<arm64 or x64>.dmg` | Signed ad hoc; needs Xcode's command line tools |
| Linux | `BetterVoice/` with `bettervoice` and `install.sh`, and `BetterVoice-<version>-linux-x64.tar.gz` | Build on an old distribution: the app runs where glibc is at least as new |

The build is a folder, not a single file: a one-file build would unpack about 200 MB to a temporary folder on every start. The script also writes the version information (the exe's resources, the Mac app's `Info.plist`) and leaves out components BetterVoice never uses.

The Windows installers need [Inno Setup](https://jrsoftware.org/isinfo.php) 6.7 or newer. `build.py` finds it in its default install folders or on `PATH`; set `ISCC` to the path of `ISCC.exe` for another location. The installer script is [`packaging/bettervoice.iss`](packaging/bettervoice.iss); `build.py` passes it the version and renders its wizard images from the mark.

## Test

```sh
python -m pytest                              # offline: fake microphone, local mock servers
RUN_INTEGRATION=1 python -m pytest            # also against the real services and models
```

On Linux, run the tests on a virtual display with the tools the X11 tests use: `sudo apt install xvfb xdotool`, then `xvfb-run -a python -m pytest`. In PowerShell, set the variable with `$env:RUN_INTEGRATION = "1"`. Integration tests use the keys from your settings and skip engines without one. The [development guide](docs/development/README.md) describes the suites in detail.
