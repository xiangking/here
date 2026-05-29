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

echo "========================================"
echo "  Installing..."
echo "========================================"
echo ""

# Check if uv exists
if ! command -v uv &> /dev/null; then
    echo "Error: uv not found in PATH"
    echo "Install uv first: https://docs.astral.sh/uv/getting-started/installation/"
    exit 1
fi

ensure_macos_audio_dependencies

echo "Installing dependencies..."
echo ""

uv sync --python 3.11

echo ""
echo "========================================"
echo "  Installation complete!"
echo "========================================"
echo ""
echo "You can now run scripts/start.sh to launch the application"
