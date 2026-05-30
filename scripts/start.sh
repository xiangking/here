#!/bin/bash

set -e

case "$(uname -s)" in
    MINGW*|MSYS*|CYGWIN*)
        echo "This script is for macOS/Linux."
        echo "On Windows, run .\\start.bat from the project root instead."
        exit 1
        ;;
esac

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${PROJECT_DIR}"

default_app_home() {
    case "$(uname -s)" in
        Darwin)
            echo "${HOME}/Library/Application Support/here"
            ;;
        *)
            if [ -n "${XDG_DATA_HOME:-}" ]; then
                echo "${XDG_DATA_HOME}/here"
            else
                echo "${HOME}/.local/share/here"
            fi
            ;;
    esac
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
        echo "Error: embedded Python not found, uv is not installed, and neither curl nor wget is available."
        echo "Install uv manually: https://docs.astral.sh/uv/getting-started/installation/"
        exit 1
    fi

    if ! command -v uv >/dev/null 2>&1; then
        echo "Error: uv installation finished, but uv is still not available in PATH."
        echo "Try opening a new terminal, or add ~/.local/bin to PATH."
        exit 1
    fi
}

# Check for embedded python, fall back to uv-managed source environment
if [ -f "runtime/bin/python3" ]; then
    PYTHON_EXE="runtime/bin/python3"
elif [ -f "runtime/python.exe" ]; then
    PYTHON_EXE="runtime/python.exe"
else
    ensure_uv
    uv run python -m app.desktop.main
    exit $?
fi

export HERE_PROJECT_ROOT="${PROJECT_DIR}"
export HERE_APP_HOME="${HERE_APP_HOME:-$(default_app_home)}"

"$PYTHON_EXE" -m app.desktop.main
