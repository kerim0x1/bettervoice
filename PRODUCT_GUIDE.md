# How BetterVoice works

[Home](README.md) · [Getting started](GETTING_STARTED.md)

**BetterVoice turns speech into text in whatever program you are using.** You press a hotkey, speak, and press it again; BetterVoice transcribes what you said and pastes it at your cursor.

## The pieces

| Concept | Meaning |
| --- | --- |
| **Dictation** | Everything between the first and the second press of the hotkey: <kbd>Win</kbd>+<kbd>O</kbd> on Windows, <kbd>⌃</kbd>+<kbd>⌥</kbd>+<kbd>O</kbd> on a Mac, <kbd>Ctrl</kbd>+<kbd>Alt</kbd>+<kbd>O</kbd> on Linux. |
| **Engine** | What turns your speech into text: the offline model on your computer, or a cloud service. |
| **Language** | The language you speak. **Automatic** lets the engine detect it. |
| **Offline model** | The Whisper model the **Local** engine runs on your computer. |
| **The pill** | The small overlay next to your cursor that shows what BetterVoice is doing. |
| **AI Polish** | An optional cleanup of the finished text by a fast AI model. |
| **Tray icon** | BetterVoice's icon in the notification area (Windows), the menu bar (macOS), or the system tray (Linux): status, quick switches, settings. |

## What happens during a dictation

1. **Listen.** On the first press of the hotkey, BetterVoice opens the microphone and shows the pill at your text cursor (or at the mouse, in apps that don't report a cursor; under Wayland at the bottom of the screen).
2. **Transcribe while you speak.** Deepgram receives the audio live. The other engines work in pieces: whenever you pause after a longer passage, everything up to the pause is transcribed in the background. Pure silence is never sent anywhere.
3. **Finish.** On the second press, only the rest is left to transcribe. If AI Polish is on, the text is cleaned up.
4. **Paste.** BetterVoice copies the text to the clipboard, presses <kbd>Ctrl</kbd>+<kbd>V</kbd> (on a Mac <kbd>⌘</kbd>+<kbd>V</kbd>, in Linux terminals <kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>V</kbd>) for you, and puts your previous clipboard text back a second later.

<kbd>Esc</kbd> cancels at any point. If a connection breaks midway, the text recognized so far is still pasted.

## Engines

| | Local | Deepgram | ElevenLabs | OpenRouter |
| --- | --- | --- | --- | --- |
| Runs | On your computer | Deepgram's cloud | ElevenLabs' cloud | The chosen model's provider |
| Model | Whisper (`base`, `small`, `large-v3-turbo`) | nova-3 | Scribe v2 | Any model with audio input, e.g. Gemini Flash |
| Internet | Only for the one-time download | Required | Required | Required |
| Cost | Free | Per minute, on your Deepgram account | Per minute, on your ElevenLabs account | Per token, on your OpenRouter account |
| Text ready after you stop* | 0.1–0.4 s on an NVIDIA GPU, ~1.2 s on the processor | ~0.2–0.4 s | Not measured yet | Not measured yet |

\*Measured on Windows with an RTX 5070 Ti and a Ryzen 7 7800X3D, with 8–35 s dictations. Results depend on hardware, connection, and dictation length.

API keys are checked with the provider when you save them. BetterVoice keeps an HTTPS connection to the provider ready while you speak, so the request doesn't wait for a handshake.

### Offline models

| Choice in the app | Model | Download | Notes |
| --- | --- | --- | --- |
| **Automatic** (default) | `large-v3-turbo` with an NVIDIA GPU, `small` otherwise | — | The best fit for your hardware. |
| **Fast** | `base` | 150 MB | Very fast, less accurate. |
| **Balanced** | `small` | 490 MB | Good accuracy, quick on a processor. |
| **Best quality** | `large-v3-turbo` | 1.6 GB | The most accurate; slow without a GPU. |

Models are downloaded once from Hugging Face into the models folder (`%APPDATA%\BetterVoice\models` on Windows, `~/Library/Application Support/BetterVoice/models` on a Mac, `~/.local/share/bettervoice/models` on Linux). An interrupted download resumes where it stopped.

The model runs in a process of its own that starts when you press the hotkey, so it loads while you speak: `large-v3-turbo` is ready about 2 s later on an NVIDIA GPU. Five minutes after your last dictation the process ends and gives its memory back. Idle, BetterVoice then needs about 80 MB of RAM; while the model is loaded, about 600 MB more with a GPU (mostly NVIDIA's CUDA runtime; the model itself sits in video memory) or 300–1,000 MB on the processor, depending on the model. To keep the model loaded, turn off **Free the memory 5 minutes after the last dictation** under **Settings… → Recognition → Local**. Switching to a cloud engine frees the memory at once.

The GPU is used when an NVIDIA graphics card and NVIDIA's CUDA 12 libraries are available. On Windows, the CUDA edition (`…-cuda-setup.exe` or `…-cuda.zip`) includes cuBLAS; with the standard edition, BetterVoice uses the processor. On Linux, BetterVoice uses cuBLAS 12 and cuDNN 9 when they are installed, from your distribution or NVIDIA's `pip` packages. On a Mac, the offline engine runs on the processor.

## Languages

Choose one of 13 languages — English, German, French, Spanish, Italian, Portuguese, Dutch, Polish, Turkish, Russian, Chinese, Japanese, and Arabic — or **Automatic**:

- With **Deepgram**, *Automatic* can switch languages mid-sentence for English, Spanish, French, German, Hindi, Russian, Portuguese, Japanese, Italian, and Dutch.
- The **Local** engine detects the language for each piece of your dictation, choosing among the 13 languages above.
- **ElevenLabs** and **OpenRouter** detect the language themselves.

A fixed language is a little more accurate if you always speak the same one.

## AI Polish

When AI Polish is on, a fast text model on OpenRouter removes filler words ("um", "uh", and their equivalents in other languages), stutters, false starts, and repeated words, and fixes punctuation. It is instructed not to rephrase, shorten, translate, or answer what you said. If the result looks like an answer rather than your text, or the request fails, BetterVoice pastes your original transcript. With the **OpenRouter** engine the cleanup happens during transcription, without a second request.

## Privacy and data

| What | Where it goes |
| --- | --- |
| Your voice, with **Local** | Nowhere. It is processed on your computer and discarded. |
| Your voice, with a cloud engine | To that provider while you dictate, under the provider's terms and data policy. |
| The finished text, with AI Polish | To OpenRouter and the model provider, under their terms. |
| Settings and API keys | A `.env` file in plain text, readable only by your user account: `%APPDATA%\BetterVoice` on Windows, `~/Library/Application Support/BetterVoice` on a Mac, `~/.config/bettervoice` on Linux. |
| The log | `bettervoice.log` (`%APPDATA%\BetterVoice` on Windows, `~/Library/Logs/BetterVoice` on a Mac, `~/.local/state/bettervoice` on Linux): status and error messages only, never your dictation or your keys. Rotated at 1 MB. |
| Your clipboard | Used for pasting. Previous clipboard *text* is restored; other content, such as an image, is replaced by the transcript. |

BetterVoice has no account, telemetry, or analytics. Apart from the engines you use, it only contacts Hugging Face to download offline models and OpenRouter's public model list when you open its settings.

## Limitations

- Windows 10 and 11 (64-bit), macOS 12 and newer, and 64-bit Linux. macOS and Linux support is newer and less tried than Windows.
- On Windows, programs running as administrator don't accept keystrokes from BetterVoice unless it runs as administrator too; <kbd>Win</kbd>+<kbd>O</kbd> replaces the Windows shortcut for the screen rotation lock.
- On a Mac, BetterVoice needs the Accessibility permission to hear its hotkey and to paste.
- Under Wayland, apps can't listen for keys or type into other apps by themselves: the hotkey is a desktop shortcut to `bettervoice --toggle`, <kbd>Esc</kbd> reaches BetterVoice only from X11 apps, and pasting into Wayland apps needs wtype or ydotool (otherwise the text waits on the clipboard). The pill sits at the bottom of the screen there.
