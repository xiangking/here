#!/bin/bash
set -e

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

echo "Installing dependencies..."
echo ""

uv sync --python 3.11

echo ""
echo "========================================"
echo "  Installation complete!"
echo "========================================"
echo ""
echo "You can now run scripts/start.sh to launch the application"
