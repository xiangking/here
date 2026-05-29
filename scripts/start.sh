#!/bin/bash

# Check for embedded python, fall back to uv-managed source environment
if [ -f "runtime/bin/python3" ]; then
    PYTHON_EXE="runtime/bin/python3"
elif [ -f "runtime/python.exe" ]; then
    PYTHON_EXE="runtime/python.exe"
else
    if ! command -v uv &> /dev/null; then
        echo "Error: embedded Python not found and uv is not in PATH"
        echo "Install uv first: https://docs.astral.sh/uv/getting-started/installation/"
        exit 1
    fi
    uv run python -m app.desktop.main
    exit $?
fi

$PYTHON_EXE -m app.desktop.main
