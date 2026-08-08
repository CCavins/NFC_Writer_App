"""Settings dialog for NFC URL Writer."""

import logging
from pathlib import Path
from PyQt6.QtWidgets import QDialog
from PyQt6.QtCore import Qt
from PyQt6 import uic

from ..config.settings import Settings


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
        
        # Connect signals
        self.ok_button.clicked.connect(self._on_ok_clicked)
        self.cancel_button.clicked.connect(self.reject)
        
        self._load_settings()
        self._apply_theme()
    
    def _apply_theme(self) -> None:
        """Apply dark/light theme based on settings, matching main window."""
        if not self.settings:
            # Default to light if no settings
            dark_mode = False
        else:
            dark_mode = self.settings.dark_mode
            
            # Auto-detect if None
            if dark_mode is None:
                # Check system theme
                palette = self.palette()
                bg_color = palette.color(palette.ColorRole.Window)
                # If background is dark, use dark mode
                dark_mode = bg_color.lightness() < 128
        
        if dark_mode:
            # Dark theme - matching main window
            self.setStyleSheet("""
                /* Settings Dialog */
                QDialog {
                    background-color: #1c1c1e;
                }
                
                /* Scroll Area */
                QScrollArea {
                    background-color: #1c1c1e;
                    border: none;
                }
                QScrollBar:vertical {
                    background-color: #2c2c2e;
                    width: 12px;
                    border: none;
                }
                QScrollBar::handle:vertical {
                    background-color: #48484a;
                    border-radius: 6px;
                    min-height: 30px;
                }
                QScrollBar::handle:vertical:hover {
                    background-color: #5a5a5c;
                }
                QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                    height: 0px;
                }
                
                /* Group Boxes */
                QGroupBox {
                    font-weight: 600;
                    font-size: 13px;
                    color: #ffffff;
                    border: none;
                    border-radius: 12px;
                    background-color: #2c2c2e;
                    margin-top: 8px;
                    padding-top: 16px;
                    padding: 12px;
                }
                QGroupBox::title {
                    subcontrol-origin: margin;
                    left: 16px;
                    padding: 0 8px;
                    color: #ffffff;
                    font-weight: 600;
                }
                
                /* Combo Boxes */
                QComboBox {
                    background-color: #1c1c1e;
                    border: 2px solid #38383a;
                    border-radius: 8px;
                    padding: 6px 12px;
                    font-size: 14px;
                    color: #ffffff;
                    min-height: 28px;
                }
                QComboBox:hover {
                    border: 2px solid #48484a;
                }
                QComboBox:focus {
                    border: 2px solid #0a84ff;
                }
                QComboBox::drop-down {
                    border: none;
                    width: 30px;
                }
                QComboBox::down-arrow {
                    image: none;
                    border-left: 5px solid transparent;
                    border-right: 5px solid transparent;
                    border-top: 6px solid #ffffff;
                    margin-right: 10px;
                }
                QComboBox QAbstractItemView {
                    background-color: #2c2c2e;
                    border: 1px solid #38383a;
                    border-radius: 8px;
                    selection-background-color: #0a84ff;
                    selection-color: white;
                    padding: 4px;
                }
                
                /* Buttons */
                QPushButton {
                    background-color: #0a84ff;
                    color: #ffffff;
                    border: none;
                    border-radius: 8px;
                    padding: 6px 16px;
                    font-size: 14px;
                    font-weight: 500;
                    min-height: 32px;
                }
                QPushButton:hover {
                    background-color: #0051d5;
                }
                QPushButton:pressed {
                    background-color: #0040a8;
                }
                
                /* Cancel button - secondary style */
                QPushButton[text="Cancel"] {
                    background-color: transparent;
                    color: #0a84ff;
                    border: 2px solid #0a84ff;
                }
                QPushButton[text="Cancel"]:hover {
                    background-color: rgba(10, 132, 255, 0.1);
                }
                QPushButton[text="Cancel"]:pressed {
                    background-color: rgba(10, 132, 255, 0.2);
                }
                
                /* Labels */
                QLabel {
                    color: #ffffff;
                    font-size: 14px;
                }
                
                /* Checkbox */
                QCheckBox {
                    font-size: 14px;
                    color: #ffffff;
                    spacing: 8px;
                }
                QCheckBox::indicator {
                    width: 20px;
                    height: 20px;
                    border: 2px solid #48484a;
                    border-radius: 4px;
                    background-color: #1c1c1e;
                }
                QCheckBox::indicator:hover {
                    border: 2px solid #0a84ff;
                }
                QCheckBox::indicator:checked {
                    background-color: #0a84ff;
                    border: 2px solid #0a84ff;
                }
            """)
        else:
            # Light theme - matching main window
            self.setStyleSheet("""
                /* Settings Dialog */
                QDialog {
                    background-color: #f5f5f7;
                }
                
                /* Scroll Area */
                QScrollArea {
                    background-color: #f5f5f7;
                    border: none;
                }
                QScrollBar:vertical {
                    background-color: #e5e5e7;
                    width: 12px;
                    border: none;
                }
                QScrollBar::handle:vertical {
                    background-color: #d1d1d6;
                    border-radius: 6px;
                    min-height: 30px;
                }
                QScrollBar::handle:vertical:hover {
                    background-color: #b8b8bc;
                }
                QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                    height: 0px;
                }
                
                /* Group Boxes */
                QGroupBox {
                    font-weight: 600;
                    font-size: 13px;
                    color: #1d1d1f;
                    border: none;
                    border-radius: 12px;
                    background-color: #ffffff;
                    margin-top: 8px;
                    padding-top: 16px;
                    padding: 12px;
                }
                QGroupBox::title {
                    subcontrol-origin: margin;
                    left: 16px;
                    padding: 0 8px;
                    color: #1d1d1f;
                    font-weight: 600;
                }
                
                /* Combo Boxes */
                QComboBox {
                    background-color: #f5f5f7;
                    border: 2px solid #e5e5e7;
                    border-radius: 8px;
                    padding: 6px 12px;
                    font-size: 14px;
                    color: #1d1d1f;
                    min-height: 28px;
                }
                QComboBox:hover {
                    border: 2px solid #d1d1d6;
                }
                QComboBox:focus {
                    border: 2px solid #007aff;
                }
                QComboBox::drop-down {
                    border: none;
                    width: 30px;
                }
                QComboBox::down-arrow {
                    image: none;
                    border-left: 5px solid transparent;
                    border-right: 5px solid transparent;
                    border-top: 6px solid #1d1d1f;
                    margin-right: 10px;
                }
                QComboBox QAbstractItemView {
                    background-color: #ffffff;
                    border: 1px solid #e5e5e7;
                    border-radius: 8px;
                    selection-background-color: #007aff;
                    selection-color: white;
                    padding: 4px;
                }
                
                /* Buttons */
                QPushButton {
                    background-color: #007aff;
                    color: #ffffff;
                    border: none;
                    border-radius: 8px;
                    padding: 6px 16px;
                    font-size: 14px;
                    font-weight: 500;
                    min-height: 32px;
                }
                QPushButton:hover {
                    background-color: #0051d5;
                }
                QPushButton:pressed {
                    background-color: #0040a8;
                }
                
                /* Cancel button - secondary style */
                QPushButton[text="Cancel"] {
                    background-color: transparent;
                    color: #007aff;
                    border: 2px solid #007aff;
                }
                QPushButton[text="Cancel"]:hover {
                    background-color: rgba(0, 122, 255, 0.1);
                }
                QPushButton[text="Cancel"]:pressed {
                    background-color: rgba(0, 122, 255, 0.2);
                }
                
                /* Labels */
                QLabel {
                    color: #1d1d1f;
                    font-size: 14px;
                }
                
                /* Checkbox */
                QCheckBox {
                    font-size: 14px;
                    color: #1d1d1f;
                    spacing: 8px;
                }
                QCheckBox::indicator {
                    width: 20px;
                    height: 20px;
                    border: 2px solid #d1d1d6;
                    border-radius: 4px;
                    background-color: #ffffff;
                }
                QCheckBox::indicator:hover {
                    border: 2px solid #007aff;
                }
                QCheckBox::indicator:checked {
                    background-color: #007aff;
                    border: 2px solid #007aff;
                }
            """)
    
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
