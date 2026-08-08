#!/bin/bash
# Script to create a macOS app bundle for NFC URL Writer
# This creates a double-clickable .app that can be placed in Applications

APP_NAME="NFC URL Writer"
APP_DIR="${APP_NAME}.app"
CONTENTS_DIR="${APP_DIR}/Contents"
MACOS_DIR="${CONTENTS_DIR}/MacOS"
RESOURCES_DIR="${CONTENTS_DIR}/Resources"

# Get the directory where this script is located
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

echo "Creating macOS app bundle: ${APP_NAME}.app"

# Create directory structure
rm -rf "${APP_DIR}"
mkdir -p "${MACOS_DIR}"
mkdir -p "${RESOURCES_DIR}"

# Create Info.plist
cat > "${CONTENTS_DIR}/Info.plist" << 'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleExecutable</key>
    <string>nfc_url_writer</string>
    <key>CFBundleIdentifier</key>
    <string>com.nfcurlwriter.app</string>
    <key>CFBundleName</key>
    <string>NFC URL Writer</string>
    <key>CFBundleVersion</key>
    <string>1.0</string>
    <key>CFBundleShortVersionString</key>
    <string>1.0</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>CFBundleSignature</key>
    <string>NFCW</string>
    <key>LSMinimumSystemVersion</key>
    <string>10.13</string>
    <key>NSHighResolutionCapable</key>
    <true/>
</dict>
</plist>
EOF

# Create launcher script
cat > "${MACOS_DIR}/nfc_url_writer" << LAUNCHER_EOF
#!/bin/bash
# Launcher script for NFC URL Writer app bundle

# Get the app bundle directory
APP_DIR="$(cd "\$(dirname "\$0")/../.." && pwd)"

# The app bundle should be in the project root
# So the project directory is the parent of the .app
PROJECT_DIR="\$(dirname "\${APP_DIR}")"

# If that doesn't work, try the directory containing the app
if [ ! -d "\${PROJECT_DIR}/venv" ]; then
    PROJECT_DIR="\$(dirname "\$(dirname "\${APP_DIR}")")"
fi

cd "\${PROJECT_DIR}"
LAUNCHER_EOF

# Activate virtual environment
if [ ! -d "venv" ]; then
    osascript -e 'display dialog "Virtual environment not found. Please ensure the app is in the correct location." buttons {"OK"} default button "OK" with icon stop'
    exit 1
fi

source venv/bin/activate

# Set library path for zbar on macOS (Homebrew)
export DYLD_LIBRARY_PATH="/opt/homebrew/lib:\${DYLD_LIBRARY_PATH:-}"

# Check if PC/SC is running (required for nfctagger)
if ! ps aux | grep -q "[p]cscd"; then
    osascript -e 'display dialog "PC/SC daemon is not running. nfctagger requires PC/SC to be running. Start it?" buttons {"Cancel", "Start PC/SC"} default button "Start PC/SC" with icon caution' > /dev/null 2>&1
    if [ \$? -eq 0 ]; then
        sudo launchctl load /System/Library/LaunchDaemons/com.apple.pcscd.plist 2>/dev/null
    fi
fi

# Run the application
python -m nfc_url_writer.main "\$@"
LAUNCHER_EOF

chmod +x "${MACOS_DIR}/nfc_url_writer"

echo "✓ App bundle created: ${APP_DIR}"
echo ""
echo "To use:"
echo "  1. Double-click '${APP_NAME}.app' in Finder"
echo "  2. Or drag it to your Applications folder"
echo ""
echo "Note: You may need to right-click and select 'Open' the first time"
echo "      (macOS Gatekeeper may block it initially)"

