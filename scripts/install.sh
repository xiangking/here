#!/bin/bash
set -e

find_brew() {
    if command -v brew >/dev/null 2>&1; then
        command -v brew
        return 0
    fi

    if [ -x "/opt/homebrew/bin/brew" ]; then
        echo "/opt/homebrew/bin/brew"
        return 0
    fi

    if [ -x "/usr/local/bin/brew" ]; then
        echo "/usr/local/bin/brew"
        return 0
    fi

    return 1
}

ensure_uv() {
    export PATH="${HOME}/.local/bin:${HOME}/.cargo/bin:${PATH}"
    if command -v uv >/dev/null 2>&1; then
        return 0
    fi

    echo "uv not found. Installing uv..."
    if command -v curl >/dev/null 2>&1; then
        curl -LsSf https://astral.sh/uv/install.sh | sh
    elif command -v wget >/dev/null 2>&1; then
        wget -qO- https://astral.sh/uv/install.sh | sh
    else
        echo "Error: uv is not installed, and neither curl nor wget is available to install it."
        echo "Install uv manually: https://docs.astral.sh/uv/getting-started/installation/"
        exit 1
    fi

    if ! command -v uv >/dev/null 2>&1; then
        echo "Error: uv installation finished, but uv is still not available in PATH."
        echo "Try opening a new terminal, or add ~/.local/bin to PATH."
        exit 1
    fi
}

ensure_macos_audio_dependencies() {
    if [ "$(uname -s)" != "Darwin" ]; then
        return 0
    fi

    echo "Checking macOS audio build dependencies..."

    local brew_cmd
    if ! brew_cmd="$(find_brew)"; then
        echo "Error: Homebrew is required on macOS to install PortAudio for PyAudio."
        echo "Install Homebrew first: https://brew.sh/"
        exit 1
    fi

    eval "$("$brew_cmd" shellenv)"

    if ! brew list portaudio >/dev/null 2>&1; then
        echo "Installing PortAudio with Homebrew..."
        brew install portaudio
    fi

    local portaudio_prefix
    portaudio_prefix="$(brew --prefix portaudio)"
    export CPPFLAGS="-I${portaudio_prefix}/include ${CPPFLAGS:-}"
    export LDFLAGS="-L${portaudio_prefix}/lib ${LDFLAGS:-}"
    export PKG_CONFIG_PATH="${portaudio_prefix}/lib/pkgconfig${PKG_CONFIG_PATH:+:${PKG_CONFIG_PATH}}"
}

EXTRA_ARGS=()
NEEDS_AUDIO=0
NEEDS_GIT=0

while [ "$#" -gt 0 ]; do
    case "$1" in
        --with-asr|--asr)
            EXTRA_ARGS+=(--extra asr)
            NEEDS_AUDIO=1
            ;;
        --with-video|--video)
            EXTRA_ARGS+=(--extra video)
            ;;
        --with-background-removal|--background-removal)
            EXTRA_ARGS+=(--extra background-removal)
            ;;
        --with-hermes|--hermes)
            EXTRA_ARGS+=(--extra hermes)
            NEEDS_GIT=1
            ;;
        --full)
            EXTRA_ARGS+=(--extra full)
            NEEDS_AUDIO=1
            ;;
        *)
            echo "Unknown option: $1"
            echo "Supported options: --with-asr --with-video --with-background-removal --with-hermes --full"
            exit 1
            ;;
    esac
    shift
done

echo "========================================"
echo "  Installing..."
echo "========================================"
echo ""

ensure_uv

if [ "$NEEDS_AUDIO" -eq 1 ]; then
    ensure_macos_audio_dependencies
fi

if [ "$NEEDS_GIT" -eq 1 ] && ! command -v git >/dev/null 2>&1; then
    echo "Error: Git is required only when installing the local Hermes Agent package into this environment."
    echo "Install Git first, then rerun scripts/install.sh --with-hermes."
    exit 1
fi

echo "Installing dependencies..."
echo ""

uv sync --python 3.11 "${EXTRA_ARGS[@]}"

echo ""
echo "========================================"
echo "  Installation complete!"
echo "========================================"
echo ""
echo "You can now run scripts/start.sh to launch the application"
