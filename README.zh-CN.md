# here

<p align="center">
  <img src="assets/system/picture/Icon.png" width="96" alt="here 应用图标">
</p>

<p align="center">
  <b>一个常驻桌面的 AI 伴侣，支持角色、记忆、语音、主动联系和状态自拍。</b>
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
  <a href="#-主要功能">主要功能</a>
  ·
  <a href="#-系统要求">系统要求</a>
  ·
  <a href="#-安装">安装</a>
  ·
  <a href="#-配置">配置</a>
  ·
  <a href="#-生图与自拍">生图与自拍</a>
  ·
  <a href="#-开发">开发</a>
  ·
  <a href="#license">License</a>
</p>

here 是一个常驻桌面的 AI 伴侣。它负责角色人设、长期记忆、日常状态、立绘动画、语音、输入、聊天演出、主动联系，以及可选的当前状态照片。

模型推理由 Hermes Agent 或内置 OpenAI-compatible Internal Agent 承担。生图能力采用适配器设计，因此 Grok Imagine、GPT Image、OpenAI-compatible 服务和未来新增的生图 API 都可以复用同一套主动联系附图流程。

## ✨ 主要功能

<p align="center">
  <img src="docs/assets/screenshot/feature-showcase-01.jpg" width="720" alt="here 主打展示图">
</p>

| 功能 | 说明 | 展示 |
| --- | --- | --- |
| 角色系统 | 创建、导入、编辑角色；维护人设、视觉身份、情绪标签、语音引用和角色包。 | <img src="docs/assets/screenshot/feature-character-01.png" width="120" alt="角色桌面预览"> <img src="docs/assets/screenshot/feature-character-02.png" width="150" alt="角色导入菜单"> <img src="docs/assets/screenshot/feature-character-03.png" width="150" alt="创建角色窗口"> |
| ASR 与 TTS | 支持麦克风语音输入、ASR 后端选择、TTS 播放和多服务语音配置。 | <img src="docs/assets/screenshot/feature-voice-01.png" width="135" alt="语音识别设置"> <img src="docs/assets/screenshot/feature-voice-02.png" width="135" alt="语音合成设置"> <img src="docs/assets/screenshot/feature-voice-03.png" width="120" alt="麦克风权限提示"> <img src="docs/assets/screenshot/feature-voice-04.png" width="120" alt="语音合成状态"> |
| 桌面聊天 | 对话、立绘切换、TTS 播放、麦克风输入、历史保存与恢复。 | <img src="docs/assets/screenshot/feature-chat-01.png" width="150" alt="桌面聊天与通话界面"> <img src="docs/assets/screenshot/feature-chat-02.png" width="150" alt="外部发送渠道配置"> <img src="docs/assets/screenshot/feature-chat-03.png" width="160" alt="外部聊天效果"> |
| Agent 后端 | 在主窗口菜单中选择 Hermes Agent、Internal Agent 或自动兜底。 |  |
| 主动联系 | 角色可按自己的日程状态主动联系用户，并可选择桌面、微信等送达渠道。 | <img src="docs/assets/screenshot/feature-proactive-01.png" width="110" alt="外部会话提醒"> <img src="docs/assets/screenshot/feature-proactive-02.png" width="120" alt="外部聊天内容"> |
| 主动附图 | 主动联系可附带根据角色身份、生活状态和可选参考图生成的自然状态照片。 | <img src="docs/assets/screenshot/feature-proactive-image-01.jpg" width="160" alt="主动联系附图"> |
| 可配置生图 API | image-api、Grok Imagine、GPT Image、OpenAI-compatible endpoint 和未来适配器都可以在不改调度器的情况下切换。 | <img src="docs/assets/screenshot/feature-image-api-01.png" width="220" alt="生图 API 设置"> |





## 💻 系统要求

| 项目 | 要求 |
| --- | --- |
| Python | Python 3.11。项目约束为 `<3.13`，因为 ASR 代码仍使用 `audioop`。 |
| 环境管理 | 源码安装和开发统一使用 [uv](https://docs.astral.sh/uv/)。 |
| 桌面 UI | PySide6 / Qt runtime。 |
| ASR | Windows 源码环境和打包版本默认提供轻量 Vosk 路线；`--with-asr` 用于安装完整 ASR extras，例如 faster-whisper、RealtimeSTT，以及非 Windows 源码环境需要的本地 ASR 依赖。 |
| TTS 和生图 API | 可选，可在 UI 填写 API Key，也可以通过环境变量提供。 |
| 外部送达 | 可选。微信等渠道需要各自的本地配置。 |

Windows 用户请把项目放在纯英文路径下，例如 `D:\here`，避免部分音频/Qt/嵌入式 Python 组件遇到非 ASCII 路径问题。

macOS 源码安装 ASR 时需要 Homebrew PortAudio，用来编译 `pyaudio`；打包版本会把 Vosk 需要的 PortAudio 动态库放进应用内。

## 📦 安装

### 源码运行

源码开发和运行统一使用 uv。不要直接用系统 Python 或手动 `pip install` 管理项目环境。
如果当前环境没有 uv，安装和启动脚本会通过 Astral 官方安装器自动安装。

Windows 用户请在 PowerShell 或命令提示符里运行批处理脚本：

```powershell
.\install.bat
.\start.bat
```

不要在 Windows 的 Git Bash 里运行 `.sh` 脚本；这些脚本只用于 macOS/Linux。

macOS 和 Linux 用户请运行 shell 脚本：

```bash
bash scripts/install.sh
bash scripts/start.sh
```

按需安装可选原生能力。不同平台使用相同参数名：

```powershell
.\install.bat --with-asr
.\install.bat --with-video
.\install.bat --with-background-removal
.\install.bat --with-hermes
.\install.bat --full
```

```bash
bash scripts/install.sh --with-asr
bash scripts/install.sh --with-video
bash scripts/install.sh --with-background-removal
bash scripts/install.sh --with-hermes
bash scripts/install.sh --full
```

| 参数 | 安装内容 | 对应功能 |
| --- | --- | --- |
| `--with-asr` | `pyaudio`、`vosk`、`faster-whisper`、`RealtimeSTT` | 完整 ASR extras：补充 faster-whisper、RealtimeSTT 等高级/替代后端，以及非 Windows 源码环境所需的本地语音依赖。Windows 基础 Vosk 路线不需要它。 |
| `--with-video` | `opencv_python` | 创建或编辑角色时，从视频文件抽帧导入为立绘动画。普通图片、多张图片帧和 Codex Pet 导入不需要它。 |
| `--with-background-removal` | `rembg` | 导入角色图片时使用 AI 去背，方便制作透明背景立绘。 |
| `--with-hermes` | `hermes-agent` | 把 Hermes Agent 安装进当前项目环境，用作本地 Agent 后端。需要 Git 和网络。 |
| `--full` | ASR、视频导入、AI 去背这些原生 extras | 一次性安装本地原生能力；不包含 Hermes Agent。 |

`--full` 只安装原生能力 extras，刻意不自动安装 Hermes Agent，因为它来自 GitHub 源码包。需要 here 帮当前环境安装 Hermes Agent 时，请显式使用 `--with-hermes`。

源码运行缺少 Vosk 模型时会在首次使用时下载。打包版本已内置中文小模型，默认 Vosk 后端首次使用不需要再下载模型。

### 打包版本

Release 包内包含启动脚本。源码开发仍建议使用 uv；打包包内脚本会优先使用自带 runtime。

macOS/Linux：

```bash
bash scripts/start.sh
```

Windows：

```bat
.\start.bat
```

## ⚙️ 配置

默认配置不包含真实密钥。源码运行时，本地配置会写入项目下的 `.local/here/`；打包应用会写入系统应用数据目录。你也可以用环境变量指定应用数据目录：

```bash
HERE_APP_HOME=/path/to/here-data uv run python -m app.desktop.main
```

主要配置入口：

| 配置 | 入口 |
| --- | --- |
| Agent 后端 | 主菜单「API / Agent 后端」 |
| TTS | 主菜单「TTS 设置」 |
| ASR | 主菜单「语音识别 ASR」 |
| 角色记忆和动画素材目录 | 主菜单「角色数据目录」 |
| 主动联系 | 主菜单「允许他/她主动找你」 |
| 微信等外部送达 | 主菜单「聊天平台设置」 |
| 主动联系附图 | 主菜单「主动联系自拍生图设置」 |

常用环境变量：

| 变量 | 用途 |
| --- | --- |
| `HERE_APP_HOME` | 覆盖 here 的本地配置、记忆、生成文件和状态目录。 |
| `OPENAI_API_KEY` | Internal Agent、OpenAI TTS、GPT Image 可复用。 |
| `FAL_KEY` / `XAI_API_KEY` | Grok Imagine / fal 风格生图接口。 |
| `OPENROUTER_API_KEY` | OpenRouter Grok Imagine。 |
| `ELEVENLABS_API_KEY` | ElevenLabs TTS。 |
| `MINIMAX_API_KEY` / `MINIMAX_GROUP_ID` | MiniMax TTS。 |
| `FISH_AUDIO_API_KEY` / `FISH_AUDIO_REFERENCE_ID` | Fish Audio TTS。 |
| `HERE_MESSAGING_CONFIG` | 覆盖外部消息渠道配置文件路径。 |
| `HERE_WECHAT_STATE_DIR` | 覆盖微信登录状态保存目录。 |

API Key 也可以直接在 UI 设置里填写。UI 写入的配置只保存在本地，不应提交到 Git。

## 🖼️ 生图与自拍

主动联系附图是主动联系流程的附属能力，不会单独驱动主动联系。启用后，角色在合适的主动联系时机会根据当前日常状态、角色视觉身份和可选参考图生成一张自然的状态照片。

<p align="center">
  <img src="docs/assets/screenshot/feature-selfie-example-01.jpg" width="420" alt="主动联系自拍示例">
</p>

支持的生图适配器包括：

| 适配器 | 说明 |
| --- | --- |
| `image-api` | OpenAI-compatible `/v1/images/generations` 或简易生图接口。 |
| `xai-grok-imagine` | fal / OpenRouter / OpenAI-compatible 风格的 Grok Imagine 配置。 |
| `openai-gpt-image` | OpenAI GPT Image images API，支持参考图编辑。 |

不同适配器的 URL、API Key、模型、尺寸、质量等参数可在「主动联系自拍生图设置」里单独配置。

## 🧰 开发

常用开发命令：

```bash
uv sync --python 3.11 --group dev
uv run pytest -q
uv run python -m compileall app core infrastructure internal_agent services ui main.py
```

上传 GitHub 或提交 PR 前，请先跑完整测试，并确认本地配置、API Key、生成媒体和 `.local/` 数据没有进入提交。

## License

here 使用 [PolyForm Noncommercial License 1.0.0](LICENSE) 发布。未经单独书面授权，不允许商业使用。
