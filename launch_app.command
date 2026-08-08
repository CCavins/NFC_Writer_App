#!/bin/bash
# Double-clickable launcher for NFC URL Writer
# This file can be double-clicked in Finder to launch the app

# Get the directory where this script is located
cd "$(dirname "$0")"

# Activate virtual environment
if [ ! -d "venv" ]; then
    osascript -e 'display dialog "Virtual environment not found. Please run setup first." buttons {"OK"} default button "OK" with icon stop'
    exit 1
fi

source venv/bin/activate

# Set library path for zbar on macOS (Homebrew)
if [[ "$OSTYPE" == "darwin"* ]]; then
    export DYLD_LIBRARY_PATH="/opt/homebrew/lib:${DYLD_LIBRARY_PATH:-}"
    
    # Check if PC/SC is running (required for nfctagger)
    # Just warn, don't try to start it automatically (requires password)
    if ! ps aux | grep -q "[p]cscd"; then
        echo "⚠ WARNING: PC/SC daemon is not running"
        echo "   nfctagger requires PC/SC to be running for ACR122U access"
        echo "   The app may still work, but reader detection might fail"
        echo ""
    fi
fi

# Run the launcher (which will handle web/desktop choice)
python launcher.py "$@"

# Keep terminal open if there was an error
if [ $? -ne 0 ]; then
    echo ""
    echo "Press Enter to close..."
    read
fi
