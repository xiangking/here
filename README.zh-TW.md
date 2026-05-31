# here

<p align="center">
  <img src="assets/system/picture/Icon.png" width="96" alt="here 應用程式圖示">
</p>

<p align="center">
  <b>一個常駐桌面的 AI 伴侶，支援角色、記憶、語音、主動聯絡與狀態自拍。</b>
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

here 是一個常駐桌面的 AI 伴侶。它負責角色設定、長期記憶、日常狀態、立繪動畫、語音、輸入、聊天呈現、主動聯絡，以及可選的目前狀態照片。

模型推理會優先使用使用者本機已安裝並設定好的 Hermes Agent；專案內建的 OpenAI-compatible Internal Agent 主要作為輕量兜底。生圖能力採用適配器設計，因此 Grok Imagine、GPT Image、OpenAI-compatible 服務和未來新增的生圖 API 都可以共用同一套主動聯絡附圖流程。

## ✨ 主要功能

<p align="center">
  <img src="docs/assets/screenshot/feature-showcase-01.jpg" width="720" alt="here 主打展示圖">
</p>

| 功能 | 說明 | 展示 |
| --- | --- | --- |
| 角色系統 | 建立、匯入、編輯角色；維護人設、視覺身份、情緒標籤、語音引用和角色包。 | <img src="docs/assets/screenshot/feature-character-01.png" width="120" alt="角色桌面預覽"> <img src="docs/assets/screenshot/feature-character-02.png" width="150" alt="角色匯入選單"> <img src="docs/assets/screenshot/feature-character-03.png" width="150" alt="建立角色視窗"> |
| ASR 與 TTS | 支援麥克風語音輸入、ASR 後端選擇、TTS 播放和多服務語音設定。 | <img src="docs/assets/screenshot/feature-voice-01.png" width="135" alt="語音辨識設定"> <img src="docs/assets/screenshot/feature-voice-02.png" width="135" alt="語音合成設定"> <img src="docs/assets/screenshot/feature-voice-03.png" width="120" alt="麥克風權限提示"> <img src="docs/assets/screenshot/feature-voice-04.png" width="120" alt="語音合成狀態"> |
| 桌面聊天 | 對話、立繪切換、TTS 播放、麥克風輸入、歷史保存與恢復。 | <img src="docs/assets/screenshot/feature-chat-01.png" width="150" alt="桌面聊天與通話介面"> <img src="docs/assets/screenshot/feature-chat-02.png" width="150" alt="外部送達設定"> <img src="docs/assets/screenshot/feature-chat-03.png" width="160" alt="外部聊天效果"> |
| Agent 後端 | 在主視窗選單中選擇使用者本機 Hermes Agent、專案內建 Internal Agent 兜底，或自動選擇。 |  |
| 主動聯絡 | 角色可依自己的日程狀態主動聯絡使用者，並可選擇桌面、微信等送達渠道。 | <img src="docs/assets/screenshot/feature-proactive-01.png" width="110" alt="外部會話提醒"> <img src="docs/assets/screenshot/feature-proactive-02.png" width="120" alt="外部聊天內容"> |
| 主動附圖 | 主動聯絡可附帶根據角色身份、生活狀態和可選參考圖生成的自然狀態照片。 | <img src="docs/assets/screenshot/feature-proactive-image-01.jpg" width="160" alt="主動聯絡附圖"> |
| 可配置生圖 API | image-api、Grok Imagine、GPT Image、OpenAI-compatible endpoint 和未來適配器都可以在不改調度器的情況下切換。 | <img src="docs/assets/screenshot/feature-image-api-01.png" width="220" alt="生圖 API 設定"> |

## 💻 系統需求

| 項目 | 需求 |
| --- | --- |
| Python | 已驗證 Python 3.11 到 3.13。 |
| 環境管理 | 原始碼安裝和開發統一使用 [uv](https://docs.astral.sh/uv/)。 |
| 桌面 UI | PySide6 / Qt runtime。 |
| 可選原生能力 | 本機 ASR、影片立繪匯入、AI 去背都作為可選 extras，預設安裝和發行包會更輕。 |
| 本機 Hermes Agent | 如果目前專案環境還沒有安裝 Hermes Agent，可透過 `--with-hermes` 輔助安裝。這個 extra 來自 GitHub，需要 Git 和網路存取。 |
| ASR | Windows 原始碼環境和打包版本預設提供輕量 Vosk 路線；`--with-asr` 用於安裝完整 ASR extras，例如 faster-whisper、RealtimeSTT，以及非 Windows 原始碼環境需要的本機 ASR 依賴。 |
| TTS 和生圖 API | 可選，可在 UI 填寫 API Key，也可以透過環境變數提供。 |
| 外部送達 | 可選。微信等渠道需要各自的本機設定。 |

Windows 使用者請把專案放在純英文路徑下，例如 `D:\here`，避免部分音訊/Qt/嵌入式 Python 元件遇到非 ASCII 路徑問題。

Apple Silicon macOS 上，可選 ASR 安裝會跳過 `vosk`，因為目前官方 Vosk wheel 不覆蓋 darwin arm64。語音辨識請在「語音辨識 ASR」裡選擇 `faster-whisper` 或 `RealtimeSTT`；Intel macOS、Windows 和 Linux 仍可安裝 Vosk。

## 📦 安裝

### 原始碼執行

原始碼開發和執行統一使用 uv。不要直接用系統 Python 或手動 `pip install` 管理專案環境。
如果目前環境沒有 uv，安裝和啟動腳本會透過 Astral 官方安裝器自動安裝。

Windows 使用者請在 PowerShell 或命令提示字元中執行批次腳本：

```powershell
.\install.bat
.\start.bat
```

不要在 Windows 的 Git Bash 裡執行 `.sh` 腳本；這些腳本只用於 macOS/Linux。

macOS 和 Linux 使用者請執行 shell 腳本：

```bash
bash scripts/install.sh
bash scripts/start.sh
```

按需安裝可選原生能力。不同平台使用相同參數名：

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

| 參數 | 安裝內容 | 對應功能 |
| --- | --- | --- |
| `--with-asr` | `pyaudio`、`vosk`、`faster-whisper`、`RealtimeSTT` | 完整 ASR extras：補充 faster-whisper、RealtimeSTT 等進階/替代後端，以及非 Windows 原始碼環境所需的本機語音依賴。Windows 基礎 Vosk 路線不需要它。 |
| `--with-video` | `opencv_python` | 建立或編輯角色時，從影片檔抽幀匯入為立繪動畫。一般圖片、多張圖片幀和 Codex Pet 匯入不需要它。 |
| `--with-background-removal` | `rembg` | 匯入角色圖片時使用 AI 去背，方便製作透明背景立繪。 |
| `--with-hermes` | `hermes-agent` | 把 Hermes Agent 安裝進目前專案環境，用作本機 Agent 後端。需要 Git 和網路。 |
| `--full` | ASR、影片匯入、AI 去背這些原生 extras | 一次安裝本機原生能力；不包含 Hermes Agent。 |

`--full` 只安裝原生能力 extras，刻意不自動安裝 Hermes Agent，因為它來自 GitHub 原始碼包。需要 here 幫目前環境安裝 Hermes Agent 時，請明確使用 `--with-hermes`。

macOS 上 ASR extras 需要 Homebrew PortAudio。安裝腳本會先檢查 Homebrew，並在執行 `uv sync --extra asr` 前安裝 `portaudio`，避免全新環境裡 `pyaudio` 編譯失敗。

ASR 模型檔不會提交進倉庫或打進預設包。麥克風發現缺少 Vosk 模型時，here 會打開「語音辨識 ASR」，把中文小模型下載到應用資料目錄的 `models` 資料夾，並自動儲存模型路徑。

### 打包版本

Release 包內包含啟動腳本。原始碼開發仍建議使用 uv；打包包內腳本會優先使用自帶 runtime。

從原始碼樹建立本機 macOS 包：

```bash
python3 scripts/build_bundle.py --target macos-arm64 --name here-local-macos-arm64-lite
```

GitHub Release 會透過 `.github/workflows/release.yml` 建立 macOS arm64 和 Windows x64 包。請使用對應平台的啟動腳本。

macOS/Linux：

```bash
bash scripts/start.sh
```

Windows：

```powershell
.\start.bat
```

發行包預設採用輕量依賴，不內建本機 ASR、影片匯入或 AI 去背依賴。

## ⚙️ 設定

預設設定不包含真實密鑰。原始碼執行時，本機設定會寫入專案下的 `.local/here/`；打包應用會寫入系統應用資料目錄。你也可以用環境變數指定應用資料目錄：

```bash
HERE_APP_HOME=/path/to/here-data uv run python -m app.desktop.main
```

| 設定 | 入口 |
| --- | --- |
| Agent 後端 | 主選單「API / Agent 後端」 |
| TTS | 主選單「TTS 設定」 |
| ASR | 主選單「語音辨識 ASR」 |
| 角色記憶和動畫素材目錄 | 主選單「角色資料目錄」 |
| 主動聯絡 | 主選單「允許他/她主動找你」 |
| 微信等外部送達 | 主選單「聊天平台設定」 |
| 主動聯絡附圖 | 主選單「主動聯絡自拍生圖設定」 |

常用環境變數：

| 變數 | 用途 |
| --- | --- |
| `HERE_APP_HOME` | 覆蓋 here 的本機設定、記憶、生成檔案和狀態目錄。 |
| `OPENAI_API_KEY` | Internal Agent、OpenAI TTS、GPT Image 可共用。 |
| `FAL_KEY` / `XAI_API_KEY` | Grok Imagine / fal 風格生圖接口。 |
| `OPENROUTER_API_KEY` | OpenRouter Grok Imagine。 |
| `ELEVENLABS_API_KEY` | ElevenLabs TTS。 |
| `MINIMAX_API_KEY` / `MINIMAX_GROUP_ID` | MiniMax TTS。 |
| `FISH_AUDIO_API_KEY` / `FISH_AUDIO_REFERENCE_ID` | Fish Audio TTS。 |
| `HERE_MESSAGING_CONFIG` | 覆蓋外部訊息渠道設定檔路徑。 |
| `HERE_WECHAT_STATE_DIR` | 覆蓋微信登入狀態保存目錄。 |

API Key 也可以直接在 UI 設定裡填寫。UI 寫入的設定只保存在本機，不應提交到 Git。

## 🖼️ 生圖與自拍

主動聯絡附圖是主動聯絡流程的附屬能力，不會單獨驅動主動聯絡。啟用後，角色在合適的主動聯絡時機會根據目前日常狀態、角色視覺身份和可選參考圖生成一張自然的狀態照片。

<p align="center">
  <img src="docs/assets/screenshot/feature-selfie-example-01.jpg" width="420" alt="主動聯絡自拍範例">
</p>

| 適配器 | 說明 |
| --- | --- |
| `image-api` | OpenAI-compatible `/v1/images/generations` 或簡易生圖接口。 |
| `xai-grok-imagine` | fal / OpenRouter / OpenAI-compatible 風格的 Grok Imagine 設定。 |
| `openai-gpt-image` | OpenAI GPT Image images API，支援參考圖編輯。 |

不同適配器的 URL、API Key、模型、尺寸、品質等參數可在「主動聯絡自拍生圖設定」裡單獨配置。

## 🧰 開發

```bash
uv sync --python 3.11 --group dev
uv run pytest -q
uv run python -m compileall app core infrastructure internal_agent services ui main.py
```

上傳 GitHub 或提交 PR 前，請先跑完整測試，並確認本機設定、API Key、生成媒體和 `.local/` 資料沒有進入提交。

## License

here 使用 [PolyForm Noncommercial License 1.0.0](LICENSE) 發布。未經單獨書面授權，不允許商業使用。
