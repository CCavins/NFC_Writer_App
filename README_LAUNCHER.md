# Quick Launch Options

## Option 1: Double-Click Launcher (Easiest)

**`launch_app.command`** - Double-click this file in Finder to launch the app.

1. In Finder, navigate to the project folder
2. Double-click `launch_app.command`
3. The app will launch automatically

**Note:** The first time you run it, macOS may ask for permission. Right-click and select "Open" if needed.

## Option 2: macOS App Bundle

Create a proper macOS app bundle that can be placed in Applications:

```bash
./create_app_bundle.sh
```

This creates `NFC URL Writer.app` which you can:
- Double-click to launch
- Drag to Applications folder
- Add to Dock

## Option 3: Terminal Alias

Add this to your `~/.zshrc` or `~/.bash_profile`:

```bash
alias nfc-writer="cd /Users/christophercavins/GitHub/NFC_URL_Writer_pyapp && ./run.sh"
```

Then just type `nfc-writer` in Terminal.

## Option 4: Spotlight/Launchpad

After creating the app bundle (Option 2), you can:
- Press Cmd+Space and type "NFC URL Writer"
- Or find it in Launchpad

## Recommended: Option 1 (launch_app.command)

The simplest option is to double-click `launch_app.command` - it works immediately without any setup!

