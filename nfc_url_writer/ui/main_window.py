"""Main application window."""

import logging
import urllib.parse
import webbrowser
from pathlib import Path
from typing import Optional
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QStatusBar, QMessageBox, QGroupBox, QComboBox,
    QMenuBar, QFileDialog, QListWidget, QListWidgetItem, QCheckBox, QProgressBar,
    QScrollArea, QSizePolicy, QApplication, QSystemTrayIcon
)
from PyQt6.QtCore import Qt, QTimer, pyqtSlot, pyqtSignal, QThread, QRect
from PyQt6.QtGui import (
    QColor, QPalette, QImage, QPixmap, QFontDatabase, QIcon, QPainter,
    QShortcut, QKeySequence
)
from PyQt6 import uic
import sys

from ..config.settings import Settings
from ..nfc.nfc_manager import NFCManager
from ..qr.qr_scanner import QRScanner, QRScannerWorker
from . import theme
from .settings_dialog import SettingsDialog


class MainWindow(QMainWindow):
    """Main application window."""
    
    def __init__(self):
        """Initialize main window."""
        super().__init__()
        self.setWindowTitle("NFC URL Writer")
        self.setMinimumSize(1000, 680)
        self.resize(1400, 900)
        
        # Initialize components
        self.settings = Settings()
        self.nfc_manager = NFCManager()
        
        # Setup logging
        self.logger = logging.getLogger(__name__)
        
        # UI state
        self.current_url = ""
        self.url_valid = False
        self.tag_detected = False
        self.tag_type = ""
        self.tag_capacity: Optional[int] = None
        
        # QR Scanner worker
        self.qr_scanner_worker: Optional[QRScannerWorker] = None
        
        # System tray icon for notifications (created lazily)
        self._tray: Optional[QSystemTrayIcon] = None
        
        # Theme state: tracked label styles so they can be re-applied
        # when the theme changes (text, role, bold, italic per label)
        self._label_states = {}
        self._dark = theme.resolve_dark_mode(self.settings.dark_mode, self)
        self.colors = theme.colors(self._dark)
        
        # Setup UI first (loads from .ui file)
        self._setup_ui()
        
        # Setup menu after UI is loaded (menu bar is created programmatically)
        self._setup_menu()
        
        # Connect signals and apply theme
        self._connect_signals()
        self._apply_theme()
        
        # Delay NFC reader connection to allow PC/SC stack to initialize
        # This prevents the need to manually retry on app launch
        from PyQt6.QtCore import QTimer
        self.init_timer = QTimer()
        self.init_timer.setSingleShot(True)
        self.init_timer.timeout.connect(self._delayed_nfc_init)
        self.init_timer.start(1500)  # Wait 1.5 seconds after UI is ready
        
        # Success animation timer
        self.success_timer = QTimer()
        self.success_timer.setSingleShot(True)
        self.success_timer.timeout.connect(self._reset_success_indicator)
    
    def _setup_menu(self) -> None:
        """Setup menu bar."""
        try:
            menubar = self.menuBar()
            
            # Clear any existing menus to avoid conflicts
            menubar.clear()
            
            # File menu
            file_menu = menubar.addMenu("File")
            
            import_action = file_menu.addAction("Import URLs...")
            import_action.setShortcut("Ctrl+O")
            import_action.triggered.connect(self._on_import_urls)
            # Explicitly disable icon to prevent macOS from trying to auto-generate one
            import_action.setIconVisibleInMenu(False)
            
            export_action = file_menu.addAction("Export URLs...")
            export_action.setShortcut("Ctrl+E")
            export_action.triggered.connect(self._on_export_urls)
            export_action.setIconVisibleInMenu(False)
            
            file_menu.addSeparator()
            
            exit_action = file_menu.addAction("Exit")
            exit_action.triggered.connect(self.close)
            exit_action.setIconVisibleInMenu(False)
            
            # Settings menu
            settings_menu = menubar.addMenu("Settings")
            
            preferences_action = settings_menu.addAction("Preferences...")
            preferences_action.setShortcut("Ctrl+,")  # Standard shortcut for preferences
            preferences_action.triggered.connect(self._on_preferences)
            preferences_action.setIconVisibleInMenu(False)
            
            # Help menu
            help_menu = menubar.addMenu("Help")
            
            about_action = help_menu.addAction("About")
            about_action.triggered.connect(self._on_about)
            about_action.setIconVisibleInMenu(False)
        except Exception as e:
            # If menu setup fails, log but don't crash
            self.logger.error(f"Error setting up menu bar: {e}", exc_info=True)
    
    def _setup_ui(self) -> None:
        """Setup the user interface."""
        # Load UI from .ui file
        ui_file = Path(__file__).parent / "main_window.ui"
        uic.loadUi(ui_file, self)
        
        # Set up combo box items
        self.record_type_combo.addItems(["URL", "Text"])
        self.record_type_combo.setFixedWidth(100)
        
        # Set up recent URLs combo
        self.recent_urls_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        
        # Set up progress bar
        self.write_progress.setRange(0, 0)  # Indeterminate progress
        
        # Low-emphasis style for the retry reader button (styled via theme QSS)
        self.retry_reader_button.setProperty("class", "subtle")
        
        # Set up camera preview label styling and size policy
        self.camera_preview_label.setProperty("class", "camera-preview")
        # Allow camera preview to shrink when window is resized, but maintain aspect ratio
        self.camera_preview_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.camera_preview_label.setScaledContents(False)  # We'll handle scaling manually to maintain aspect ratio
        self.camera_preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        # Monospace font for the tag UID
        fixed_font = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        fixed_font.setPointSize(11)
        self.tag_uid_label.setFont(fixed_font)
        
        # Set up read URL label
        self._set_label(self.read_url_label, "", role="muted", italic=True)
        self.read_url_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.read_url_label.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        
        # Store the current read URL
        self.current_read_url: Optional[str] = None
        
        # Connect signals
        self.record_type_combo.currentTextChanged.connect(self._on_record_type_changed)
        self.url_input.textChanged.connect(self._on_url_changed)
        self.url_input.returnPressed.connect(self._on_write_clicked)
        self.recent_urls_combo.currentTextChanged.connect(self._on_recent_url_selected)
        self.clear_history_button.clicked.connect(self._on_clear_history_clicked)
        self.write_button.clicked.connect(self._on_write_clicked)
        self.retry_button.clicked.connect(self._on_retry_clicked)
        self.retry_reader_button.clicked.connect(self._on_retry_reader_clicked)
        self.camera_combo.currentIndexChanged.connect(self._on_camera_changed)
        self.start_camera_button.clicked.connect(self._start_camera)
        self.stop_camera_button.clicked.connect(self._stop_camera)
        self.read_tag_button.clicked.connect(self._on_read_tag_clicked)
        self.open_url_button.clicked.connect(self._on_open_url_clicked)
        self.copy_url_button.clicked.connect(self._on_copy_url_clicked)
        self.queue_mode_check.toggled.connect(self._on_queue_mode_toggled)
        self.import_queue_button.clicked.connect(self._on_import_queue_clicked)
        self.clear_queue_button.clicked.connect(self._on_clear_queue_clicked)
        self.reset_progress_button.clicked.connect(self._on_reset_progress_clicked)
        
        # Keyboard shortcuts and tooltips
        self.read_tag_button.setShortcut("Ctrl+R")
        self.read_tag_button.setToolTip("Read the URL/text from the tag on the reader (Cmd+R / Ctrl+R)")
        self.write_button.setToolTip("Write the content to the detected tag (Enter in the URL field)")
        self.retry_button.setToolTip("Load the last successfully written URL back into the field")
        self.copy_url_button.setToolTip("Copy the URL read from the tag to the clipboard")
        self.open_url_button.setToolTip("Open the URL read from the tag in your default browser")
        focus_url_shortcut = QShortcut(QKeySequence("Ctrl+L"), self)
        focus_url_shortcut.activated.connect(
            lambda: (self.url_input.setFocus(), self.url_input.selectAll())
        )
        
        # Set initial button states
        self.write_button.setEnabled(False)
        self.retry_button.setEnabled(self.settings.last_written_url is not None)
        
        # Populate recent URLs
        self._update_recent_urls_combo()
        
        # Populate camera list
        self._populate_cameras()
        
        # Auto-start camera if setting is enabled
        if self.settings.auto_start_camera:
            QTimer.singleShot(500, self._auto_start_camera)
        
        # Status bar
        self.status_bar.showMessage("Ready")
    
    def _connect_signals(self) -> None:
        """Connect NFC manager signals to UI slots."""
        self.nfc_manager.reader_status_changed.connect(self._on_reader_status_changed)
        self.nfc_manager.tag_detected.connect(self._on_tag_detected)
        self.nfc_manager.tag_removed.connect(self._on_tag_removed)
        self.nfc_manager.write_success.connect(self._on_write_success)
        self.nfc_manager.write_failed.connect(self._on_write_failed)
        self.nfc_manager.write_verified.connect(self._on_write_verified)
        self.nfc_manager.operation_status.connect(self._on_operation_status)
        self.nfc_manager.tag_read.connect(self._on_tag_read)
    
    def _set_label(self, label, text: str, role: str = "text",
                   bold: bool = False, italic: bool = False) -> None:
        """Set label text with a theme-aware semantic color role.
        
        Tracks the state so colors can be re-applied when the theme changes.
        Roles: text, muted, success, error, warning, info.
        """
        self._label_states[label] = (text, role, bold, italic)
        label.setText(text)
        self._style_label(label, role, bold, italic)
    
    def _style_label(self, label, role: str, bold: bool, italic: bool) -> None:
        """Apply the current theme color for a semantic role to a label."""
        parts = [f"color: {self.colors[role]};"]
        if bold:
            parts.append("font-weight: bold;")
        if italic:
            parts.append("font-style: italic;")
        label.setStyleSheet(" ".join(parts))
    
    def _notify(self, title: str, message: str) -> None:
        """Show a system notification (best effort)."""
        try:
            if not QSystemTrayIcon.isSystemTrayAvailable():
                return
            if self._tray is None:
                # Tray icon is required to post notifications; draw a simple one
                pixmap = QPixmap(64, 64)
                pixmap.fill(Qt.GlobalColor.transparent)
                painter = QPainter(pixmap)
                painter.setRenderHint(QPainter.RenderHint.Antialiasing)
                painter.setBrush(QColor(self.colors["accent"]))
                painter.setPen(Qt.PenStyle.NoPen)
                painter.drawEllipse(4, 4, 56, 56)
                painter.setPen(QColor("white"))
                font = painter.font()
                font.setPointSize(28)
                font.setBold(True)
                painter.setFont(font)
                painter.drawText(QRect(0, 0, 64, 64), Qt.AlignmentFlag.AlignCenter, "N")
                painter.end()
                self._tray = QSystemTrayIcon(QIcon(pixmap), self)
                self._tray.show()
            self._tray.showMessage(
                title, message, QSystemTrayIcon.MessageIcon.Information, 4000
            )
        except Exception as e:
            self.logger.debug(f"Could not show system notification: {e}")
    
    @pyqtSlot()
    def _on_copy_url_clicked(self) -> None:
        """Handle Copy button click - copy read URL to clipboard."""
        if self.current_read_url:
            QApplication.clipboard().setText(self.current_read_url)
            self.status_bar.showMessage("URL copied to clipboard", 3000)
    
    def _delayed_nfc_init(self) -> None:
        """Initialize NFC reader connection after a delay (non-blocking)."""
        self.logger.info("Initializing NFC reader connection...")
        self._set_label(self.reader_status_label, "Reader status: Connecting...", role="muted")
        
        # Connect reader in a background thread to avoid blocking UI
        class InitConnectionThread(QThread):
            finished = pyqtSignal(bool)
            
            def __init__(self, nfc_manager):
                super().__init__()
                self.nfc_manager = nfc_manager
            
            def run(self):
                result = self.nfc_manager.connect_reader()
                self.finished.emit(result)
        
        self.init_connection_thread = InitConnectionThread(self.nfc_manager)
        self.init_connection_thread.finished.connect(self._on_init_connection_finished)
        self.init_connection_thread.start()
    
    def _on_init_connection_finished(self, success: bool) -> None:
        """Handle completion of initial NFC reader connection."""
        if success:
            # Start polling once reader is connected
            self.nfc_manager.start_polling()
        else:
            # If initial connection fails, still start polling
            # (it might connect later when reader becomes available)
            self.nfc_manager.start_polling()
    
    def _normalize_url(self, url: str) -> str:
        """Normalize URL: trim whitespace, handle LinkedIn usernames, and add https:// if needed."""
        url = url.strip()
        if not url:
            return ""
        
        # Check if it looks like a LinkedIn username
        # LinkedIn usernames are typically alphanumeric with hyphens/underscores, no spaces, no slashes
        import re
        linkedin_username_pattern = r'^[a-zA-Z0-9_-]+$'
        if re.match(linkedin_username_pattern, url) and len(url) > 1:
            # Convert to LinkedIn URL
            url = f"https://www.linkedin.com/in/{url}/"
            self.logger.debug(f"Detected LinkedIn username, converted to: {url}")
            return url
        
        # Check if URL has a scheme
        parsed = urllib.parse.urlparse(url)
        if not parsed.scheme:
            if self.settings.auto_add_https:
                url = "https://" + url
            else:
                # Still try to validate, but don't auto-add
                pass
        
        return url
    
    def _validate_url(self, url: str) -> bool:
        """Validate URL format."""
        if not url:
            return False
        
        try:
            result = urllib.parse.urlparse(url)
            # Check that we have at least a scheme and netloc (domain)
            if result.scheme and result.netloc:
                return True
            # Also accept URLs with just scheme and path (like file://)
            if result.scheme and result.path:
                return True
            return False
        except Exception:
            return False
    
    def _on_record_type_changed(self, record_type: str) -> None:
        """Handle record type change."""
        if record_type == "Text":
            self.url_input.setPlaceholderText("Enter text to write")
            self._set_label(self.validation_label, "Text mode - any text is valid", role="info")
        else:
            self.url_input.setPlaceholderText("Enter URL or scan QR code")
            # Re-validate current input
            self._on_url_changed(self.url_input.text())
    
    def _update_write_button_state(self) -> None:
        """Update write button enabled state based on current conditions."""
        if self.queue_mode_check.isChecked():
            # Queue mode - enable if tag detected and queue has URLs
            current_url = self.nfc_manager.get_current_queue_url()
            self.write_button.setEnabled(self.tag_detected and current_url is not None)
        else:
            # Normal mode
            record_type = self.record_type_combo.currentText()
            clear_after_write = self.settings.clear_url_after_write
            
            if record_type == "Text":
                # Text mode - enable if tag detected and text is not empty
                has_text = bool(self.current_url and self.current_url.strip())
                self.write_button.setEnabled(self.tag_detected and has_text)
            else:
                # URL mode
                if clear_after_write:
                    # Original behavior: require valid URL
                    self.write_button.setEnabled(self.url_valid and self.tag_detected)
                else:
                    # New behavior: enable if tag is detected and URL is valid
                    # (still need valid URL to write, but don't clear after)
                    self.write_button.setEnabled(self.url_valid and self.tag_detected)
    
    def _on_url_changed(self, text: str) -> None:
        """Handle URL input text change."""
        self.current_url = text
        record_type = self.record_type_combo.currentText()
        
        # Check if write_button exists (may be called during initialization)
        if not hasattr(self, 'write_button'):
            return
        
        if record_type == "Text":
            # Text mode - any non-empty text is valid
            if not text:
                self._set_label(self.validation_label, "")
            else:
                message = f"Text ({len(text)} characters)"
                size = len(text.encode('utf-8'))
                role = "info"
                if self.tag_capacity and size + 7 > self.tag_capacity:
                    message += f" - may not fit on this tag ({self.tag_capacity}-byte capacity)"
                    role = "warning"
                self._set_label(self.validation_label, message, role=role)
        else:
            # URL mode - validate URL
            normalized = self._normalize_url(text)
            self.url_valid = self._validate_url(normalized)
            
            if not text:
                self._set_label(self.validation_label, "")
            elif self.url_valid:
                # Check if it was converted from a LinkedIn username
                import re
                linkedin_username_pattern = r'^[a-zA-Z0-9_-]+$'
                is_linkedin_username = bool(re.match(linkedin_username_pattern, text.strip()) and len(text.strip()) > 1)
                
                if is_linkedin_username:
                    message = f"LinkedIn profile: {normalized}"
                else:
                    message = "Valid URL"
                
                # Show size and warn if it may exceed the detected tag's capacity
                # (+7 bytes approximates the NDEF record/TLV overhead)
                size = len(normalized.encode('utf-8'))
                message += f" \u00b7 {size} bytes"
                role = "success"
                if self.tag_capacity and size + 7 > self.tag_capacity:
                    message += f" - may not fit on this tag ({self.tag_capacity}-byte capacity)"
                    role = "warning"
                self._set_label(self.validation_label, message, role=role)
            else:
                self._set_label(self.validation_label, "Invalid URL", role="error")
        
        # Update write button state
        self._update_write_button_state()
    
    def _on_write_clicked(self) -> None:
        """Handle Write to tag button click."""
        # Check if in queue mode
        if self.queue_mode_check.isChecked():
            # Queue mode - check if queue has URLs
            current_url = self.nfc_manager.get_current_queue_url()
            if current_url is None:
                QMessageBox.warning(self, "Queue Empty", "No URLs in queue or queue is complete. Import a queue first.")
                return
        else:
            # Normal mode - validate URL
            if not self.url_valid:
                QMessageBox.warning(self, "Invalid URL", "Please enter a valid URL first.")
                return
        
        if not self.tag_detected:
            QMessageBox.warning(self, "No Tag", "Please place an NFC tag on the reader.")
            return
        
        # Get record type
        record_type = self.record_type_combo.currentText()
        
        # Check if in queue mode
        if self.queue_mode_check.isChecked():
            # In queue mode, write current queue URL (no need to normalize, it's from queue)
            self.write_button.setEnabled(False)
            current_url = self.nfc_manager.get_current_queue_url()
            url_preview = current_url[:50] + "..." if current_url and len(current_url) > 50 else current_url
            self.status_bar.showMessage(f"Starting write operation: {url_preview}", 0)
            self.write_progress.setVisible(True)
            self.write_progress.setRange(0, 0)  # Indeterminate
            # Set initial status
            self._set_label(self.tag_status_label, "Tag status: Preparing write operation...", role="info", bold=True)
            self.nfc_manager.write_url(record_type=record_type)  # No URL parameter - uses queue
        else:
            # Normal mode - use entered content
            if record_type == "Text":
                content = self.current_url
            else:
                content = self._normalize_url(self.current_url)
            
            # Disable write button during operation
            self.write_button.setEnabled(False)
            content_preview = content[:50] + "..." if len(content) > 50 else content
            self.status_bar.showMessage(f"Starting write operation: {content_preview}", 0)
            
            # Show progress bar
            self.write_progress.setVisible(True)
            self.write_progress.setRange(0, 0)  # Indeterminate
            
            # Set initial status
            self._set_label(self.tag_status_label, "Tag status: Preparing write operation...", role="info", bold=True)
            
            # Write to tag
            self.nfc_manager.write_url(content, record_type=record_type)
    
    def _populate_cameras(self) -> None:
        """Populate camera combo box with available cameras."""
        # Clear existing items first
        self.camera_combo.clear()
        
        cameras = QRScanner.get_available_cameras()
        if not cameras:
            self.camera_combo.addItem("No cameras found", None)
            self.start_camera_button.setEnabled(False)
            return
        
        selected_index = 0
        best_match_score = -1
        default_index = self.settings.default_camera_index
        default_name = self.settings.default_camera_name
        
        for i, (index, name) in enumerate(cameras):
            # Store camera index as user data, display name as text
            self.camera_combo.addItem(f"{name} (Index {index})", index)
            
            # Calculate match score (same logic as QR dialog)
            match_score = 0
            name_lower = name.lower()
            is_logitech = any(term in name_lower for term in [
                'logitech', 'c922', 'c920', 'c930', 'c270', 'c310', 'brio'
            ])
            is_virtual = any(term in name_lower for term in [
                'obs', 'virtual', 'screen', 'display'
            ])
            
            if default_index is not None and default_name is not None:
                if index == default_index and name == default_name:
                    match_score = 100
                elif index == default_index:
                    match_score = 50
                elif default_name.lower() in name_lower or name_lower in default_name.lower():
                    match_score = 40 if default_name.lower() == name_lower else 30
            elif default_index is not None:
                if index == default_index:
                    match_score = 50
            elif default_name is not None:
                if default_name.lower() == name_lower:
                    match_score = 40
                elif default_name.lower() in name_lower or name_lower in default_name.lower():
                    match_score = 30
            
            if default_index is None and default_name is None:
                if is_logitech:
                    match_score = 20
                elif not is_virtual:
                    match_score = 10
                else:
                    match_score = -10
            
            if match_score > best_match_score:
                best_match_score = match_score
                selected_index = i
        
        self.camera_combo.setCurrentIndex(selected_index)
    
    def _auto_start_camera(self) -> None:
        """Automatically start the camera if setting is enabled."""
        if self.settings.auto_start_camera and self.camera_combo.count() > 0:
            camera_index = self.camera_combo.currentData()
            if camera_index is not None:
                self._start_camera()
    
    def _on_camera_changed(self) -> None:
        """Handle camera selection change."""
        was_running = False
        if self.qr_scanner_worker and self.qr_scanner_worker.isRunning():
            was_running = True
            self._stop_camera()
        
        # Save camera selection - extract name without index suffix
        camera_index = self.camera_combo.currentData()
        camera_text = self.camera_combo.currentText()
        # Remove " (Index X)" suffix if present
        if " (Index " in camera_text:
            camera_name = camera_text.split(" (Index ")[0]
        else:
            camera_name = camera_text
        
        if camera_index is not None:
            self.settings.set_default_camera(camera_index, camera_name)
            self.logger.debug(f"Selected camera: {camera_name} (Index {camera_index})")
        
        # Restart camera if it was running
        if was_running:
            QTimer.singleShot(300, self._start_camera)
    
    def _start_camera(self) -> None:
        """Start camera and begin scanning."""
        camera_index = self.camera_combo.currentData()
        camera_text = self.camera_combo.currentText()
        
        if camera_index is None:
            QMessageBox.warning(self, "No Camera", "Please select a valid camera.")
            return
        
        # Log which camera is being started for debugging
        self.logger.info(f"Starting camera: {camera_text} (Index {camera_index})")
        
        # Stop any existing scanner
        if self.qr_scanner_worker:
            self._stop_camera()
        
        # Create and start scanner worker with the camera index from combo box data
        self.qr_scanner_worker = QRScannerWorker(camera_index)
        self.qr_scanner_worker.frame_ready.connect(self._on_camera_frame_ready)
        self.qr_scanner_worker.qr_decoded.connect(self._on_qr_decoded)
        self.qr_scanner_worker.error_occurred.connect(self._on_camera_error)
        self.qr_scanner_worker.start()
        
        self.start_camera_button.setEnabled(False)
        self.stop_camera_button.setEnabled(True)
        self.camera_status_label.setText(f"Using camera: {camera_text}")
    
    def _stop_camera(self) -> None:
        """Stop camera and scanning."""
        if self.qr_scanner_worker:
            try:
                self.qr_scanner_worker.frame_ready.disconnect()
                self.qr_scanner_worker.qr_decoded.disconnect()
                self.qr_scanner_worker.error_occurred.disconnect()
            except:
                pass
            
            self.qr_scanner_worker.stop()
            if not self.qr_scanner_worker.wait(3000):
                self.logger.warning("Camera worker thread did not stop within timeout")
                if self.qr_scanner_worker.isRunning():
                    self.qr_scanner_worker.terminate()
                    self.qr_scanner_worker.wait(1000)
            
            self.qr_scanner_worker = None
        
        self.start_camera_button.setEnabled(True)
        self.stop_camera_button.setEnabled(False)
        self.camera_preview_label.setText("Camera stopped")
        self.camera_status_label.setText("Camera stopped")
    
    @pyqtSlot(QImage)
    def _on_camera_frame_ready(self, image: QImage) -> None:
        """Handle new frame from camera."""
        # Scale image to fit label while maintaining aspect ratio
        pixmap = QPixmap.fromImage(image)
        label_size = self.camera_preview_label.size()
        
        # Calculate scaled size maintaining aspect ratio
        scaled_pixmap = pixmap.scaled(
            label_size,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation
        )
        self.camera_preview_label.setPixmap(scaled_pixmap)
    
    @pyqtSlot(str)
    def _on_qr_decoded(self, data: str) -> None:
        """Handle successfully decoded QR code."""
        data = data.strip()
        if not data:
            self.camera_status_label.setText("QR code does not contain valid data")
            return
        
        # Normalize and set URL
        normalized = self._normalize_url(data)
        self.url_input.setText(normalized)
        self.url_input.setFocus()
        display = normalized if len(normalized) <= 50 else normalized[:47] + "..."
        self.camera_status_label.setText(f"QR code scanned: {display}")
        self.status_bar.showMessage("QR code scanned successfully", 3000)
    
    @pyqtSlot(str)
    def _on_camera_error(self, error_msg: str) -> None:
        """Handle camera errors."""
        self.logger.error(f"Camera error: {error_msg}")
        self.camera_status_label.setText(f"Error: {error_msg}")
        QMessageBox.warning(self, "Camera Error", f"An error occurred: {error_msg}")
        self._stop_camera()
    
    def _on_retry_clicked(self) -> None:
        """Handle Retry previous URL button click."""
        if self.settings.last_written_url:
            self.url_input.setText(self.settings.last_written_url)
            self.status_bar.showMessage("Previous URL loaded")
    
    def _on_retry_reader_clicked(self) -> None:
        """Handle retry reader connection button click."""
        self._set_label(self.reader_status_label, "Reader status: Checking...", role="muted")
        self.status_bar.showMessage("Attempting to connect to reader...")
        # Reconnect in a separate thread to avoid blocking UI
        class ConnectionThread(QThread):
            finished = pyqtSignal(bool)
            
            def __init__(self, nfc_manager):
                super().__init__()
                self.nfc_manager = nfc_manager
            
            def run(self):
                result = self.nfc_manager.connect_reader()
                self.finished.emit(result)
        
        self.connection_thread = ConnectionThread(self.nfc_manager)
        self.connection_thread.finished.connect(lambda success: self.status_bar.showMessage("Reader connection attempt completed"))
        self.connection_thread.start()
    
    @pyqtSlot(str)
    def _on_reader_status_changed(self, status: str) -> None:
        """Handle NFC reader status change."""
        if status == "not found":
            self._set_label(self.reader_status_label, "Reader status: Reader not found", role="error")
            help_text = (
                "Reader not found.\n\n"
                "Troubleshooting:\n"
                "1. Ensure ACR122U is connected via USB\n"
                "2. Verify PC/SC service is running (required for nfctagger)\n"
                "3. Check that ACR122U driver is installed\n"
                "4. Try disconnecting and reconnecting the reader\n"
                "5. Restart the application\n\n"
                "Note: nfctagger works with PC/SC running (no need to stop it)."
            )
            self.status_bar.showMessage("Reader not found. Check troubleshooting steps above.")
            # Show a helpful tooltip or we could show a message box on first failure
        else:
            self._set_label(self.reader_status_label, f"Reader status: Reader connected: {status}", role="success")
            self.status_bar.showMessage("Reader connected")
    
    @pyqtSlot(str, dict)
    def _on_tag_detected(self, tag_type: str, tag_info: dict) -> None:
        """Handle NFC tag detection."""
        self.tag_detected = True
        self.tag_type = tag_type
        
        # Track tag capacity for URL size feedback
        capacity = tag_info.get('capacity')
        self.tag_capacity = capacity if isinstance(capacity, int) else None
        
        # Handle MIFARE Classic with custom keys (locked)
        if tag_type == "mifare_classic_locked":
            message = tag_info.get('message', 'MIFARE Classic detected but requires custom keys')
            self._set_label(self.tag_status_label, "Tag status: MIFARE Classic (locked with custom keys)", role="warning")
            self.write_button.setEnabled(False)
            self.status_bar.showMessage("MIFARE Classic detected but authentication failed. Tag uses custom keys.")
            return
        
        ndef_capable = tag_info.get('ndef_capable', False)
        writable = tag_info.get('writable', True)
        
        # Check if tag is NTAG (supports reading) for auto-read
        is_ntag = tag_type and tag_type.startswith('ntag')
        
        if ndef_capable and writable:
            # Format tag type for display
            display_type = tag_type
            if tag_type == 'ntag213':
                display_type = 'NTAG213'
            elif tag_type == 'ntag215':
                display_type = 'NTAG215'
            elif tag_type == 'ntag216':
                display_type = 'NTAG216'
            elif tag_type == 'mifare_ultralight':
                display_type = 'MIFARE Ultralight'
            elif tag_type == 'mifare_classic':
                display_type = 'MIFARE Classic'
            
            self._set_label(self.tag_status_label, f"Tag status: {display_type} detected", role="success")
            
            # Update write button state and refresh URL validation with capacity info
            self._update_write_button_state()
            self._on_url_changed(self.url_input.text())
            
            # Update status bar message
            if self.queue_mode_check.isChecked():
                current_url = self.nfc_manager.get_current_queue_url()
                if current_url:
                    self.status_bar.showMessage(f"Tag detected - ready to write queue URL: {current_url[:50]}...")
                else:
                    self.status_bar.showMessage("Tag detected - queue is empty or complete")
            else:
                self.status_bar.showMessage("Tag detected - ready to write")
            
            # Update tag info panel
            self._update_tag_info_panel(tag_type, tag_info)
            
            # Auto-read tag if setting is enabled and tag supports reading
            if getattr(self.settings, 'auto_read_on_detect', True) and is_ntag:
                self.logger.info(f"Tag detected ({tag_type}) - scheduling auto-read in 200ms")
                # Reduced delay for faster, more reliable reads while tag is still stable
                # Store tag_type in closure to avoid race conditions
                detected_tag_type = tag_type
                def auto_read_with_type():
                    # Re-check tag is still detected and matches
                    if self.tag_detected and self.tag_type == detected_tag_type:
                        self.logger.info(f"Executing scheduled auto-read for {detected_tag_type}")
                        self._auto_read_tag()
                    else:
                        self.logger.debug(f"Auto-read skipped - tag state changed (detected={self.tag_detected}, type={self.tag_type}, expected={detected_tag_type})")
                QTimer.singleShot(200, auto_read_with_type)  # Reduced delay for better reliability
            elif is_ntag:
                self.logger.debug(f"Auto-read disabled in settings for {tag_type}")
        else:
            # Unsupported tag type
            message = tag_info.get('message', 'Unsupported tag type')
            if tag_type == "unsupported":
                status_text = f"Tag status: Detected but not supported ({tag_info.get('type', 'unknown')})"
            else:
                status_text = f"Tag status: Unsupported tag type ({tag_type})"
            self._set_label(self.tag_status_label, status_text, role="warning")
            self.write_button.setEnabled(False)
            # Show helpful message
            if message and len(message) > 100:
                # Truncate long messages for status bar
                self.status_bar.showMessage(message[:100] + "...")
            else:
                self.status_bar.showMessage(message if message else "Tag detected but not supported")
    
    @pyqtSlot()
    def _on_tag_removed(self) -> None:
        """Handle NFC tag removal."""
        self.logger.info("Tag removed signal received - updating UI")
        self.tag_detected = False
        self.tag_type = ""
        self.tag_capacity = None
        self._set_label(self.tag_status_label, "Tag status: No tag detected", role="muted")
        self.write_button.setEnabled(False)
        self.read_tag_button.setEnabled(False)
        self.status_bar.showMessage("Tag removed")
        
        # Clear tag info panel
        self.tag_uid_label.setText("-")
        self.tag_type_label.setText("-")
        self.tag_capacity_label.setText("-")
        self.tag_writable_label.setText("-")
        self._set_label(self.read_url_label, "", role="muted", italic=True)
        self.read_url_label.setToolTip("")
        self.open_url_button.setEnabled(False)
        self.copy_url_button.setEnabled(False)
        self.current_read_url = None
        
        # Refresh URL validation (capacity info no longer applies)
        self._on_url_changed(self.url_input.text())
        
        # Force UI update
        QApplication.processEvents()
    
    def _update_tag_info_panel(self, tag_type: str, tag_info: dict) -> None:
        """Update the tag information panel with current tag details."""
        # UID (no prefix - title label handles it)
        uid = tag_info.get('uid', 'Unknown')
        self.tag_uid_label.setText(uid)
        
        # Type (no prefix - title label handles it)
        display_type = tag_type
        if tag_type == 'ntag213':
            display_type = 'NTAG213'
        elif tag_type == 'ntag215':
            display_type = 'NTAG215'
        elif tag_type == 'ntag216':
            display_type = 'NTAG216'
        elif tag_type == 'mifare_ultralight':
            display_type = 'MIFARE Ultralight'
        elif tag_type == 'mifare_classic':
            display_type = 'MIFARE Classic'
        self.tag_type_label.setText(display_type)
        
        # Capacity (no prefix - title label handles it)
        capacity = tag_info.get('capacity', 'Unknown')
        if isinstance(capacity, int):
            self.tag_capacity_label.setText(f"{capacity} bytes")
        else:
            self.tag_capacity_label.setText(str(capacity))
        
        # Writable (no prefix - title label handles it)
        writable = tag_info.get('writable', True)
        writable_text = "Yes" if writable else "No (Locked)"
        self._set_label(self.tag_writable_label, writable_text,
                        role="success" if writable else "error")
        
        # Enable read button for NTAG tags
        if tag_type and tag_type.startswith('ntag'):
            self.read_tag_button.setEnabled(True)
        else:
            self.read_tag_button.setEnabled(False)
    
    @pyqtSlot()
    def _on_read_tag_clicked(self) -> None:
        """Handle Read Tag button click."""
        self.read_tag_button.setEnabled(False)
        self.read_url_label.setText("Reading tag...")
        self.status_bar.showMessage("Reading tag...")
        self.nfc_manager.read_tag_url()
    
    @pyqtSlot(str, dict)
    def _on_tag_read(self, url: str, tag_info: dict) -> None:
        """Handle tag read completion."""
        self.read_tag_button.setEnabled(True)
        if url:
            self.current_read_url = url
            # Truncate URL if too long to fit in fixed space
            display_url = url if len(url) <= 60 else url[:57] + "..."
            self._set_label(self.read_url_label, f"URL: {display_url}", role="success")
            self.read_url_label.setToolTip(url)
            self.read_url_label.setWordWrap(True)
            # Ensure label stays at fixed height
            self.read_url_label.setMinimumHeight(50)
            self.read_url_label.setMaximumHeight(50)
            # Copy works for any content; open only for browsable URLs
            self.copy_url_button.setEnabled(True)
            try:
                parsed = urllib.parse.urlparse(url)
                is_valid_url = parsed.scheme in ('http', 'https', 'ftp', 'file')
                self.open_url_button.setEnabled(is_valid_url)
            except Exception:
                self.open_url_button.setEnabled(False)
            self.status_bar.showMessage(f"Tag read: {display_url}")
        else:
            self.current_read_url = None
            self._set_label(self.read_url_label, "No URL/text found on tag", role="muted", italic=True)
            self.read_url_label.setToolTip("")
            self.open_url_button.setEnabled(False)
            self.copy_url_button.setEnabled(False)
            self.status_bar.showMessage("Tag read: No URL/text found")
    
    @pyqtSlot()
    def _on_open_url_clicked(self) -> None:
        """Handle Open in Browser button click."""
        if hasattr(self, 'current_read_url') and self.current_read_url:
            try:
                webbrowser.open(self.current_read_url)
                display_url = self.current_read_url if len(self.current_read_url) <= 50 else self.current_read_url[:47] + "..."
                self.status_bar.showMessage(f"Opened {display_url} in browser", 3000)
            except Exception as e:
                QMessageBox.warning(self, "Open Failed", f"Failed to open URL in browser:\n{str(e)}")
                self.logger.error(f"Failed to open URL: {e}")
    
    @pyqtSlot(bool, str)
    def _on_write_verified(self, verified: bool, message: str) -> None:
        """Handle write verification result."""
        if verified:
            self.status_bar.showMessage(f"✓ {message}", 5000)
        else:
            self.status_bar.showMessage(f"⚠ Verification failed: {message}", 10000)
            if self.settings.notify_on_verify:
                self._notify("Write verification failed", message)
    
    def _on_queue_mode_toggled(self, checked: bool) -> None:
        """Handle queue mode toggle."""
        self.queue_group.setVisible(checked)
        self.import_queue_button.setEnabled(checked)
        if checked:
            self.url_input.setEnabled(False)
            self.url_input.setPlaceholderText("Queue mode active - use queue URLs")
            self._update_queue_display()
        else:
            self.url_input.setEnabled(True)
            record_type = self.record_type_combo.currentText()
            if record_type == "Text":
                self.url_input.setPlaceholderText("Enter text to write")
            else:
                self.url_input.setPlaceholderText("Enter URL or scan QR code")
            self.nfc_manager.clear_batch_queue()
            # Update write button state
            self._update_write_button_state()
    
    def _on_import_queue_clicked(self) -> None:
        """Handle Import Queue button click."""
        filename, _ = QFileDialog.getOpenFileName(
            self, "Import Queue", "", "Text Files (*.txt);;CSV Files (*.csv);;All Files (*)"
        )
        if filename:
            try:
                urls = []
                with open(filename, 'r', encoding='utf-8') as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith('#'):
                            # Try to parse as CSV (first column)
                            if filename.endswith('.csv'):
                                parts = line.split(',')
                                if parts:
                                    url = parts[0].strip().strip('"').strip("'")
                                    if url:
                                        urls.append(url)
                            else:
                                urls.append(line)
                
                if urls:
                    self.nfc_manager.set_batch_queue(urls)
                    self._update_queue_display()
                    QMessageBox.information(self, "Queue Imported", f"Imported {len(urls)} URL(s) to queue")
                    self.status_bar.showMessage(f"Queue imported: {len(urls)} URL(s)")
                else:
                    QMessageBox.warning(self, "Import Failed", "No valid URLs found in file")
            except Exception as e:
                QMessageBox.critical(self, "Import Error", f"Failed to import queue:\n{str(e)}")
    
    def _on_clear_queue_clicked(self) -> None:
        """Handle Clear Queue button click."""
        reply = QMessageBox.question(
            self, "Clear Queue",
            "Are you sure you want to clear the queue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.nfc_manager.clear_batch_queue()
            self._update_queue_display()
            self.status_bar.showMessage("Queue cleared")
    
    def _on_reset_progress_clicked(self) -> None:
        """Handle Reset Progress button click."""
        reply = QMessageBox.question(
            self, "Reset Progress",
            "Reset all queue items to pending?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.nfc_manager.reset_batch_progress()
            self._update_queue_display()
            self.status_bar.showMessage("Progress reset")
    
    def _update_queue_display(self) -> None:
        """Update the queue list and progress display."""
        queue = self.nfc_manager.get_batch_queue()
        self.queue_list.clear()
        
        if not queue:
            self.queue_list.addItem("(Queue is empty)")
            self.queue_progress_label.setText("Progress: 0/0")
            self.queue_progress_bar.setValue(0)
            self.clear_queue_button.setEnabled(False)
            self.reset_progress_button.setEnabled(False)
            return
        
        completed = sum(1 for item in queue if item['status'] == 'completed')
        failed = sum(1 for item in queue if item['status'] == 'failed')
        total = len(queue)
        
        for i, item in enumerate(queue):
            url = item['url']
            status = item['status']
            
            # Truncate long URLs for display
            display_url = url if len(url) <= 60 else url[:57] + "..."
            
            if status == 'completed':
                text = f"✓ {i+1}. {display_url}"
                item_widget = QListWidgetItem(text)
                item_widget.setForeground(QColor(0, 128, 0))  # Green
            elif status == 'failed':
                text = f"✗ {i+1}. {display_url}"
                item_widget = QListWidgetItem(text)
                item_widget.setForeground(QColor(200, 0, 0))  # Red
            else:
                text = f"⏳ {i+1}. {display_url}"
                item_widget = QListWidgetItem(text)
                item_widget.setForeground(QColor(128, 128, 128))  # Gray
            
            self.queue_list.addItem(item_widget)
        
        # Update progress
        self.queue_progress_label.setText(f"Progress: {completed}/{total} completed, {failed} failed")
        if total > 0:
            progress = int((completed / total) * 100)
            self.queue_progress_bar.setValue(progress)
        else:
            self.queue_progress_bar.setValue(0)
        
        self.clear_queue_button.setEnabled(True)
        self.reset_progress_button.setEnabled(True)
        
        # Update write button state
        self._update_write_button_state()
        current_url = self.nfc_manager.get_current_queue_url()
        if current_url:
            self.status_bar.showMessage(f"Queue mode: Ready to write '{current_url[:50]}...'")
        else:
            if completed == total:
                self.status_bar.showMessage("Queue complete!")
    
    @pyqtSlot(str)
    def _on_operation_status(self, status: str) -> None:
        """Handle operation status updates from NFC manager."""
        # Style the label to indicate operation in progress
        if "Step" in status or "Preparing" in status or "Clearing" in status or "Writing" in status or "Verifying" in status:
            # Show in-progress styling
            self._set_label(self.tag_status_label, f"Tag status: {status}", role="info", bold=True)
            # Update status bar as well
            self.status_bar.showMessage(status, 0)  # 0 = permanent until changed
        elif "complete" in status.lower():
            # Show success styling briefly
            self._set_label(self.tag_status_label, f"Tag status: {status}", role="success", bold=True)
            self.status_bar.showMessage(status, 3000)  # Show for 3 seconds
        else:
            # Default styling
            self._set_label(self.tag_status_label, f"Tag status: {status}",
                            role="success" if self.tag_detected else "muted")
    
    @pyqtSlot()
    def _on_write_success(self) -> None:
        """Handle successful tag write."""
        # Hide progress bar
        self.write_progress.setVisible(False)
        
        # Reset status to ready after a brief delay to show completion
        if self.tag_detected:
            self._set_label(self.tag_status_label, "Tag status: Ready to write", role="success")
        else:
            self._set_label(self.tag_status_label, "Tag status: No tag detected", role="muted")
        
        # Update queue display if in queue mode
        written_url = None
        if self.queue_mode_check.isChecked():
            self._update_queue_display()
            # The queue is processed in order, so the most recently written
            # URL is the *last* completed item
            queue = self.nfc_manager.get_batch_queue()
            for item in queue:
                if item['status'] == 'completed':
                    written_url = item['url']
            if written_url:
                self.settings.add_recent_url(written_url)
        else:
            # Normal mode - save entered URL
            normalized_url = self._normalize_url(self.current_url)
            written_url = normalized_url
            self.settings.set_last_written_url(normalized_url)
            self.settings.add_recent_url(normalized_url)
            # Clear URL input and current_url only if setting is enabled
            should_clear = self.settings.clear_url_after_write
            self.logger.info(f"Write success - clear_url_after_write={should_clear}, current_url='{self.current_url}', url_input.text='{self.url_input.text()}'")
            if should_clear:
                self.logger.info("Clearing URL input field after successful write")
                # Use a small delay to ensure clear happens after all other operations
                def clear_field():
                    # Block signals temporarily to prevent side effects from textChanged
                    self.url_input.blockSignals(True)
                    try:
                        # Clear the field explicitly
                        self.url_input.setText("")
                        self.current_url = ""
                        self.validation_label.setText("")
                        self.url_valid = False
                        # Force widget update and repaint
                        self.url_input.update()
                        self.url_input.repaint()
                        # Force UI event processing
                        from PyQt6.QtWidgets import QApplication
                        QApplication.processEvents()
                        # Verify it's actually cleared
                        if self.url_input.text():
                            self.logger.warning(f"URL field not cleared! Still contains: '{self.url_input.text()}'")
                            # Try clearing again
                            self.url_input.setText("")
                            self.url_input.update()
                            self.url_input.repaint()
                            QApplication.processEvents()
                        self.logger.info(f"After clear - url_input.text='{self.url_input.text()}', current_url='{self.current_url}'")
                    finally:
                        # Always unblock signals
                        self.url_input.blockSignals(False)
                
                # Clear immediately and also schedule a delayed clear as backup
                clear_field()
                QTimer.singleShot(100, clear_field)  # Backup clear after 100ms
            else:
                self.logger.info("Not clearing URL input field (setting disabled)")
        
        self.retry_button.setEnabled(True)
        
        # Update recent URLs dropdown if it exists
        if hasattr(self, 'recent_urls_combo'):
            self._update_recent_urls_combo()
        
        # Visual success feedback
        self._show_success_indicator()
        
        # Update status
        self.status_bar.showMessage("Write successful. Ready for next card.")
        
        # System notification (if enabled in preferences)
        if self.settings.notify_on_success:
            self._notify("Write successful", written_url or "Content written to tag")
        
        # Auto-read tag after write if setting is enabled
        if self.tag_detected and getattr(self.settings, 'auto_read_after_write', True):
            # Delay to ensure write is complete and tag is stable
            QTimer.singleShot(300, self._auto_read_tag)  # Reduced delay for better reliability
        
        # Re-enable write button if conditions are met
        self._update_write_button_state()
    
    def _auto_read_tag(self) -> None:
        """Automatically read tag if detected and tag type supports reading."""
        self.logger.debug(f"Auto-read check - tag_detected={self.tag_detected}, tag_type={getattr(self, 'tag_type', 'None')}")
        if self.tag_detected and hasattr(self, 'tag_type'):
            # Only auto-read NTAG tags (they support reading)
            if self.tag_type and self.tag_type.startswith('ntag'):
                self.logger.info("Auto-reading tag...")
                # Temporarily disable read button to prevent duplicate reads
                if hasattr(self, 'read_tag_button'):
                    self.read_tag_button.setEnabled(False)
                if hasattr(self, 'read_url_label'):
                    self.read_url_label.setText("Reading tag...")
                self.nfc_manager.read_tag_url()
            else:
                self.logger.debug(f"Skipping auto-read for tag type: {self.tag_type} (not supported)")
        else:
            self.logger.debug(f"Auto-read skipped - tag not detected or no tag_type (detected={self.tag_detected})")
    
    @pyqtSlot(str)
    def _on_write_failed(self, error_msg: str) -> None:
        """Handle failed tag write."""
        # Hide progress bar
        self.write_progress.setVisible(False)
        
        # Reset status
        if self.tag_detected:
            self._set_label(self.tag_status_label, "Tag status: Ready to write", role="success")
        else:
            self._set_label(self.tag_status_label, "Tag status: No tag detected", role="muted")
        
        # Update status bar
        self.status_bar.showMessage("Write failed. Please try again.", 5000)
        
        self.logger.error(f"Write failed: {error_msg}")
        
        # Get user-friendly error message
        user_msg, suggestion = self.nfc_manager._get_user_friendly_error(error_msg)
        
        # Show detailed error dialog
        error_dialog = QMessageBox(self)
        error_dialog.setIcon(QMessageBox.Icon.Warning)
        error_dialog.setWindowTitle("Write Failed")
        error_dialog.setText(user_msg)
        error_dialog.setInformativeText(suggestion)
        error_dialog.setDetailedText(f"Technical details:\n{error_msg}")
        error_dialog.setStandardButtons(QMessageBox.StandardButton.Ok)
        error_dialog.exec()
        
        self.status_bar.showMessage(f"Write failed: {user_msg}")
        
        # Re-enable write button if conditions are met
        self._update_write_button_state()
    
    def _update_recent_urls_combo(self) -> None:
        """Update the recent URLs dropdown."""
        # Block signals while repopulating so placeholder items don't
        # trigger the selection handler
        self.recent_urls_combo.blockSignals(True)
        self.recent_urls_combo.clear()
        recent_urls = self.settings.get_recent_urls()
        if recent_urls:
            self.recent_urls_combo.addItem("-- Select a recent URL --")
            for i, url in enumerate(recent_urls, start=1):
                self.recent_urls_combo.addItem(url)
                # Long URLs get cut off by the combo width; show full URL on hover
                self.recent_urls_combo.setItemData(i, url, Qt.ItemDataRole.ToolTipRole)
            self.recent_urls_combo.setCurrentIndex(0)
            self.recent_urls_combo.setEnabled(True)
            self.clear_history_button.setEnabled(True)
        else:
            self.recent_urls_combo.addItem("(No recent URLs)")
            self.recent_urls_combo.setEnabled(False)
            self.clear_history_button.setEnabled(False)
        self.recent_urls_combo.blockSignals(False)
    
    def _on_recent_url_selected(self, text: str) -> None:
        """Handle recent URL selection from dropdown."""
        if text and text != "-- Select a recent URL --" and text != "(No recent URLs)":
            self.url_input.setText(text)
            self.url_input.setFocus()
            # Reset combo to placeholder
            self.recent_urls_combo.setCurrentIndex(0)
    
    def _on_clear_history_clicked(self) -> None:
        """Handle Clear History button click."""
        reply = QMessageBox.question(
            self, "Clear History",
            "Are you sure you want to clear all recent URLs?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.settings.clear_recent_urls()
            self._update_recent_urls_combo()
            self.status_bar.showMessage("Recent URLs cleared")
    
    def _on_preferences(self) -> None:
        """Handle Preferences menu item."""
        dialog = SettingsDialog(self, self.settings)
        if dialog.exec():
            # Theme may have changed, reapply it
            self._apply_theme()
    
    def _apply_theme(self) -> None:
        """Apply the light/dark theme from settings (or system auto-detect)."""
        self._dark = theme.resolve_dark_mode(self.settings.dark_mode, self)
        self.colors = theme.colors(self._dark)
        self.setStyleSheet(theme.build_stylesheet(self._dark))
        
        # Widget-specific styles that depend on theme colors
        self._reset_success_indicator()
        muted_title = f"font-size: 11px; color: {self.colors['muted']};"
        self.uid_label_title.setStyleSheet(muted_title)
        self.type_label_title.setStyleSheet(muted_title)
        self.capacity_label_title.setStyleSheet(muted_title)
        self.writable_label_title.setStyleSheet(muted_title)
        
        # Re-apply semantic colors on all tracked status labels
        for label, (text, role, bold, italic) in self._label_states.items():
            self._style_label(label, role, bold, italic)
    
    def _on_import_urls(self) -> None:
        """Handle Import URLs menu item."""
        filename, _ = QFileDialog.getOpenFileName(
            self, "Import URLs", "", "Text Files (*.txt);;CSV Files (*.csv);;All Files (*)"
        )
        if filename:
            try:
                urls = []
                with open(filename, 'r', encoding='utf-8') as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith('#'):
                            # Try to parse as CSV (first column)
                            if filename.endswith('.csv'):
                                parts = line.split(',')
                                if parts:
                                    url = parts[0].strip().strip('"').strip("'")
                                    if url:
                                        urls.append(url)
                            else:
                                urls.append(line)
                
                if urls:
                    # Add to recent URLs
                    for url in urls:
                        self.settings.add_recent_url(url)
                    self._update_recent_urls_combo()
                    QMessageBox.information(self, "Import Successful", f"Imported {len(urls)} URL(s)")
                    self.status_bar.showMessage(f"Imported {len(urls)} URL(s)")
                else:
                    QMessageBox.warning(self, "Import Failed", "No valid URLs found in file")
            except Exception as e:
                QMessageBox.critical(self, "Import Error", f"Failed to import URLs:\n{str(e)}")
    
    def _on_export_urls(self) -> None:
        """Handle Export URLs menu item."""
        recent_urls = self.settings.get_recent_urls()
        if not recent_urls:
            QMessageBox.information(self, "No URLs", "No recent URLs to export")
            return
        
        filename, _ = QFileDialog.getSaveFileName(
            self, "Export URLs", "", "Text Files (*.txt);;CSV Files (*.csv);;All Files (*)"
        )
        if filename:
            try:
                with open(filename, 'w', encoding='utf-8') as f:
                    if filename.endswith('.csv'):
                        f.write("URL\n")
                        for url in recent_urls:
                            f.write(f'"{url}"\n')
                    else:
                        for url in recent_urls:
                            f.write(f"{url}\n")
                
                QMessageBox.information(self, "Export Successful", f"Exported {len(recent_urls)} URL(s)")
                self.status_bar.showMessage(f"Exported {len(recent_urls)} URL(s)")
            except Exception as e:
                QMessageBox.critical(self, "Export Error", f"Failed to export URLs:\n{str(e)}")
    
    def _on_about(self) -> None:
        """Handle About menu item."""
        QMessageBox.about(
            self, "About NFC URL Writer",
            "NFC URL Writer\n\n"
            "A desktop application for writing URLs to NFC tags.\n\n"
            "Supports NTAG213, NTAG215, NTAG216, MIFARE Ultralight, and MIFARE Classic tags."
        )
    
    def _show_success_indicator(self) -> None:
        """Show visual success feedback."""
        # Change status panel background to green
        self.status_panel.setStyleSheet(
            f"background-color: {self.colors['success_bg']};"
            f"border: 2px solid {self.colors['success_border']};"
            "border-radius: 8px;"
        )
        
        # Reset after 2 seconds
        self.success_timer.start(2000)
    
    def _reset_success_indicator(self) -> None:
        """Reset success indicator to normal state."""
        self.status_panel.setStyleSheet(
            f"background-color: {self.colors['field']};"
            f"border: 2px solid {self.colors['border']};"
            "border-radius: 8px;"
        )
    
    def closeEvent(self, event) -> None:
        """Handle window close event."""
        # Stop camera
        if self.qr_scanner_worker:
            self._stop_camera()
        
        # Stop NFC polling
        if self.nfc_manager:
            self.nfc_manager.cleanup()
        super().closeEvent(event)

