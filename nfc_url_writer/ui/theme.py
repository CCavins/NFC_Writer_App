"""Centralized theming for NFC URL Writer.

Design language adapted from the vixi2 component library:
Inter typography, 8px radius, 4/8/12/16/24 spacing scale, and the vixi
color system (pink primary #D52265, dark surfaces #1B1B1B/#262626).
The dark palette is vixi's native theme; the light palette is derived
from it with the same primary and semantic hues.
"""

import logging
import tempfile
from pathlib import Path
from string import Template
from typing import Optional

from PyQt6.QtCore import QPointF, Qt
from PyQt6.QtGui import QColor, QFont, QFontDatabase, QPainter, QPen, QPixmap
from PyQt6.QtWidgets import QApplication, QWidget

logger = logging.getLogger(__name__)

_fonts_installed = False


def install_fonts() -> None:
    """Load the bundled Inter font and set it as the application font."""
    global _fonts_installed
    if _fonts_installed:
        return
    _fonts_installed = True
    try:
        font_path = Path(__file__).parent / "fonts" / "Inter.ttf"
        if font_path.exists():
            font_id = QFontDatabase.addApplicationFont(str(font_path))
            families = QFontDatabase.applicationFontFamilies(font_id)
            if families:
                app = QApplication.instance()
                if app is not None:
                    font = QFont(families[0], 13)
                    app.setFont(font)
                logger.debug(f"Installed application font: {families[0]}")
    except Exception as e:
        logger.debug(f"Could not install Inter font: {e}")


# vixi native (dark-first) palette
DARK = {
    # Surfaces
    "window": "#1b1b1b",
    "card": "#262626",
    "field": "#2c2c2c",
    "field_focus": "#2c2c2c",
    "border": "#3a3a3a",
    "border_hover": "#5d5e60",
    # Text
    "text": "#ffffff",
    "muted": "#c5c5c5",
    "disabled_text": "#8a8a8e",
    # Accent (vixi primary)
    "accent": "#d52265",
    "accent_hover": "#e94d87",
    "accent_pressed": "#b01c53",
    "accent_soft": "#442033",
    "disabled_bg": "#333333",
    # Semantic status colors (vixi)
    "success": "#4dbd74",
    "error": "#ff5e4e",
    "warning": "#fec651",
    "info": "#51d9fe",
    "success_bg": "#223a2b",
    "success_border": "#4dbd74",
    # Scrollbars
    "scroll_bg": "#262626",
    "scroll_handle": "#3a3a3a",
    "scroll_handle_hover": "#5d5e60",
}

# Light palette derived from vixi (same primary/semantic hues, darkened
# where needed for contrast on light surfaces)
LIGHT = {
    # Surfaces
    "window": "#f7f7f8",
    "card": "#ffffff",
    "field": "#f4f4f5",
    "field_focus": "#ffffff",
    "border": "#e4e4e7",
    "border_hover": "#cfcfd4",
    # Text
    "text": "#212121",
    "muted": "#6e6e73",
    "disabled_text": "#a1a1a6",
    # Accent (vixi primary)
    "accent": "#d52265",
    "accent_hover": "#b71d57",
    "accent_pressed": "#9a184a",
    "accent_soft": "#fbe7ef",
    "disabled_bg": "#eaeaec",
    # Semantic status colors (contrast-adjusted vixi hues)
    "success": "#278c52",
    "error": "#de3a2c",
    "warning": "#a56a00",
    "info": "#0a7fa3",
    "success_bg": "#e6f6ec",
    "success_border": "#4dbd74",
    # Scrollbars
    "scroll_bg": "#eaeaec",
    "scroll_handle": "#cfcfd4",
    "scroll_handle_hover": "#b5b5ba",
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


_icon_cache = {}


def _icon_url(kind: str, color: str, points) -> str:
    """Render a small line icon and return a file path usable in QSS.

    Qt stylesheets can only load images from files, and the native
    combo-box arrow / checkbox check are unreliable once box properties
    are styled, so we paint our own once per theme color and cache them
    in the temp dir.
    """
    key = (kind, color)
    if key in _icon_cache:
        return _icon_cache[key]
    size = 24  # rendered at 2x, displayed at 12px via QSS width
    pm = QPixmap(size, size)
    pm.setDevicePixelRatio(2.0)
    pm.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pm)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen = QPen(QColor(color), 1.6)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    painter.drawPolyline([QPointF(x, y) for x, y in points])
    painter.end()
    path = Path(tempfile.gettempdir()) / f"nfcurlwriter_{kind}_{color.strip('#')}.png"
    pm.save(str(path))
    url = path.as_posix()
    _icon_cache[key] = url
    return url


def _chevron_down_url(color: str) -> str:
    return _icon_url("chevron", color, [(3, 4.5), (6, 7.5), (9, 4.5)])


def _check_url(color: str) -> str:
    return _icon_url("check", color, [(2.8, 6.2), (5.2, 8.6), (9.2, 3.6)])


_STYLESHEET_TEMPLATE = Template("""
    /* Base typography (Inter, falls back to system font) */
    * {
        font-family: "Inter";
    }

    /* Window surfaces */
    QMainWindow, QDialog {
        background-color: $window;
    }

    /* Scroll areas */
    QScrollArea {
        background-color: transparent;
        border: none;
    }
    QScrollArea > QWidget > QWidget {
        background-color: transparent;
    }
    QScrollBar:vertical {
        background-color: transparent;
        width: 10px;
        border: none;
        margin: 2px;
    }
    QScrollBar::handle:vertical {
        background-color: $scroll_handle;
        border-radius: 3px;
        min-height: 30px;
    }
    QScrollBar::handle:vertical:hover {
        background-color: $scroll_handle_hover;
    }
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
        height: 0px;
    }

    /* Group boxes - card with floating section title above */
    QGroupBox {
        font-size: 13px;
        font-weight: 600;
        color: $text;
        border: 1px solid $border;
        border-radius: 8px;
        background-color: $card;
        margin-top: 26px;
        padding: 4px;
    }
    QGroupBox::title {
        subcontrol-origin: margin;
        subcontrol-position: top left;
        left: 2px;
        top: 2px;
        padding: 0;
        color: $text;
        font-weight: 600;
    }

    /* Input fields */
    QLineEdit {
        background-color: $field;
        border: 1px solid $border;
        border-radius: 8px;
        padding: 9px 12px;
        font-size: 14px;
        color: $text;
        selection-background-color: $accent;
        selection-color: white;
    }
    QLineEdit:hover {
        border: 1px solid $border_hover;
    }
    QLineEdit:focus {
        border: 1px solid $accent;
        background-color: $field_focus;
    }
    QLineEdit:disabled {
        color: $disabled_text;
    }

    /* Combo boxes */
    QComboBox {
        background-color: $field;
        border: 1px solid $border;
        border-radius: 8px;
        padding: 7px 12px;
        font-size: 14px;
        color: $text;
        min-height: 24px;
    }
    QComboBox:hover {
        border: 1px solid $border_hover;
    }
    QComboBox:focus {
        border: 1px solid $accent;
    }
    QComboBox:disabled {
        color: $disabled_text;
    }
    QComboBox::drop-down {
        border: none;
        width: 28px;
    }
    QComboBox::down-arrow {
        image: url("$arrow_url");
        width: 12px;
        height: 12px;
        margin-right: 8px;
    }
    QComboBox QAbstractItemView {
        background-color: $card;
        border: 1px solid $border;
        border-radius: 8px;
        selection-background-color: $accent;
        selection-color: white;
        padding: 4px;
    }

    /* Buttons - vixi solid style */
    QPushButton {
        background-color: $accent;
        color: #ffffff;
        border: none;
        border-radius: 8px;
        padding: 8px 16px;
        font-size: 14px;
        font-weight: 500;
        min-height: 24px;
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

    /* Secondary buttons - outlined */
    QPushButton[class="secondary"] {
        background-color: transparent;
        color: $accent;
        border: 1px solid $accent;
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
        border: 1px solid $border;
    }

    /* Subtle buttons - low-emphasis ghost */
    QPushButton[class="subtle"] {
        background-color: transparent;
        color: $muted;
        border: 1px solid $border_hover;
        border-radius: 6px;
        padding: 4px 10px;
        font-size: 12px;
        font-weight: 500;
        min-height: 20px;
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
        background: transparent;
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
        border-radius: 3px;
        background-color: $disabled_bg;
        text-align: center;
        color: $text;
        font-size: 12px;
        max-height: 6px;
    }
    QProgressBar::chunk {
        background-color: $accent;
        border-radius: 3px;
    }

    /* List widgets */
    QListWidget {
        background-color: $field;
        border: 1px solid $border;
        border-radius: 8px;
        padding: 4px;
        font-size: 13px;
        color: $text;
    }
    QListWidget::item {
        padding: 6px 8px;
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
        background: transparent;
    }
    QCheckBox::indicator {
        width: 18px;
        height: 18px;
        border: 1px solid $border_hover;
        border-radius: 4px;
        background-color: $field;
    }
    QCheckBox::indicator:hover {
        border: 1px solid $accent;
    }
    QCheckBox::indicator:checked {
        background-color: $accent;
        border: 1px solid $accent;
        image: url("$check_url");
    }

    /* Menus */
    QMenuBar {
        background-color: $window;
        border-bottom: 1px solid $border;
        color: $text;
        font-size: 13px;
        padding: 2px 4px;
    }
    QMenuBar::item {
        padding: 6px 12px;
        border-radius: 6px;
    }
    QMenuBar::item:selected {
        background-color: $card;
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

    /* Tooltips */
    QToolTip {
        background-color: $card;
        color: $text;
        border: 1px solid $border;
        border-radius: 6px;
        padding: 6px 8px;
        font-size: 12px;
    }

    /* Camera preview */
    QLabel[class="camera-preview"] {
        background-color: #000000;
        color: #c5c5c5;
        border: 1px solid $border;
        border-radius: 8px;
        font-size: 14px;
    }
""")


def build_stylesheet(dark: bool) -> str:
    """Build the full application stylesheet for the given mode."""
    tokens = dict(colors(dark))
    tokens["arrow_url"] = _chevron_down_url(tokens["muted"])
    tokens["check_url"] = _check_url("#ffffff")
    return _STYLESHEET_TEMPLATE.substitute(tokens)
