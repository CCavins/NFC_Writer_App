#!/usr/bin/env python3
"""Launcher script for NFC URL Writer desktop application."""

import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

def main():
    """Main entry point - launch desktop PyQt application."""
    try:
        from nfc_url_writer.main import main as app_main
        app_main()
    except Exception as e:
        print(f"Error launching application: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()
