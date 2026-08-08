# Quick Launch Options

## Option 1: Standalone Compiled App (Recommended)

Build once with PyInstaller, then use it like any other Mac app:

```bash
./build_app.sh
```

This creates `dist/NFC URL Writer.app` which you can:
- Double-click to launch
- Drag to the Applications folder
- Add to the Dock
- Launch from Spotlight (Cmd+Space) or Launchpad

It is fully self-contained - no Python, venv, or Homebrew needed on the
machine that runs it. The first launch may require right-click > Open
(Gatekeeper), since the app is not notarized.

## Option 2: Double-Click Launcher (Development)

**`launch_app.command`** - Double-click this file in Finder to run the app
from the project's virtual environment.

1. In Finder, navigate to the project folder
2. Double-click `launch_app.command`
3. The app will launch automatically

**Note:** The first time you run it, macOS may ask for permission. Right-click and select "Open" if needed.

## Option 3: Terminal

```bash
./run.sh
```

Or add an alias to your `~/.zshrc`:

```bash
alias nfc-writer="cd /Users/christophercavins/GitHub/NFC_URL_Writer_pyapp && ./run.sh"
```

Then just type `nfc-writer` in Terminal.
