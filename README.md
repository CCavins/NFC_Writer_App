# NFC URL Writer

A cross-platform desktop application for writing URLs to NFC tags using an ACR122U NFC reader. The app supports manual URL entry, QR code scanning, and writes NDEF URI records to compatible NFC tags including NTAG213/215/216 and MIFARE Ultralight.

## Features

### Core Functionality
- **Manual URL Entry**: Type or paste URLs with automatic validation and HTTPS prefixing
- **QR Code Scanning**: Scan QR codes from your webcam to populate the URL field
- **NFC Tag Writing**: Write URLs to NTAG213, NTAG215, NTAG216, MIFARE Ultralight, and MIFARE Classic tags
- **Tag Detection**: Real-time detection and identification of NFC tags with automatic reading
- **Tag Reading**: Read URLs/text from tags and display them in the GUI
- **Write Verification**: Automatically verifies that data was written correctly after each write operation
- **Batch Queue Mode**: Import and write multiple URLs sequentially to different tags
- **Recent URLs**: Dropdown menu to quickly select from recently written URLs (up to 20)
- **Retry Previous URL**: Quickly reuse the last written URL
- **Open in Browser**: Button to open read URLs directly in your default browser
- **Cross-Platform**: Runs on macOS and Windows

### Automation Features
- **Auto-read on Detection**: Automatically read tag content when a tag is placed on the reader (configurable)
- **Auto-read after Write**: Automatically re-read tag after successful write to verify (configurable)
- **Auto-start Camera**: Automatically start camera when app opens (configurable)
- **Auto-add HTTPS**: Automatically prepend `https://` to URLs without protocol (configurable)
- **Clear URL after Write**: Automatically clear URL input field after successful write (configurable)

### User Interface Features
- **Dark/Light Theme**: System-aware theme with manual override option
- **Real-time Status Updates**: Visual feedback during write operations with step-by-step progress
- **Tag Information Display**: Shows tag type, UID, capacity, and writable status
- **Camera Preview**: Live preview of webcam feed for QR code scanning
- **Progress Indicators**: Visual progress bar during write operations
- **System Notifications**: Optional system notifications for write success/failure
- **Menu Bar**: File menu (Import/Export URLs, Exit), Settings menu (Preferences), Help menu (About)

## Requirements

### Hardware
- ACR122U NFC reader/writer
- Compatible NFC tags: NTAG213, NTAG215, NTAG216, MIFARE Ultralight, or MIFARE Classic (NTAG215 recommended)

### Software Dependencies
- **macOS**: 
  - PC/SC framework (usually pre-installed)
  - ACR122U driver from ACS
- **Windows**:
  - PC/SC service (usually pre-installed)
  - ACR122U driver from ACS

### Python Requirements
- Python 3.10 or newer
- All Python dependencies are listed in `requirements.txt`

## Setup for Development

### 1. Create a Virtual Environment

```bash
# Create virtual environment
python3 -m venv venv

# Activate virtual environment
# On macOS/Linux:
source venv/bin/activate
# On Windows:
venv\Scripts\activate
```

### 2. Install Dependencies

```bash
pip install -r requirements.txt
```

**Note on dependencies:**
- **PyQt6**: GUI framework
- **nfctagger**: NFC communication library for NTAG tags (works with PC/SC running)
- **pyscard**: PC/SC library for MIFARE Ultralight and other tag support
- **opencv-python**: Camera capture for QR scanning
- **pyzbar**: QR code decoding (requires zbar library on system)

#### Additional System Dependencies

**macOS:**
```bash
# Install zbar for QR code scanning
brew install zbar
```

**Windows:**
- Download and install zbar from: https://github.com/mchehab/zbar/releases
- Or use pre-built wheels if available

**Linux (for reference):**
```bash
sudo apt-get install libzbar0  # Debian/Ubuntu
# or
sudo yum install zbar  # RHEL/CentOS
```

### 3. Verify NFC Reader Connection

Before running the app, ensure your ACR122U is connected and recognized by the system:

**macOS:**
```bash
# Check if reader is detected
system_profiler SPUSBDataType | grep -i acr

# Verify PC/SC can see the reader (nfctagger requires PC/SC)
python -c "from smartcard.System import readers; print(readers())"
```

**Windows:**
- Check Device Manager for "ACS ACR122U PICC Interface"
- Ensure Smart Card service is running (services.msc)

## Running the Application

### Quick Launch (Recommended)

**Double-click `launch_app.command`** in Finder - this is the easiest way to launch the app!

### Other Options

**Option 1: Use the launcher script:**

```bash
./run.sh
```

**Option 2: Run directly:**

```bash
python -m nfc_url_writer.main
```

**Option 3: Create macOS App Bundle:**

```bash
./create_app_bundle.sh
```

This creates `NFC URL Writer.app` which you can:
- Double-click to launch
- Drag to Applications folder
- Launch from Spotlight (Cmd+Space)

**Note for macOS users:** If you get "Unable to find zbar shared library" errors, you need to set the library path:

```bash
export DYLD_LIBRARY_PATH=/opt/homebrew/lib:$DYLD_LIBRARY_PATH
python -m nfc_url_writer.main
```

The launcher scripts handle this automatically.

## Usage

1. **Start the Application**: Launch the app and wait for the NFC reader to be detected
2. **Enter URL**: 
   - Type or paste a URL in the "URL to write" field
   - Or click "Scan QR" to scan a QR code from your webcam
3. **Place Tag**: Place an NFC tag on the ACR122U reader
4. **Write**: Click "Write to tag" when a tag is detected and URL is valid
5. **Success**: The app will show a visual success indicator and clear the URL field

### URL Validation

- URLs are automatically validated
- If no scheme is provided, `https://` is automatically prepended (configurable)
- Invalid URLs are highlighted in red

### Tag Support

- **NTAG215** (recommended): 504 bytes capacity
- **NTAG213**: 132 bytes capacity
- **NTAG216**: 888 bytes capacity
- **MIFARE Ultralight**: 48 bytes capacity
- **MIFARE Classic 1K**: ~720 bytes capacity (requires default keys: 0xFFFFFFFFFFFF)

## GUI Structure and Design Guidelines

### Main Window Layout

The main window uses a **two-panel horizontal layout**:

#### Left Panel (Scrollable)
- **Width**: 500-600px (fixed width container)
- **Layout**: Vertical scrollable area containing multiple group boxes
- **Spacing**: 10px between group boxes

**Group Boxes (in order):**

1. **Content to Write Group** (`url_group`)
   - Record type selector (URL/Text)
   - URL input field with validation
   - Recent URLs dropdown
   - Clear history button
   - Write button (enabled when tag detected + valid URL)
   - Retry button (uses last written URL)

2. **Batch Queue Group** (`queue_group`)
   - Hidden by default, shown when Queue Mode is enabled
   - Queue Mode checkbox
   - Import Queue button
   - Clear Queue button
   - Reset Progress button
   - Queue list widget showing URLs and status

3. **Tag Status Group** (`status_group`)
   - Status panel with visual feedback (green on success, red on error)
   - Tag status label (shows detection status and operation progress)
   - Progress bar (indeterminate during operations)
   - Retry Reader button (secondary style)

#### Right Panel (Fixed)
- **Layout**: Vertical layout with group boxes
- **Spacing**: 10px between group boxes

**Group Boxes (in order):**

1. **Camera Group** (`camera_group`)
   - Camera selection dropdown
   - Camera preview label (320x240 minimum)
   - Start/Stop camera buttons

2. **Tag Information Group** (`tag_info_group`)
   - Tag UID display (monospace font)
   - Tag type display
   - Capacity display
   - Writable status display
   - Read URL label (shows URL from tag)
   - Open in Browser button (enabled when valid URL is read)

### Preferences/Settings Dialog Structure

The settings dialog uses a **scrollable vertical layout** with consistent spacing:

#### Layout Guidelines
- **Container**: QScrollArea with QVBoxLayout
- **Content spacing**: 12px between group boxes
- **Group box margins**: 16px (left/right), 12px (top/bottom) for content
- **Group box spacing**: 20px between items within group boxes (for checkboxes)
- **Checkbox height**: 32px (minimumHeight only, no maximumHeight for notifications; minimumHeight + maximumHeight for URL settings)

#### Group Boxes (in order):

1. **Camera Settings** (`camera_group`)
   - Auto-start camera checkbox
   - Layout spacing: 10px
   - Margins: 12px

2. **URL Settings** (`url_group`)
   - Default URL prefix: Label + ComboBox (horizontal layout, 16px spacing)
     - Label: 180px width, 36px height (fixed)
     - ComboBox: 250px minimum width, 36px height (fixed)
   - Checkboxes (all with 32px min/max height, 20px spacing):
     - Automatically add https:// to URLs without protocol
     - Clear URL field after successful write
     - Automatically read tag when detected
     - Automatically read tag after successful write
   - Layout spacing: 20px
   - Margins: 24px

3. **Notifications** (`notification_group`)
   - Checkboxes (32px minimumHeight only, 20px spacing):
     - Show system notification on successful write
     - Show notification when write verification fails
   - Layout spacing: 20px
   - Margins: 24px

4. **Logging** (`logging_group`)
   - Log level dropdown (DEBUG, INFO, WARNING, ERROR)
   - Layout spacing: 20px
   - Margins: 24px
   - Fixed width: 250-280px

5. **Theme** (`theme_group`)
   - Theme selector dropdown (Auto, Light, Dark)
   - Layout spacing: 20px
   - Margins: 24px

#### Design Consistency Rules

**For Adding New Settings:**

1. **Checkbox Settings**:
   - Use `minimumHeight: 32` and `maximumHeight: 32` for fixed-height checkboxes
   - Use 20px spacing between checkboxes in group box layouts
   - Use 24px margins for group box content
   - Match the Notifications section pattern for consistency

2. **Group Box Layouts**:
   - Always use QVBoxLayout for group box content
   - Use 20px spacing for checkbox groups
   - Use 24px margins (left, top, right, bottom) for content padding

3. **Form Controls**:
   - Labels: 180px width, 36px height (fixed) for form labels
   - ComboBoxes: 250px minimum width, 36px height (fixed)
   - Horizontal form layouts: 16px spacing between label and control

4. **Group Box Ordering**:
   - Camera Settings (first)
   - URL Settings
   - Notifications
   - Logging and Theme (bottom row, side by side)

## Configuration

The app stores configuration in:

- **macOS**: `~/Library/Application Support/NFCUrlWriter/config.json`
- **Windows**: `%APPDATA%\NFCUrlWriter\config.json`

### Available Settings

**URL Settings:**
- `url_prefix`: Default URL prefix (https://, http://, etc.)
- `auto_add_https`: Automatically add https:// to URLs without protocol
- `clear_url_after_write`: Clear URL field after successful write
- `auto_read_on_detect`: Automatically read tag when detected
- `auto_read_after_write`: Automatically read tag after successful write

**Camera Settings:**
- `auto_start_camera`: Auto-start camera when app opens
- `default_camera_index`: Preferred camera index
- `default_camera_name`: Preferred camera name

**Notifications:**
- `notify_on_success`: Show system notification on successful write
- `notify_on_verify`: Show notification when write verification fails

**Appearance:**
- `dark_mode`: Theme setting (None = auto-detect, True = dark, False = light)

**Logging:**
- `log_level`: Logging level (DEBUG, INFO, WARNING, ERROR)

**Data:**
- `last_written_url`: Last successfully written URL
- `recent_urls`: List of recent URLs (max 20)

## Building a Standalone App (PyInstaller)

The repository includes a ready-to-use PyInstaller spec (`nfc_url_writer.spec`) and build script. The result is a fully self-contained, double-clickable app — no Python, venv, or Homebrew paths required on the machine running it (the NFC reader driver and PC/SC are still needed).

### macOS

```bash
./build_app.sh
```

This produces `dist/NFC URL Writer.app`. Drag it to `/Applications` and double-click to run. The first launch may require right-click → Open (Gatekeeper), since the app is not notarized.

The spec handles the packaging details automatically:
- Bundles the zbar library for QR decoding (with a runtime hook so pyzbar can find it)
- Bundles the Qt Designer `.ui` files
- Adds `NSCameraUsageDescription` to Info.plist so macOS allows camera access
- Writes logs to `~/Library/Application Support/NFCUrlWriter/` instead of the working directory

### Windows

```bash
pip install pyinstaller
pyinstaller --noconfirm nfc_url_writer.spec
```

This produces a `dist/NFC URL Writer/` folder containing `NFC URL Writer.exe`. On Windows, make sure a zbar DLL is available (see the zbar installation notes above).

## NFC Driver Requirements

### macOS

1. Install ACS ACR122U driver from: https://www.acs.com.hk/en/driver/3/acr122u-usb-nfc-reader/
2. **PC/SC framework must be running** (nfctagger requires it):
   ```bash
   # Check PC/SC status
   ps aux | grep pcscd
   ```
3. If PC/SC is not running, start it:
   ```bash
   sudo launchctl load /System/Library/LaunchDaemons/com.apple.pcscd.plist
   ```
   **Note:** Unlike nfcpy, nfctagger works WITH PC/SC running - no need to stop it!

### Windows

1. Install ACS ACR122U driver from: https://www.acs.com.hk/en/driver/3/acr122u-usb-nfc-reader/
2. **Smart Card service must be running** (nfctagger requires it):
   - Open Services (services.msc)
   - Find "Smart Card" service
   - Set to Automatic and start if needed

## Troubleshooting

### Reader Not Found

**Important:** nfctagger works with PC/SC running (unlike nfcpy). The PC/SC service must be active.

1. **Ensure ACR122U is connected via USB**
2. **Verify PC/SC service is running** (required for nfctagger):
   ```bash
   # macOS
   ps aux | grep pcscd
   # If not running:
   sudo launchctl load /System/Library/LaunchDaemons/com.apple.pcscd.plist
   
   # Windows: Check Services (services.msc) for "Smart Card" service
   ```
3. **Test if PC/SC can see the reader:**
   ```bash
   python -c "from smartcard.System import readers; print(readers())"
   ```
   Should show: `['ACS ACR122U PICC Interface']`
4. **Try disconnecting and reconnecting the reader**
5. **Restart the application**

**Note:** nfctagger is specifically designed for ACR122U and works seamlessly with PC/SC. No need to stop PC/SC daemon!

### Tag Not Detected

- Ensure tag is placed directly on the reader
- Try a different tag
- Check if tag is NDEF-capable
- Some tags may need to be formatted first

### Write Failed

- Verify tag is NDEF-capable
- Check if URL is too long for tag capacity
- Ensure tag remains on reader during write
- Try formatting the tag first (app handles this automatically)

### QR Scanner Not Working

- Verify camera permissions are granted
- Check if camera is being used by another application
- Try selecting a different camera from the dropdown
- Ensure zbar library is installed

## Project Structure

```
NFC_URL_Writer_pyapp/
├── nfc_url_writer/
│   ├── __init__.py
│   ├── main.py                 # Application entry point
│   ├── config/
│   │   ├── __init__.py
│   │   └── settings.py          # Configuration management
│   ├── nfc/
│   │   ├── __init__.py
│   │   └── nfc_manager.py      # NFC reader and tag operations
│   ├── qr/
│   │   ├── __init__.py
│   │   └── qr_scanner.py       # QR code scanning
│   └── ui/
│       ├── __init__.py
│       ├── main_window.py      # Main application window
│       ├── main_window.ui      # Qt Designer UI file
│       ├── theme.py            # Central light/dark palettes and stylesheet
│       ├── settings_dialog.py  # Settings dialog
│       ├── settings_dialog.ui  # Qt Designer UI file
│       ├── qr_dialog.py        # QR scanning dialog
│       └── qr_dialog.ui        # Qt Designer UI file
├── app_entry.py                # PyInstaller entry point
├── nfc_url_writer.spec         # PyInstaller build spec
├── build_app.sh                # Standalone app build script
├── requirements.txt
├── pyproject.toml
└── README.md
```

## UI Development with Qt Designer

The application uses Qt Designer UI files (`.ui`) for easier maintenance and visual design. UI layouts are defined in XML files that can be edited visually using Qt Designer.

### Working with UI Files

**Editing UI Files:**
1. Install Qt Designer (usually comes with PyQt6 installation)
2. Open the `.ui` file in Qt Designer:
   ```bash
   designer-qt6 nfc_url_writer/ui/main_window.ui
   ```
3. Make layout changes visually
4. Save the file - changes will be automatically loaded by the application

**How It Works:**
- UI files (`.ui`) define the widget structure and layout
- Python code loads UI files using `uic.loadUi()` from PyQt6
- Business logic, signals, and styling are handled in Python code
- This separation makes it easier to modify layouts without touching Python code

**Files:**
- `main_window.ui` - Main application window layout
- `settings_dialog.ui` - Settings dialog layout
- `qr_dialog.ui` - QR code scanner dialog layout

**Note:** After modifying `.ui` files, restart the application to see changes. The Python code automatically loads the UI files at runtime.

## License

MIT License

## Contributing

Contributions are welcome! Please ensure code follows PEP 8 style guidelines and includes appropriate type hints.

## Acknowledgments

- nfctagger library for ACR122U NFC communication
- PyQt6 for the GUI framework
- OpenCV and pyzbar for QR code scanning

