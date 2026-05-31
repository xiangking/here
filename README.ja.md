# here

<p align="center">
  <img src="assets/system/picture/Icon.png" width="96" alt="here app icon">
</p>

<p align="center">
  <b>キャラクター、記憶、音声、主动連絡、状態セルフィーを備えたデスクトップ常駐 AI コンパニオン。</b>
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

here はデスクトップに常駐する AI コンパニオンです。キャラクター設定、長期記憶、日常状態、スプライトアニメーション、音声、入力、チャット表示、主动連絡、任意の現在状態写真を扱います。

モデル推論は、ユーザー環境にインストール済みで設定済みの Hermes Agent を優先して使います。同梱の OpenAI-compatible Internal Agent は軽量フォールバックです。画像生成はアダプター方式なので、Grok Imagine、GPT Image、OpenAI-compatible サービス、今後追加される画像 API を同じ主动写真フローで利用できます。

## ✨ 主な機能

<p align="center">
  <img src="docs/assets/screenshot/feature-showcase-01.jpg" width="720" alt="here showcase">
</p>

| 機能 | 説明 | プレビュー |
| --- | --- | --- |
| キャラクターシステム | ペルソナ、視覚的アイデンティティ、感情タグ、音声参照、キャラクターパックを作成・インポート・編集できます。 | <img src="docs/assets/screenshot/feature-character-01.png" width="120" alt="キャラクターデスクトッププレビュー"> <img src="docs/assets/screenshot/feature-character-02.png" width="150" alt="キャラクターインポートメニュー"> <img src="docs/assets/screenshot/feature-character-03.png" width="150" alt="キャラクター作成ウィンドウ"> |
| ASR と TTS | マイク音声入力、ASR バックエンド選択、TTS 再生、複数サービスの音声設定に対応します。 | <img src="docs/assets/screenshot/feature-voice-01.png" width="135" alt="音声認識設定"> <img src="docs/assets/screenshot/feature-voice-02.png" width="135" alt="音声合成設定"> <img src="docs/assets/screenshot/feature-voice-03.png" width="120" alt="マイク権限プロンプト"> <img src="docs/assets/screenshot/feature-voice-04.png" width="120" alt="音声合成ステータス"> |
| デスクトップチャット | 会話、立ち絵切り替え、TTS 再生、マイク入力、履歴の保存と復元を行います。 | <img src="docs/assets/screenshot/feature-chat-01.png" width="150" alt="デスクトップチャットと通話 UI"> <img src="docs/assets/screenshot/feature-chat-02.png" width="150" alt="外部配信設定"> <img src="docs/assets/screenshot/feature-chat-03.png" width="160" alt="外部チャットプレビュー"> |
| Agent バックエンド | メインメニューからユーザー環境の Hermes Agent、同梱 Internal Agent フォールバック、自動選択を選べます。 |  |
| 主动連絡 | キャラクターが自分の日常状態に基づいて、デスクトップチャットや WeChat などの外部チャンネルへ自然に連絡できます。 | <img src="docs/assets/screenshot/feature-proactive-01.png" width="110" alt="外部会話通知"> <img src="docs/assets/screenshot/feature-proactive-02.png" width="120" alt="外部チャット内容"> |
| 主动写真 | キャラクターの見た目、生活状態、任意の参照画像から自然な現在状態写真を添付できます。 | <img src="docs/assets/screenshot/feature-proactive-image-01.jpg" width="160" alt="主动写真プレビュー"> |
| 設定可能な画像 API | image-api、Grok Imagine、GPT Image、OpenAI-compatible endpoint、今後のアダプターをスケジューラー変更なしで切り替えられます。 | <img src="docs/assets/screenshot/feature-image-api-01.png" width="220" alt="画像 API 設定"> |

## 💻 要件

| 項目 | 要件 |
| --- | --- |
| Python | Python 3.11 から 3.13 で検証済み。 |
| 環境管理 | ソース実行と開発には [uv](https://docs.astral.sh/uv/) を使用します。 |
| デスクトップ UI | PySide6 / Qt runtime。 |
| 任意のネイティブ機能 | ローカル ASR、動画スプライト取り込み、AI 背景削除は任意 extras です。標準インストールとリリースパッケージを軽く保ちます。 |
| ローカル Hermes Agent | 現在のプロジェクト環境に Hermes Agent がまだ入っていない場合は、`--with-hermes` で補助インストールできます。この extra は GitHub から取得され、Git とネットワークアクセスが必要です。 |
| ASR | 音声入力にはモデルファイルを同梱しません。Windows では軽量な Vosk runtime を標準で入れ、初回マイク使用時に ASR 設定から Vosk モデルをダウンロードして自動設定できます。faster-whisper、RealtimeSTT、またはソース環境で全 ASR backend が必要な場合は `--with-asr` を使ってください。 |
| TTS と画像 API | 任意。API Key は UI または環境変数で設定できます。 |
| 外部配信 | 任意。WeChat などのチャンネルは個別のローカル設定が必要です。 |

Windows では、音声、Qt、組み込み Python コンポーネントのパス問題を避けるため、`D:\here` のような ASCII のみのパスに置いてください。

Apple Silicon macOS では、任意 ASR インストール時に `vosk` をスキップします。現在の公式 Vosk wheel が darwin arm64 をカバーしていないためです。`Speech recognition ASR` で `faster-whisper` または `RealtimeSTT` を選択してください。Intel macOS、Windows、Linux では Vosk を利用できます。

## 📦 インストール

### ソースから実行

ソース実行と開発は uv で管理します。システム Python や手動の `pip install` で環境を管理しないでください。
uv がまだ使えない環境では、インストール/起動スクリプトが Astral 公式インストーラで自動インストールします。

Windows では PowerShell または Command Prompt から batch script を実行してください:

```powershell
.\install.bat
.\start.bat
```

Windows の Git Bash から `.sh` script を実行しないでください。`.sh` script は macOS/Linux 用です。

macOS と Linux では shell script を実行してください:

```bash
bash scripts/install.sh
bash scripts/start.sh
```

必要に応じて任意機能を追加できます。各プラットフォームで同じオプション名を使います:

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

`--full` はネイティブ extras のみをインストールし、Hermes Agent は自動では入れません。Hermes Agent は GitHub のソースパッケージから取得するため、この環境へ here からインストールしたい場合だけ `--with-hermes` を指定してください。

macOS で ASR extras を使うには Homebrew PortAudio が必要です。インストーラは Homebrew を確認し、`uv sync --extra asr` の前に `portaudio` をインストールするため、クリーン環境でも `pyaudio` をビルドできます。

ASR モデルファイルはリポジトリや標準パッケージには含めません。マイク使用時に Vosk モデルが見つからない場合、here は `Speech recognition ASR` を開き、中国語 small モデルをアプリデータの `models` フォルダへダウンロードし、パスを自動保存します。

### パッケージ版

Release パッケージには起動スクリプトが含まれています。ソース開発では uv を使い、パッケージ版スクリプトは同梱 runtime を優先します。

ソースツリーからローカル macOS パッケージを作成します:

```bash
python3 scripts/build_bundle.py --target macos-arm64 --name here-local-macos-arm64-lite
```

GitHub Releases は `.github/workflows/release.yml` で macOS arm64 と Windows x64 のパッケージを作成します。環境に合う起動スクリプトを使ってください。

macOS/Linux:

```bash
bash scripts/start.sh
```

Windows:

```powershell
.\start.bat
```

Release bundles are intentionally lightweight and do not include local ASR, video import, or AI background-removal dependencies by default.

## ⚙️ 設定

デフォルト設定には実際のシークレットは含まれません。ソース実行時のローカルデータは `.local/here/` に保存され、パッケージ版は各 OS のアプリケーションデータディレクトリを使います。アプリデータのルートは環境変数で上書きできます。

```bash
HERE_APP_HOME=/path/to/here-data uv run python -m app.desktop.main
```

| 設定 | UI |
| --- | --- |
| Agent バックエンド | Main menu: `API / Agent backend` |
| TTS | Main menu: `TTS settings` |
| ASR | Main menu: `Speech recognition ASR` |
| キャラクター記憶とアニメ素材 | Main menu: `Character data folders` |
| 主动連絡 | Main menu: `Let her reach out first` |
| WeChat などの外部配信 | Main menu: `Chat platform settings` |
| 主动写真生成 | Main menu: `Proactive selfie image settings` |

主な環境変数:

| 変数 | 用途 |
| --- | --- |
| `HERE_APP_HOME` | ローカル設定、記憶、生成ファイル、状態ディレクトリを上書きします。 |
| `OPENAI_API_KEY` | Internal Agent、OpenAI TTS、GPT Image で使用します。 |
| `FAL_KEY` / `XAI_API_KEY` | Grok Imagine / fal 形式の画像 API で使用します。 |
| `OPENROUTER_API_KEY` | OpenRouter Grok Imagine で使用します。 |
| `ELEVENLABS_API_KEY` | ElevenLabs TTS で使用します。 |
| `MINIMAX_API_KEY` / `MINIMAX_GROUP_ID` | MiniMax TTS で使用します。 |
| `FISH_AUDIO_API_KEY` / `FISH_AUDIO_REFERENCE_ID` | Fish Audio TTS で使用します。 |
| `HERE_MESSAGING_CONFIG` | 外部メッセージチャンネル設定ファイルのパスを上書きします。 |
| `HERE_WECHAT_STATE_DIR` | WeChat ログイン状態の保存ディレクトリを上書きします。 |

API Key は UI からも入力できます。UI が書き込む設定はローカル専用で、Git にコミットしないでください。

## 🖼️ 画像生成とセルフィー

主动写真は主动連絡の添付機能であり、スケジューラー自体を駆動しません。有効にすると、キャラクターは適切な主动連絡タイミングで、日常状態、視覚的アイデンティティ、任意の参照画像から自然な現在状態写真を生成できます。

| アダプター | 説明 |
| --- | --- |
| `image-api` | OpenAI-compatible `/v1/images/generations` またはシンプルな画像 API。 |
| `xai-grok-imagine` | fal / OpenRouter / OpenAI-compatible 形式の Grok Imagine 設定。 |
| `openai-gpt-image` | 参照画像編集に対応した OpenAI GPT Image images API。 |

各アダプターの URL、API Key、モデル、サイズ、品質などは `Proactive selfie image settings` で個別に設定できます。

## 🧰 開発

```bash
uv sync --python 3.11 --group dev
uv run pytest -q
uv run python -m compileall app core infrastructure internal_agent services ui main.py
```

GitHub へアップロードまたは PR を作成する前に、テストを実行し、ローカル設定、API Key、生成メディア、`.local/` データがコミットに含まれていないことを確認してください。

## License

here は [PolyForm Noncommercial License 1.0.0](LICENSE) の下で公開されています。別途書面による許可がない限り、商用利用はできません。
