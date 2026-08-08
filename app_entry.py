"""PyInstaller entry point for NFC URL Writer.

The package's main module uses relative imports, so the frozen app needs
a top-level script that imports it as a package.
"""

from nfc_url_writer.main import main

if __name__ == "__main__":
    main()
