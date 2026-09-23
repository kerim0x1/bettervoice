# Getting started with BetterVoice

[Home](README.md) · [How BetterVoice works](PRODUCT_GUIDE.md)

Get from download to your first dictation in a few minutes. This guide covers the app itself; to run BetterVoice from source, see [INSTALL.md](INSTALL.md).

## 1. Get the app

Download the installer from the newest release on the [GitHub Releases page](https://github.com/kerim0x1/bettervoice/releases):

| Your PC | File |
| --- | --- |
| Windows 10 / 11, 64-bit | `BetterVoice-<version>-win-x64-setup.exe` |
| … with an NVIDIA graphics card, for faster offline recognition | `BetterVoice-<version>-win-x64-cuda-setup.exe` |

Run it and follow the installer. It installs BetterVoice for your Windows account, without administrator rights, and adds it to the Start menu. If SmartScreen warns about an unrecognized app, choose *More info → Run anyway*; BetterVoice is not code-signed yet.

Prefer not to install? The release also has zip archives (`…-win-x64.zip` and `…-win-x64-cuda.zip`): unzip one to a folder you keep, for example `Documents\BetterVoice`, and start `BetterVoice.exe`.

Using an older version called **BetterTalk**? Quit it first from its tray icon. BetterVoice takes over its settings and downloaded models automatically.

## 2. Set it up

The setup opens on the first start and takes five short steps.

![The first step of the setup](assets/screenshots/setup-welcome.png)

1. **Welcome** — an overview. Choose **Set up**.
2. **How should BetterVoice listen?** — pick an engine:

   | Engine | Choose it when | Needs |
   | --- | --- | --- |
   | **Local** | You want privacy, no costs, and work offline. | A one-time model download |
   | **Deepgram** | You want the fastest results; text is ready as you stop. | A Deepgram API key |
   | **ElevenLabs** | You want top accuracy, also for less common languages. | An ElevenLabs API key |
   | **OpenRouter** | You already use OpenRouter, or want to pick an AI model yourself. | An OpenRouter API key |

3. **Connect** your engine — for a cloud engine, paste your API key and choose **Verify**. BetterVoice checks it with the provider and saves it only on this PC. The link above the field opens the page where you create a key.
   For **Local**, choose a model; **Automatic** picks the best one for your hardware. **Download & continue** starts the one-time download, which continues in the background while you finish the setup.
4. **Which language do you speak?** — choose your language, or **Automatic** to let BetterVoice detect it.
5. **You're all set** — leave **Start with Windows** on to have BetterVoice ready after every sign-in, then choose **Get started**.

BetterVoice now runs in the background. Its icon sits in the notification area of the taskbar; open the arrow next to the clock if you don't see it.

## 3. Dictate

1. Click into any text field: a document, an email, a chat, the browser's address bar.
2. Press <kbd>Win</kbd>+<kbd>O</kbd>. A small pill appears next to your cursor with a red dot and a moving waveform.
3. Speak naturally. Pauses are fine.
4. Press <kbd>Win</kbd>+<kbd>O</kbd> again. The waveform dims while the last words are transcribed, then your text is pasted at the cursor.

Press <kbd>Esc</kbd> while the pill is visible to cancel; nothing is pasted.

![The pill while listening, while transcribing, and with a message](assets/screenshots/overlay.png)

## 4. Change settings

**Right-click the tray icon** for quick changes:

- **Recognition** — switch the engine.
- **Language** — switch the language.
- **AI Polish** — remove filler words and slips from your text (needs an OpenRouter key).
- **Settings…** — the settings window, also opened by clicking the icon.

In the settings window, **Recognition** holds the engines, keys, and the offline model; **Language** the languages; **General** AI Polish, **Start with Windows**, and help. Changes are saved right away.

![The settings window](assets/screenshots/settings.png)

## 5. Update or uninstall

**To update**, download the newest installer from the [Releases page](https://github.com/kerim0x1/bettervoice/releases) and run it. It installs over your current version; settings, keys, and models stay. If BetterVoice is running, the installer asks you to quit it first from its tray icon. With the zip archive, quit BetterVoice and replace its folder instead.

**To uninstall**, open *Windows Settings → Apps → Installed apps*, find **BetterVoice**, and choose **Uninstall**. The uninstaller asks whether to delete your settings, API keys, and downloaded models too; keep them if you plan to come back. **Start with Windows** is removed with the app.

## When something does not work

| What you see | What to check |
| --- | --- |
| Nothing happens on <kbd>Win</kbd>+<kbd>O</kbd> | Check that the BetterVoice icon is in the notification area. Windows doesn't let apps type into programs that run as administrator unless BetterVoice runs as administrator too. |
| "BetterVoice is already running" | BetterVoice, or the older BetterTalk, is already running. Quit it from its tray icon and start BetterVoice again. |
| "No microphone found" | Connect a microphone and allow microphone access under *Windows Settings → Privacy & security → Microphone*. |
| "…: invalid API key" | Open **Settings… → Recognition**, paste the key again, and choose **Verify**. |
| "…: out of credit" or "…: rate limited" | Your account with that provider is out of credit or has hit a limit. Top up, wait a moment, or switch the engine. |
| "No speech recognized" | BetterVoice heard no speech. Speak a little louder or closer to the microphone, and check the microphone selected in Windows. |
| The pill shows "Local model downloading…" | The offline model is still downloading or loading. Your dictation is kept and typed once it is ready; <kbd>Esc</kbd> cancels. |
| The offline engine uses the processor although you have an NVIDIA GPU | Install the CUDA edition (`…-cuda-setup.exe`) over your installation; your settings stay. **Settings… → Recognition → Local** shows which one is used. |
| The text lands in the wrong place | BetterVoice pastes into the window that has focus when you stop. Keep the cursor in the field until the text appears. |

## Send useful feedback

Report problems on [GitHub Issues](https://github.com/kerim0x1/bettervoice/issues). Describe what you did, what you expected, and what happened, and name the engine and your Windows version.

A log can help: **Settings… → General → Open log**. It contains status messages only — never what you dictated — but review it before posting and remove anything you don't want to share. API keys never appear in it.
