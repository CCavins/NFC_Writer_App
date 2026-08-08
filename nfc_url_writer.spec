# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for NFC URL Writer.

Build with:  pyinstaller --noconfirm nfc_url_writer.spec
Produces a self-contained app in dist/ (macOS: "NFC URL Writer.app").
"""

import os
import sys

APP_NAME = "NFC URL Writer"
IS_MACOS = sys.platform == "darwin"

# Bundle the zbar shared library (pyzbar loads it via ctypes at runtime).
binaries = []
_zbar_candidates = [
    "/opt/homebrew/lib/libzbar.dylib",       # macOS arm64 (Homebrew)
    "/usr/local/lib/libzbar.dylib",          # macOS x86_64 (Homebrew)
]
for _cand in _zbar_candidates:
    if os.path.exists(_cand):
        binaries.append((_cand, "."))
        break

a = Analysis(
    ["app_entry.py"],
    pathex=[],
    binaries=binaries,
    datas=[
        # Qt Designer layouts loaded at runtime via uic.loadUi()
        ("nfc_url_writer/ui/*.ui", "nfc_url_writer/ui"),
    ],
    hiddenimports=[
        "nfctagger",
        "nfctagger.devices.pcsc",
        "nfctagger.devices.ntag",
        "nfctagger.ndef",
        "pyzbar.pyzbar",
        "smartcard",
        "smartcard.System",
        "smartcard.scard",
        "smartcard.pcsc",
        "cv2",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=["pyi_rth_zbar.py"],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=APP_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name=APP_NAME,
)

if IS_MACOS:
    app = BUNDLE(
        coll,
        name=f"{APP_NAME}.app",
        icon=None,
        bundle_identifier="com.nfcurlwriter.app",
        info_plist={
            "CFBundleName": APP_NAME,
            "CFBundleDisplayName": APP_NAME,
            "CFBundleShortVersionString": "1.0.0",
            "CFBundleVersion": "1.0.0",
            "NSHighResolutionCapable": True,
            "LSMinimumSystemVersion": "11.0",
            # Required for QR scanning; without it macOS kills the app
            # the moment it tries to open the camera.
            "NSCameraUsageDescription": (
                "NFC URL Writer uses the camera to scan QR codes."
            ),
        },
    )
