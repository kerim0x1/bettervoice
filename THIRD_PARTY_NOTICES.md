# Third-party notices

BetterVoice's source is released under the MIT License in [`LICENSE`](LICENSE). The components it builds on keep their own licenses; choosing MIT for BetterVoice does not change their terms. Preserve their license and copyright notices when you redistribute them.

## Components in the Windows app

The installers and zip archives bundle these packages and runtimes. License identifiers are taken from each package's own metadata at the time of the 0.1 release; the installed packages' notices remain authoritative.

| Component | Used for | License |
| --- | --- | --- |
| [Python](https://www.python.org/) runtime and standard library | Everything | PSF-2.0 |
| [Tcl/Tk](https://www.tcl-lang.org/) | Windows and dialogs | Tcl/Tk license (BSD-style) |
| [CustomTkinter](https://github.com/TomSchimansky/CustomTkinter) | The setup and settings window | MIT (its package metadata also names CC0-1.0) |
| [darkdetect](https://github.com/albertosottile/darkdetect) | Used by CustomTkinter | BSD-3-Clause |
| [faster-whisper](https://github.com/SYSTRAN/faster-whisper) | Offline recognition | MIT |
| [Silero VAD](https://github.com/snakers4/silero-vad) model, shipped with faster-whisper | Finding speech and pauses | MIT |
| [CTranslate2](https://github.com/OpenNMT/CTranslate2) | Running Whisper models | MIT |
| [ONNX Runtime](https://github.com/microsoft/onnxruntime) | Running the Silero VAD model | MIT |
| [Tokenizers](https://github.com/huggingface/tokenizers) | Whisper's tokenizer | Apache-2.0 |
| [Hugging Face Hub](https://github.com/huggingface/huggingface_hub) client | Finding model files | Apache-2.0 |
| [NumPy](https://numpy.org/) | Audio processing | BSD-3-Clause, with bundled parts under 0BSD, MIT, Zlib, and CC0-1.0 |
| [python-sounddevice](https://github.com/spatialaudio/python-sounddevice) and [PortAudio](https://www.portaudio.com/) | Microphone input | MIT |
| [websocket-client](https://github.com/websocket-client/websocket-client) | Deepgram streaming | Apache-2.0 |
| [pystray](https://github.com/moses-palmer/pystray) | The tray icon and menu | LGPL-3.0 |
| [Pyperclip](https://github.com/asweigart/pyperclip) | Clipboard access | BSD-3-Clause |
| [Pillow](https://python-pillow.org/) | Drawing the icons and images | MIT-CMU |
| [tqdm](https://github.com/tqdm/tqdm) | Used by the Hugging Face client | MPL-2.0 AND MIT |
| [certifi](https://github.com/certifi/python-certifi) | Trusted certificates for HTTPS | MPL-2.0 |
| [OpenSSL](https://www.openssl.org/), [libffi](https://sourceware.org/libffi/), [zlib](https://zlib.net/), [SQLite](https://sqlite.org/) | Parts of the Python runtime | Apache-2.0, MIT, Zlib, public domain |
| Microsoft Visual C++ runtime | Parts of the Python runtime | Microsoft redistributable terms |

**pystray** is licensed under the GNU LGPL 3.0. Its unmodified source is available from its [repository](https://github.com/moses-palmer/pystray). You can replace it with a modified version by installing that version and rebuilding the app with `scripts/build.py`; the complete build setup is part of this repository.

The release workflow builds with the dependency versions available at build time; each release's files contain the exact packages they were built with.

## NVIDIA cuBLAS (CUDA edition only)

The CUDA edition (`-cuda-setup.exe` and `-cuda.zip`) adds `cublas64_12.dll` and `cublasLt64_12.dll` from NVIDIA's `nvidia-cublas-cu12` package. They are proprietary NVIDIA software, redistributed under the terms of the [NVIDIA CUDA Toolkit license agreement](https://docs.nvidia.com/cuda/eula/index.html). The standard edition does not contain them.

## Inno Setup (installers only)

The installers are built with [Inno Setup](https://jrsoftware.org/isinfo.php), Copyright (C) 1997-2026 Jordan Russell, portions Copyright (C) 2000-2026 Martijn Laan. Its setup and uninstall programs are part of every installer and keep their copyright notices, under the [Inno Setup License](https://jrsoftware.org/files/is/license.txt).

## Downloaded at runtime

These are not part of the installers or archives. BetterVoice downloads them from Hugging Face when you first use the offline engine:

| Model | Source | License |
| --- | --- | --- |
| Whisper `base`, `small` (CTranslate2 conversions) | [Systran](https://huggingface.co/Systran) | MIT, from [OpenAI Whisper](https://github.com/openai/whisper) |
| Whisper `large-v3-turbo` (CTranslate2 conversion) | [mobiuslabsgmbh](https://huggingface.co/mobiuslabsgmbh/faster-whisper-large-v3-turbo) | MIT, from OpenAI Whisper |

## Development tools

[PyInstaller](https://pyinstaller.org/) (GPL-2.0-or-later with an exception that permits distributing the apps it builds), [pytest](https://pytest.org/) (MIT), and [Ruff](https://docs.astral.sh/ruff/) (MIT) are used to build and check BetterVoice and are not distributed with it.

## Services, names, and marks

Deepgram, ElevenLabs, OpenRouter, Google Gemini, OpenAI, Whisper, NVIDIA, Windows, and other product names identify services and technologies BetterVoice works with. They belong to their respective owners, and their mention does not imply endorsement. Using a cloud engine is subject to that provider's own terms and pricing.

The BetterVoice name, mark, and brand guide are supplied by the project owner. The source license does not by itself permit presenting a modified build as an official BetterVoice release. The app uses the Segoe UI Variable and Segoe Fluent Icons fonts that come with Windows; they are not distributed with BetterVoice.
