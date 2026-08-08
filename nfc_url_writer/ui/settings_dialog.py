"""Settings dialog for NFC URL Writer."""

import logging
from pathlib import Path
from PyQt6.QtWidgets import QDialog
from PyQt6.QtCore import Qt
from PyQt6 import uic

from ..config.settings import Settings
from . import theme


class SettingsDialog(QDialog):
    """Dialog for application settings and preferences."""
    
    def __init__(self, parent=None, settings: Settings = None):
        """Initialize settings dialog.
        
        Args:
            parent: Parent widget
            settings: Settings object to modify
        """
        super().__init__(parent)
        
        # Load UI from .ui file
        ui_file = Path(__file__).parent / "settings_dialog.ui"
        uic.loadUi(ui_file, self)
        
        self.settings = settings
        self.logger = logging.getLogger(__name__)
        
        # Set up combo box items
        self.url_prefix_combo.addItems(["https://", "http://", "https://www.", "http://www."])
        self.url_prefix_combo.setCurrentText("https://")
        
        self.log_level_combo.addItems(["DEBUG", "INFO", "WARNING", "ERROR"])
        self.log_level_combo.setCurrentText("INFO")
        
        self.theme_combo.addItems(["Auto (follow system)", "Light", "Dark"])
        
        # Secondary styling for Cancel (handled by the shared theme stylesheet)
        self.cancel_button.setProperty("class", "secondary")

        # Connect signals
        self.ok_button.clicked.connect(self._on_ok_clicked)
        self.cancel_button.clicked.connect(self.reject)
        
        self._load_settings()
        self._apply_theme()
    
    def _apply_theme(self) -> None:
        """Apply dark/light theme from settings, matching the main window."""
        dark_mode_setting = self.settings.dark_mode if self.settings else False
        dark = theme.resolve_dark_mode(dark_mode_setting, self)
        self.setStyleSheet(theme.build_stylesheet(dark))
    
    def _load_settings(self) -> None:
        """Load current settings into UI."""
        if not self.settings:
            return
        
        self.auto_add_https_check.setChecked(self.settings.auto_add_https)
        self.clear_url_after_write_check.setChecked(self.settings.clear_url_after_write)
        self.auto_read_on_detect_check.setChecked(getattr(self.settings, 'auto_read_on_detect', True))
        self.auto_read_after_write_check.setChecked(getattr(self.settings, 'auto_read_after_write', True))
        self.auto_start_camera_check.setChecked(getattr(self.settings, 'auto_start_camera', True))
        self.notify_on_success_check.setChecked(getattr(self.settings, 'notify_on_success', True))
        self.notify_on_verify_check.setChecked(getattr(self.settings, 'notify_on_verify', True))
        
        log_level = getattr(self.settings, 'log_level', 'INFO')
        index = self.log_level_combo.findText(log_level)
        if index >= 0:
            self.log_level_combo.setCurrentIndex(index)
        
        url_prefix = getattr(self.settings, 'url_prefix', 'https://')
        index = self.url_prefix_combo.findText(url_prefix)
        if index >= 0:
            self.url_prefix_combo.setCurrentIndex(index)
        else:
            self.url_prefix_combo.setCurrentText(url_prefix)
        
        # Load theme setting
        dark_mode = getattr(self.settings, 'dark_mode', None)
        if dark_mode is None:
            self.theme_combo.setCurrentIndex(0)  # Auto
        elif dark_mode:
            self.theme_combo.setCurrentIndex(2)  # Dark
        else:
            self.theme_combo.setCurrentIndex(1)  # Light
    
    def _on_ok_clicked(self) -> None:
        """Handle OK button click - save settings."""
        if not self.settings:
            self.reject()
            return
        
        # Save settings
        self.settings.set_auto_add_https(self.auto_add_https_check.isChecked())
        self.settings.clear_url_after_write = self.clear_url_after_write_check.isChecked()
        self.settings.auto_read_on_detect = self.auto_read_on_detect_check.isChecked()
        self.settings.auto_read_after_write = self.auto_read_after_write_check.isChecked()
        self.settings.auto_start_camera = self.auto_start_camera_check.isChecked()
        self.settings.notify_on_success = self.notify_on_success_check.isChecked()
        self.settings.notify_on_verify = self.notify_on_verify_check.isChecked()
        self.settings.log_level = self.log_level_combo.currentText()
        self.settings.url_prefix = self.url_prefix_combo.currentText()
        
        # Save theme setting
        theme_index = self.theme_combo.currentIndex()
        if theme_index == 0:  # Auto
            self.settings.dark_mode = None
        elif theme_index == 1:  # Light
            self.settings.dark_mode = False
        else:  # Dark
            self.settings.dark_mode = True
        
        self.settings.save()
        
        # Apply logging level
        log_level = getattr(logging, self.settings.log_level, logging.INFO)
        logging.getLogger().setLevel(log_level)
        
        # Reapply theme in case it changed
        self._apply_theme()
        
        # Signal that theme changed (parent window should apply it)
        self.accept()
