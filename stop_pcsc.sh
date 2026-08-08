#!/bin/bash
# DEPRECATED: This script is no longer needed
# nfctagger works WITH PC/SC running (unlike nfcpy which required stopping PC/SC)

echo "⚠ DEPRECATED: This script is no longer needed!"
echo ""
echo "The application now uses nfctagger instead of nfcpy."
echo "nfctagger works WITH PC/SC running - no need to stop it."
echo ""
echo "If PC/SC is not running and you need to start it:"
echo "  sudo launchctl load /System/Library/LaunchDaemons/com.apple.pcscd.plist"
echo ""
echo "If you really need to stop PC/SC for some other reason:"
echo "  sudo launchctl unload -w /System/Library/LaunchDaemons/com.apple.pcscd.plist"
echo ""
echo "But this is NOT required for the NFC URL Writer application."

