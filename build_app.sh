#!/bin/bash
# Build a self-contained, double-clickable app with PyInstaller.
#
# Usage: ./build_app.sh
# Output: dist/NFC URL Writer.app (macOS) or dist/NFC URL Writer/ (Windows/Linux)

set -euo pipefail
cd "$(dirname "$0")"

if [ ! -d "venv" ]; then
    echo "Error: virtual environment not found. Create it first:"
    echo "  python3 -m venv venv && source venv/bin/activate && pip install -r requirements.txt"
    exit 1
fi

source venv/bin/activate

if ! python -m PyInstaller --version >/dev/null 2>&1; then
    echo "Installing PyInstaller..."
    pip install pyinstaller
fi

echo "Building NFC URL Writer..."
python -m PyInstaller --noconfirm nfc_url_writer.spec

echo ""
if [[ "$OSTYPE" == "darwin"* ]]; then
    echo "Done: dist/NFC URL Writer.app"
    echo "Drag it to /Applications and double-click to run."
    echo "Note: the first launch may require right-click > Open (Gatekeeper)."
else
    echo "Done: see the dist/ folder."
fi
