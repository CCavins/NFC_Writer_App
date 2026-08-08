"""Centralized theming for NFC URL Writer.

Defines the light/dark color palettes and builds the application-wide
stylesheet from a single template, so the main window and dialogs stay
visually consistent and colors are defined in exactly one place.
"""

from string import Template
from typing import Optional

from PyQt6.QtWidgets import QWidget

LIGHT = {
    # Surfaces
    "window": "#f5f5f7",
    "card": "#ffffff",
    "field": "#f5f5f7",
    "field_focus": "#ffffff",
    "border": "#e5e5e7",
    "border_hover": "#d1d1d6",
    # Text
    "text": "#1d1d1f",
    "muted": "#6e6e73",
    "disabled_text": "#8e8e93",
    # Accent
    "accent": "#007aff",
    "accent_hover": "#0051d5",
    "accent_pressed": "#0040a8",
    "accent_soft": "#e8f2ff",
    "disabled_bg": "#e5e5e7",
    # Semantic status colors (chosen for contrast on light surfaces)
    "success": "#1e8e3e",
    "error": "#d70015",
    "warning": "#c93400",
    "info": "#007aff",
    "success_bg": "#e4f7e9",
    "success_border": "#34c759",
    # Scrollbars
    "scroll_bg": "#e5e5e7",
    "scroll_handle": "#d1d1d6",
    "scroll_handle_hover": "#b8b8bc",
}

DARK = {
    # Surfaces
    "window": "#1c1c1e",
    "card": "#2c2c2e",
    "field": "#1c1c1e",
    "field_focus": "#2c2c2e",
    "border": "#38383a",
    "border_hover": "#48484a",
    # Text
    "text": "#ffffff",
    "muted": "#98989d",
    "disabled_text": "#8e8e93",
    # Accent
    "accent": "#0a84ff",
    "accent_hover": "#3395ff",
    "accent_pressed": "#0060df",
    "accent_soft": "#1c3a5e",
    "disabled_bg": "#38383a",
    # Semantic status colors (chosen for contrast on dark surfaces)
    "success": "#32d74b",
    "error": "#ff453a",
    "warning": "#ff9f0a",
    "info": "#0a84ff",
    "success_bg": "#1e3b26",
    "success_border": "#32d74b",
    # Scrollbars
    "scroll_bg": "#2c2c2e",
    "scroll_handle": "#48484a",
    "scroll_handle_hover": "#5a5a5c",
}


def resolve_dark_mode(dark_mode_setting: Optional[bool], widget: QWidget) -> bool:
    """Resolve the effective dark mode: explicit setting or system detection."""
    if dark_mode_setting is not None:
        return dark_mode_setting
    palette = widget.palette()
    bg_color = palette.color(palette.ColorRole.Window)
    return bg_color.lightness() < 128


def colors(dark: bool) -> dict:
    """Return the color token dictionary for the given mode."""
    return DARK if dark else LIGHT


_STYLESHEET_TEMPLATE = Template("""
    /* Window surfaces */
    QMainWindow, QDialog {
        background-color: $window;
    }

    /* Scroll areas */
    QScrollArea {
        background-color: $window;
        border: none;
    }
    QScrollArea > QWidget > QWidget {
        background-color: transparent;
    }
    QScrollBar:vertical {
        background-color: $scroll_bg;
        width: 12px;
        border: none;
    }
    QScrollBar::handle:vertical {
        background-color: $scroll_handle;
        border-radius: 6px;
        min-height: 30px;
    }
    QScrollBar::handle:vertical:hover {
        background-color: $scroll_handle_hover;
    }
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
        height: 0px;
    }

    /* Group boxes - card style */
    QGroupBox {
        font-weight: 600;
        font-size: 13px;
        color: $text;
        border: none;
        border-radius: 12px;
        background-color: $card;
        margin-top: 8px;
        padding-top: 16px;
        padding: 12px;
    }
    QGroupBox::title {
        subcontrol-origin: margin;
        left: 16px;
        padding: 0 8px;
        color: $text;
        font-weight: 600;
    }

    /* Input fields */
    QLineEdit {
        background-color: $field;
        border: 2px solid $border;
        border-radius: 8px;
        padding: 8px 12px;
        font-size: 14px;
        color: $text;
        selection-background-color: $accent;
        selection-color: white;
    }
    QLineEdit:focus {
        border: 2px solid $accent;
        background-color: $field_focus;
    }
    QLineEdit:hover {
        border: 2px solid $border_hover;
    }
    QLineEdit:disabled {
        color: $disabled_text;
    }

    /* Combo boxes */
    QComboBox {
        background-color: $field;
        border: 2px solid $border;
        border-radius: 8px;
        padding: 6px 12px;
        font-size: 14px;
        color: $text;
        min-height: 28px;
    }
    QComboBox:hover {
        border: 2px solid $border_hover;
    }
    QComboBox:focus {
        border: 2px solid $accent;
    }
    QComboBox:disabled {
        color: $disabled_text;
    }
    QComboBox::drop-down {
        border: none;
        width: 30px;
    }
    QComboBox::down-arrow {
        image: none;
        border-left: 5px solid transparent;
        border-right: 5px solid transparent;
        border-top: 6px solid $text;
        margin-right: 10px;
    }
    QComboBox QAbstractItemView {
        background-color: $card;
        border: 1px solid $border;
        border-radius: 8px;
        selection-background-color: $accent;
        selection-color: white;
        padding: 4px;
    }

    /* Buttons */
    QPushButton {
        background-color: $accent;
        color: #ffffff;
        border: none;
        border-radius: 8px;
        padding: 6px 16px;
        font-size: 14px;
        font-weight: 500;
        min-height: 32px;
    }
    QPushButton:hover {
        background-color: $accent_hover;
    }
    QPushButton:pressed {
        background-color: $accent_pressed;
    }
    QPushButton:disabled {
        background-color: $disabled_bg;
        color: $disabled_text;
    }

    /* Secondary buttons */
    QPushButton[class="secondary"] {
        background-color: transparent;
        color: $accent;
        border: 2px solid $accent;
    }
    QPushButton[class="secondary"]:hover {
        background-color: $accent_soft;
    }
    QPushButton[class="secondary"]:pressed {
        background-color: $accent_soft;
    }
    QPushButton[class="secondary"]:disabled {
        background-color: transparent;
        color: $disabled_text;
        border: 2px solid $border;
    }

    /* Subtle buttons (low-emphasis actions) */
    QPushButton[class="subtle"] {
        background-color: transparent;
        color: $muted;
        border: 1px solid $border_hover;
        border-radius: 6px;
        padding: 4px 10px;
        font-size: 12px;
        min-height: 26px;
    }
    QPushButton[class="subtle"]:hover {
        background-color: $field;
        border-color: $accent;
        color: $accent;
    }
    QPushButton[class="subtle"]:pressed {
        background-color: $accent_soft;
    }

    /* Labels */
    QLabel {
        color: $text;
        font-size: 14px;
    }

    /* Status bar */
    QStatusBar {
        background-color: $card;
        border-top: 1px solid $border;
        color: $muted;
        font-size: 12px;
    }

    /* Progress bars */
    QProgressBar {
        border: none;
        border-radius: 4px;
        background-color: $disabled_bg;
        text-align: center;
        color: $text;
        font-size: 12px;
        height: 6px;
    }
    QProgressBar::chunk {
        background-color: $accent;
        border-radius: 4px;
    }

    /* List widgets */
    QListWidget {
        background-color: $field;
        border: 2px solid $border;
        border-radius: 8px;
        padding: 4px;
        font-size: 14px;
        color: $text;
    }
    QListWidget::item {
        padding: 8px;
        border-radius: 6px;
    }
    QListWidget::item:selected {
        background-color: $accent;
        color: white;
    }
    QListWidget::item:hover {
        background-color: $accent_soft;
    }

    /* Checkboxes */
    QCheckBox {
        font-size: 14px;
        color: $text;
        spacing: 8px;
    }
    QCheckBox::indicator {
        width: 20px;
        height: 20px;
        border: 2px solid $border_hover;
        border-radius: 4px;
        background-color: $card;
    }
    QCheckBox::indicator:hover {
        border: 2px solid $accent;
    }
    QCheckBox::indicator:checked {
        background-color: $accent;
        border: 2px solid $accent;
    }

    /* Menus */
    QMenuBar {
        background-color: $card;
        border-bottom: 1px solid $border;
        color: $text;
        font-size: 13px;
        padding: 4px;
    }
    QMenuBar::item {
        padding: 6px 12px;
        border-radius: 6px;
    }
    QMenuBar::item:selected {
        background-color: $window;
    }
    QMenu {
        background-color: $card;
        border: 1px solid $border;
        border-radius: 8px;
        padding: 4px;
    }
    QMenu::item {
        padding: 8px 24px;
        border-radius: 6px;
    }
    QMenu::item:selected {
        background-color: $accent;
        color: white;
    }

    /* Camera preview */
    QLabel[class="camera-preview"] {
        background-color: #000000;
        color: #ffffff;
        border: 2px solid $border;
        border-radius: 12px;
        font-size: 16px;
    }
""")


def build_stylesheet(dark: bool) -> str:
    """Build the full application stylesheet for the given mode."""
    return _STYLESHEET_TEMPLATE.substitute(colors(dark))
