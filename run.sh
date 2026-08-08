#!/bin/bash
# Launcher script for NFC URL Writer
# Sets up environment variables for zbar library on macOS

cd "$(dirname "$0")"

# Activate virtual environment
source venv/bin/activate

# Set library path for zbar on macOS (Homebrew)
if [[ "$OSTYPE" == "darwin"* ]]; then
    export DYLD_LIBRARY_PATH="/opt/homebrew/lib:${DYLD_LIBRARY_PATH:-}"
    
    # Check if PC/SC is running (required for nfctagger)
    if ! ps aux | grep -q "[p]cscd"; then
        echo "⚠ WARNING: PC/SC daemon is not running"
        echo "   nfctagger requires PC/SC to be running for ACR122U access"
        echo "   To start PC/SC, run:"
        echo "   sudo launchctl load /System/Library/LaunchDaemons/com.apple.pcscd.plist"
        echo ""
        read -p "Continue anyway? (y/N) " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            exit 1
        fi
    fi
fi

# Run the application
python -m nfc_url_writer.main "$@"

