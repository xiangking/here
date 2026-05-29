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

| 機能 | 説明 |
| --- | --- |
| キャラクターシステム | ペルソナ、視覚的アイデンティティ、感情タグ、音声参照、キャラクターパックを作成・インポート・編集できます。 |
| 記憶と素材フォルダー | キャラクターの長期記憶とアニメーション素材の保存場所を選択できます。外部ドライブにも配置できます。 |
| デスクトップチャット | 会話、立ち絵切り替え、TTS 再生、マイク入力、履歴の保存と復元を行います。 |
| Agent バックエンド | メインメニューからユーザー環境の Hermes Agent、同梱 Internal Agent フォールバック、自動選択を選べます。 |
| 主动連絡 | キャラクターが自分の日常状態に基づいて、デスクトップチャットや WeChat などの外部チャンネルへ自然に連絡できます。 |
| 主动写真 | キャラクターの見た目、生活状態、任意の参照画像から自然な現在状態写真を添付できます。 |
| 設定可能な画像 API | image-api、Grok Imagine、GPT Image、OpenAI-compatible endpoint、今後のアダプターをスケジューラー変更なしで切り替えられます。 |

## 💻 要件

| 項目 | 要件 |
| --- | --- |
| Python | Python 3.11。ASR コードがまだ `audioop` を使用しているため、プロジェクトは `<3.13` に制限されています。 |
| 環境管理 | ソース実行と開発には [uv](https://docs.astral.sh/uv/) を使用します。 |
| デスクトップ UI | PySide6 / Qt runtime。 |
| 任意のネイティブ機能 | ローカル ASR、動画スプライト取り込み、AI 背景削除は任意 extras です。標準インストールとリリースパッケージを軽く保ちます。 |
| ローカル Hermes Agent | 現在のプロジェクト環境に Hermes Agent がまだ入っていない場合は、`bash scripts/install.sh --with-hermes` で補助インストールできます。この extra は GitHub から取得され、Git とネットワークアクセスが必要です。 |
| ASR | 任意。Vosk、faster-whisper、RealtimeSTT を使う前に `bash scripts/install.sh --with-asr` を実行してください。 |
| TTS と画像 API | 任意。API Key は UI または環境変数で設定できます。 |
| 外部配信 | 任意。WeChat などのチャンネルは個別のローカル設定が必要です。 |

Windows では、音声、Qt、組み込み Python コンポーネントのパス問題を避けるため、`D:\here` のような ASCII のみのパスに置いてください。

Apple Silicon macOS では、任意 ASR インストール時に `vosk` をスキップします。現在の公式 Vosk wheel が darwin arm64 をカバーしていないためです。`Speech recognition ASR` で `faster-whisper` または `RealtimeSTT` を選択してください。Intel macOS、Windows、Linux では Vosk を利用できます。

## 📦 インストール

### ソースから実行

ソース実行と開発は uv で管理します。システム Python や手動の `pip install` で環境を管理しないでください。
uv がまだ使えない環境では、インストール/起動スクリプトが Astral 公式インストーラで自動インストールします。

```bash
bash scripts/install.sh
uv run python -m app.desktop.main
```

必要に応じて任意機能を追加できます:

```bash
bash scripts/install.sh --with-asr
bash scripts/install.sh --with-video
bash scripts/install.sh --with-background-removal
bash scripts/install.sh --with-hermes
bash scripts/install.sh --full
```

`--full` はネイティブ extras のみをインストールし、Hermes Agent は自動では入れません。Hermes Agent は GitHub のソースパッケージから取得するため、この環境へ here からインストールしたい場合だけ `--with-hermes` を指定してください。

macOS で ASR extras を使うには Homebrew PortAudio が必要です。インストーラは Homebrew を確認し、`uv sync --extra asr` の前に `portaudio` をインストールするため、クリーン環境でも `pyaudio` をビルドできます。

### パッケージ版

Release パッケージには起動スクリプトが含まれています。ソース開発では uv を使い、パッケージ版スクリプトは同梱 runtime を優先します。

ソースツリーからローカル macOS パッケージを作成します:

```bash
python3 scripts/build_bundle.py --target macos-arm64 --name here-local-macos-arm64-lite
```

GitHub Releases は `.github/workflows/release.yml` で macOS arm64 と Windows x64 のパッケージを作成します。

```bash
bash scripts/start.sh
```

```bat
start.bat
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
