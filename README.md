# here

<p align="center">
  <img src="assets/system/picture/Icon.png" width="96" alt="here app icon">
</p>

<p align="center">
  <b>A desktop-resident AI companion with characters, memory, speech, proactive contact, and image selfies.</b>
</p>

<p align="center">
  <a href="README.md">English</a>
  ·
  <a href="README.zh-CN.md">简体中文</a>
  ·
  <a href="README.zh-TW.md">繁體中文</a>
  ·
  <a href="README.ja.md">日本語</a>
  ·
  <a href="README.ko.md">한국어</a>
</p>

<p align="center">
  <img alt="Python" src="https://img.shields.io/badge/Python-3.11-blue?logo=python">
  <img alt="uv" src="https://img.shields.io/badge/uv-managed-6f42c1">
  <img alt="PySide6" src="https://img.shields.io/badge/PySide6-Qt-green?logo=qt">
  <img alt="License" src="https://img.shields.io/badge/License-PolyForm%20NC%201.0.0-blue">
</p>

<p align="center">
  <a href="#-features">Features</a>
  ·
  <a href="#-requirements">Requirements</a>
  ·
  <a href="#-installation">Installation</a>
  ·
  <a href="#-configuration">Configuration</a>
  ·
  <a href="#-image-generation-and-selfies">Image Generation</a>
  ·
  <a href="#-development">Development</a>
  ·
  <a href="#license">License</a>
</p>

here is a desktop AI companion that stays with the user instead of behaving like a disposable chat box. It owns character profiles, long-term memory, daily state, animated sprites, speech, input, chat presentation, proactive contact, and optional current-state photos.

Model reasoning is handled by Hermes Agent or the bundled OpenAI-compatible Internal Agent. Image generation is adapter-based so Grok Imagine, GPT Image, OpenAI-compatible services, and future providers can share the same proactive photo flow.

## ✨ Features

| Feature | Description |
| --- | --- |
| Character system | Create, import, and edit personas, visual identity, emotion tags, voice references, and character bundles. |
| Memory and asset folders | Choose where character memory and animation assets live, including external drives. |
| Desktop chat | Dialog, sprite switching, TTS playback, microphone input, history save and restore. |
| Agent backend | Choose Hermes Agent, Internal Agent, or automatic fallback from the main menu. |
| Proactive contact | Characters can reach out based on their own daily state through desktop chat or external delivery channels such as WeChat. |
| Proactive photos | Proactive contact can attach a natural current-state photo generated from character identity, life state, and optional reference images. |
| Configurable image APIs | Switch image-api, Grok Imagine, GPT Image, OpenAI-compatible endpoints, and future adapters without changing the scheduler. |

## 💻 Requirements

| Item | Requirement |
| --- | --- |
| Python | Python 3.11. The project is constrained to `<3.13` because `audioop` is still used by ASR code. |
| Environment manager | [uv](https://docs.astral.sh/uv/) is required for source installs and development. |
| Desktop UI | PySide6 / Qt runtime. |
| macOS audio build dependency | Homebrew PortAudio is required by PyAudio. `scripts/install.sh` installs it automatically when Homebrew is available. |
| ASR | Optional. Vosk, faster-whisper, or RealtimeSTT can be selected in the ASR settings. |
| TTS and image APIs | Optional. API keys can be entered in the UI or provided through environment variables. |
| External delivery | Optional. WeChat and other delivery channels need their own local configuration. |

On Windows, keep the project in an ASCII-only path such as `D:\here` to avoid path issues in audio, Qt, or embedded Python components.

On Apple Silicon macOS, `uv sync` skips `vosk` because the current official Vosk wheels do not cover darwin arm64. Choose `faster-whisper` or `RealtimeSTT` in `Speech recognition ASR`; Vosk remains installable on Intel macOS, Windows, and Linux.

## 📦 Installation

### Source Run

Source development and runtime are managed with uv. Do not manage the project environment with a system Python or manual `pip install`.

```bash
bash scripts/install.sh
uv run python -m app.desktop.main
```

On macOS, the installer checks Homebrew and installs `portaudio` before running `uv sync`, so `pyaudio` can build from a clean environment.

### Packaged Builds

Release bundles include start scripts. Source development should still use uv; packaged scripts prefer the bundled runtime when available.

```bash
bash scripts/start.sh
```

```bat
start.bat
```

## ⚙️ Configuration

Default configs contain no real secrets. Source runs store local data under `.local/here/`; packaged apps use the platform application data directory. You can override the app data root:

```bash
HERE_APP_HOME=/path/to/here-data uv run python -m app.desktop.main
```

Main configuration entry points:

| Setting | UI |
| --- | --- |
| Agent backend | Main menu: `API / Agent backend` |
| TTS | Main menu: `TTS settings` |
| ASR | Main menu: `Speech recognition ASR` |
| Character memory and animation folders | Main menu: `Character data folders` |
| Proactive contact | Main menu: `Let her reach out first` |
| External delivery such as WeChat | Main menu: `Chat platform settings` |
| Proactive photo generation | Main menu: `Proactive selfie image settings` |

Useful environment variables:

| Variable | Purpose |
| --- | --- |
| `HERE_APP_HOME` | Override local config, memory, generated files, and state directory. |
| `OPENAI_API_KEY` | Used by Internal Agent, OpenAI TTS, and GPT Image. |
| `FAL_KEY` / `XAI_API_KEY` | Used by Grok Imagine / fal-style image APIs. |
| `OPENROUTER_API_KEY` | Used by OpenRouter Grok Imagine. |
| `ELEVENLABS_API_KEY` | Used by ElevenLabs TTS. |
| `MINIMAX_API_KEY` / `MINIMAX_GROUP_ID` | Used by MiniMax TTS. |
| `FISH_AUDIO_API_KEY` / `FISH_AUDIO_REFERENCE_ID` | Used by Fish Audio TTS. |
| `HERE_MESSAGING_CONFIG` | Override external messaging config path. |
| `HERE_WECHAT_STATE_DIR` | Override WeChat login state directory. |

API keys can also be entered in the UI. UI-written config is local-only and should not be committed.

## 🖼️ Image Generation And Selfies

Proactive photos are an attachment capability of proactive contact; they do not drive the proactive scheduler by themselves. When enabled, the character may generate a natural current-state photo from daily state, visual identity, and an optional reference image.

Supported image adapters:

| Adapter | Description |
| --- | --- |
| `image-api` | OpenAI-compatible `/v1/images/generations` or simple image API. |
| `xai-grok-imagine` | fal / OpenRouter / OpenAI-compatible Grok Imagine configuration. |
| `openai-gpt-image` | OpenAI GPT Image images API with reference-image edits. |

Each adapter exposes its own URL, API key, model, size, quality, and related options in `Proactive selfie image settings`.

## 🧰 Development

Common development commands:

```bash
uv sync --python 3.11 --group dev
uv run pytest -q
uv run python -m compileall app core infrastructure internal_agent services ui main.py
```

Before opening a pull request or uploading to GitHub, run the test suite and make sure local config, API keys, generated media, and `.local/` data are not committed.

## License

here is released under the [PolyForm Noncommercial License 1.0.0](LICENSE). Commercial use is not permitted without separate written permission.
