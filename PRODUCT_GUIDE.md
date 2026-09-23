# How BetterVoice works

[Home](README.md) · [Getting started](GETTING_STARTED.md)

**BetterVoice turns speech into text in whatever program you are using.** You press a hotkey, speak, and press it again; BetterVoice transcribes what you said and pastes it at your cursor.

## The pieces

| Concept | Meaning |
| --- | --- |
| **Dictation** | Everything between the first and the second <kbd>Win</kbd>+<kbd>O</kbd>. |
| **Engine** | What turns your speech into text: the offline model on your PC, or a cloud service. |
| **Language** | The language you speak. **Automatic** lets the engine detect it. |
| **Offline model** | The Whisper model the **Local** engine runs on your PC. |
| **The pill** | The small overlay next to your cursor that shows what BetterVoice is doing. |
| **AI Polish** | An optional cleanup of the finished text by a fast AI model. |
| **Tray icon** | BetterVoice's icon in the notification area: status, quick switches, settings. |

## What happens during a dictation

1. **Listen.** On the first <kbd>Win</kbd>+<kbd>O</kbd>, BetterVoice opens the microphone and shows the pill at your text cursor (or at the mouse, in apps that don't report a cursor).
2. **Transcribe while you speak.** Deepgram receives the audio live. The other engines work in pieces: whenever you pause after a longer passage, everything up to the pause is transcribed in the background. Pure silence is never sent anywhere.
3. **Finish.** On the second <kbd>Win</kbd>+<kbd>O</kbd>, only the rest is left to transcribe. If AI Polish is on, the text is cleaned up.
4. **Paste.** BetterVoice copies the text to the clipboard, presses <kbd>Ctrl</kbd>+<kbd>V</kbd> for you, and puts your previous clipboard text back a second later.

<kbd>Esc</kbd> cancels at any point. If a connection breaks midway, the text recognized so far is still pasted.

## Engines

| | Local | Deepgram | ElevenLabs | OpenRouter |
| --- | --- | --- | --- | --- |
| Runs | On your PC | Deepgram's cloud | ElevenLabs' cloud | The chosen model's provider |
| Model | Whisper (`base`, `small`, `large-v3-turbo`) | nova-3 | Scribe v2 | Any model with audio input, e.g. Gemini Flash |
| Internet | Only for the one-time download | Required | Required | Required |
| Cost | Free | Per minute, on your Deepgram account | Per minute, on your ElevenLabs account | Per token, on your OpenRouter account |
| Text ready after you stop* | 0.1–0.4 s on an NVIDIA GPU, ~1.2 s on the processor | ~0.2–0.4 s | Not measured yet | Not measured yet |

\*Measured on an RTX 5070 Ti and a Ryzen 7 7800X3D with 8–35 s dictations. Results depend on hardware, connection, and dictation length.

API keys are checked with the provider when you save them. BetterVoice keeps an HTTPS connection to the provider ready while you speak, so the request doesn't wait for a handshake.

### Offline models

| Choice in the app | Model | Download | Notes |
| --- | --- | --- | --- |
| **Automatic** (default) | `large-v3-turbo` with an NVIDIA GPU, `small` otherwise | — | The best fit for your hardware. |
| **Fast** | `base` | 150 MB | Very fast, less accurate. |
| **Balanced** | `small` | 490 MB | Good accuracy, quick on a processor. |
| **Best quality** | `large-v3-turbo` | 1.6 GB | The most accurate; slow without a GPU. |

Models are downloaded once from Hugging Face into `%APPDATA%\BetterVoice\models`. An interrupted download resumes where it stopped. The model stays loaded while the **Local** engine is selected; switching to a cloud engine frees its memory.

The GPU is used when an NVIDIA graphics card and NVIDIA's cuBLAS library are available. The CUDA edition (`…-cuda-setup.exe` or `…-cuda.zip`) includes cuBLAS; with the standard edition, BetterVoice uses the processor.

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
| Your voice, with **Local** | Nowhere. It is processed on your PC and discarded. |
| Your voice, with a cloud engine | To that provider while you dictate, under the provider's terms and data policy. |
| The finished text, with AI Polish | To OpenRouter and the model provider, under their terms. |
| Settings and API keys | `%APPDATA%\BetterVoice\.env` on your PC, in plain text, readable by your Windows account. |
| The log | `%APPDATA%\BetterVoice\bettervoice.log`: status and error messages only, never your dictation or your keys. Rotated at 1 MB. |
| Your clipboard | Used for pasting. Previous clipboard *text* is restored; other content, such as an image, is replaced by the transcript. |

BetterVoice has no account, telemetry, or analytics. Apart from the engines you use, it only contacts Hugging Face to download offline models and OpenRouter's public model list when you open its settings.

## Limitations

- Windows only (10 and 11, 64-bit).
- Programs running as administrator don't accept keystrokes from BetterVoice unless it runs as administrator too.
- <kbd>Win</kbd>+<kbd>O</kbd> replaces the Windows shortcut for the screen rotation lock.
