"""Light and dark visual themes for the desktop shell."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from PySide6 import QtGui, QtWidgets


class UiThemeMode(StrEnum):
    LIGHT = "light"
    DARK = "dark"


@dataclass(frozen=True, slots=True)
class ThemeColors:
    background: str
    card: str
    card_muted: str
    raised: str
    separator: str
    separator_soft: str
    text: str
    secondary_text: str
    tertiary_text: str
    blue: str
    blue_pressed: str
    green: str
    red: str
    orange: str
    health_background: str
    health_text: str
    health_border: str
    blocked_background: str
    blocked_text: str
    blocked_border: str
    tab_background: str
    tab_border: str
    hover: str
    pressed: str
    chart_grid: str
    chart_volume: str
    highlighted_text: str


LIGHT_THEME = ThemeColors(
    background="#F2F2F7",
    card="#FFFFFF",
    card_muted="#F9F9FB",
    raised="#FFFFFF",
    separator="#D1D1D6",
    separator_soft="#E5E5EA",
    text="#1C1C1E",
    secondary_text="#6E6E73",
    tertiary_text="#8E8E93",
    blue="#007AFF",
    blue_pressed="#005ECF",
    green="#34C759",
    red="#FF3B30",
    orange="#FF9500",
    health_background="rgba(52, 199, 89, 0.12)",
    health_text="#176C2E",
    health_border="rgba(52, 199, 89, 0.40)",
    blocked_background="rgba(255, 59, 48, 0.12)",
    blocked_text="#8E120B",
    blocked_border="rgba(255, 59, 48, 0.44)",
    tab_background="#E9E9EE",
    tab_border="#E0E0E6",
    hover="#F7F7FA",
    pressed="#E9E9EE",
    chart_grid="#EFEFF4",
    chart_volume="#D1D1D6",
    highlighted_text="#FFFFFF",
)

DARK_THEME = ThemeColors(
    background="#090A0F",
    card="#14161D",
    card_muted="#1B1E27",
    raised="#20242E",
    separator="#3A3F4B",
    separator_soft="#2A2F3A",
    text="#F4F7FB",
    secondary_text="#A8B0BE",
    tertiary_text="#7D8594",
    blue="#4DA3FF",
    blue_pressed="#2587E8",
    green="#30D158",
    red="#FF453A",
    orange="#FF9F0A",
    health_background="rgba(48, 209, 88, 0.14)",
    health_text="#9EF2B2",
    health_border="rgba(48, 209, 88, 0.46)",
    blocked_background="rgba(255, 69, 58, 0.16)",
    blocked_text="#FFB5AF",
    blocked_border="rgba(255, 69, 58, 0.52)",
    tab_background="#171A22",
    tab_border="#2D3340",
    hover="#252B36",
    pressed="#303746",
    chart_grid="#252B36",
    chart_volume="#3A4353",
    highlighted_text="#FFFFFF",
)

DEFAULT_THEME_MODE = UiThemeMode.DARK

IOS_BACKGROUND = LIGHT_THEME.background
IOS_CARD = LIGHT_THEME.card
IOS_CARD_MUTED = LIGHT_THEME.card_muted
IOS_SEPARATOR = LIGHT_THEME.separator
IOS_SEPARATOR_SOFT = LIGHT_THEME.separator_soft
IOS_TEXT = LIGHT_THEME.text
IOS_SECONDARY_TEXT = LIGHT_THEME.secondary_text
IOS_TERTIARY_TEXT = LIGHT_THEME.tertiary_text
IOS_BLUE = LIGHT_THEME.blue
IOS_BLUE_PRESSED = LIGHT_THEME.blue_pressed
IOS_GREEN = LIGHT_THEME.green
IOS_RED = LIGHT_THEME.red
IOS_ORANGE = LIGHT_THEME.orange


def coerce_theme_mode(value: object, *, default: UiThemeMode = DEFAULT_THEME_MODE) -> UiThemeMode:
    if isinstance(value, UiThemeMode):
        return value
    if isinstance(value, str):
        try:
            return UiThemeMode(value)
        except ValueError:
            return default
    return default


def get_theme_colors(mode: UiThemeMode | str) -> ThemeColors:
    theme_mode = coerce_theme_mode(mode)
    return DARK_THEME if theme_mode is UiThemeMode.DARK else LIGHT_THEME


def apply_theme_palette(app: QtWidgets.QApplication, mode: UiThemeMode | str) -> None:
    """Apply the selected application palette and standard UI font."""

    colors = get_theme_colors(mode)
    families = set(QtGui.QFontDatabase.families())
    family = "Microsoft YaHei UI"
    if family not in families:
        family = "Microsoft YaHei" if "Microsoft YaHei" in families else "Segoe UI"
    font = QtGui.QFont(family)
    font.setPointSize(10)
    app.setFont(font)
    app.setProperty("themeMode", coerce_theme_mode(mode).value)

    palette = QtGui.QPalette()
    palette.setColor(QtGui.QPalette.ColorRole.Window, QtGui.QColor(colors.background))
    palette.setColor(QtGui.QPalette.ColorRole.WindowText, QtGui.QColor(colors.text))
    palette.setColor(QtGui.QPalette.ColorRole.Base, QtGui.QColor(colors.card))
    palette.setColor(QtGui.QPalette.ColorRole.AlternateBase, QtGui.QColor(colors.card_muted))
    palette.setColor(QtGui.QPalette.ColorRole.Text, QtGui.QColor(colors.text))
    palette.setColor(QtGui.QPalette.ColorRole.Button, QtGui.QColor(colors.raised))
    palette.setColor(QtGui.QPalette.ColorRole.ButtonText, QtGui.QColor(colors.text))
    palette.setColor(QtGui.QPalette.ColorRole.Highlight, QtGui.QColor(colors.blue))
    palette.setColor(
        QtGui.QPalette.ColorRole.HighlightedText,
        QtGui.QColor(colors.highlighted_text),
    )
    app.setPalette(palette)


def apply_ios_palette(app: QtWidgets.QApplication) -> None:
    """Backward-compatible helper that applies the default theme."""

    apply_theme_palette(app, DEFAULT_THEME_MODE)


def style_sheet_for(mode: UiThemeMode | str) -> str:
    colors = get_theme_colors(mode)
    return f"""
QMainWindow,
QWidget#appRoot {{
    background: {colors.background};
    color: {colors.text};
    font-family: "Microsoft YaHei UI", "Microsoft YaHei", "Segoe UI";
}}

QStatusBar {{
    background: {colors.background};
    border-top: 1px solid {colors.separator_soft};
    color: {colors.secondary_text};
}}

QMenu {{
    background: {colors.raised};
    border: 1px solid {colors.separator_soft};
    border-radius: 8px;
    padding: 6px;
    color: {colors.text};
}}

QMenu::item {{
    border-radius: 6px;
    padding: 7px 24px 7px 24px;
}}

QMenu::item:selected {{
    background: {colors.hover};
}}

QMenu::indicator:checked {{
    background: {colors.blue};
    border-radius: 5px;
}}

QLabel {{
    color: {colors.text};
}}

QLabel#marketTime,
QLabel#stateLabel,
QLabel#chartSummary {{
    color: {colors.secondary_text};
    font-size: 12px;
}}

QLabel#healthBanner {{
    border: 1px solid {colors.health_border};
    border-radius: 8px;
    padding: 6px 12px;
    background: {colors.health_background};
    color: {colors.health_text};
    font-weight: 600;
}}

QLabel#healthBanner[blocked="true"] {{
    background: {colors.blocked_background};
    color: {colors.blocked_text};
    border-color: {colors.blocked_border};
}}

QGroupBox {{
    background: {colors.card};
    border: 1px solid {colors.separator_soft};
    border-radius: 8px;
    margin-top: 18px;
    padding: 14px 10px 10px 10px;
    font-weight: 700;
    color: {colors.text};
}}

QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 10px;
    top: 0px;
    padding: 0 4px;
    color: {colors.secondary_text};
    font-size: 12px;
}}

QLineEdit {{
    background: {colors.card};
    border: 1px solid {colors.separator_soft};
    border-radius: 8px;
    min-height: 28px;
    padding: 5px 12px;
    color: {colors.text};
    selection-background-color: {colors.blue};
    selection-color: {colors.highlighted_text};
}}

QLineEdit:focus {{
    border: 1px solid {colors.blue};
}}

QListWidget,
QTextBrowser {{
    background: {colors.card};
    border: 1px solid {colors.separator_soft};
    border-radius: 8px;
    padding: 4px;
    color: {colors.text};
    selection-background-color: rgba(77, 163, 255, 0.24);
    selection-color: {colors.text};
}}

QListWidget::item {{
    min-height: 28px;
    border-radius: 6px;
    padding: 5px 8px;
}}

QListWidget::item:selected,
QListWidget::item:hover {{
    background: rgba(77, 163, 255, 0.20);
    color: {colors.text};
}}

QTabWidget::pane {{
    border: 1px solid {colors.separator_soft};
    border-radius: 8px;
    background: {colors.card};
    top: -1px;
}}

QTabBar::tab {{
    background: {colors.tab_background};
    color: {colors.secondary_text};
    border: 1px solid {colors.tab_border};
    padding: 7px 16px;
    min-width: 76px;
}}

QTabBar::tab:first {{
    border-top-left-radius: 8px;
    border-bottom-left-radius: 8px;
}}

QTabBar::tab:last {{
    border-top-right-radius: 8px;
    border-bottom-right-radius: 8px;
}}

QTabBar::tab:selected {{
    background: {colors.card};
    color: {colors.text};
    border-color: {colors.separator};
    font-weight: 700;
}}

QComboBox {{
    background: {colors.card};
    border: 1px solid {colors.separator_soft};
    border-radius: 8px;
    padding: 5px 28px 5px 10px;
    min-height: 26px;
    color: {colors.text};
    selection-background-color: {colors.blue};
}}

QComboBox:focus {{
    border-color: {colors.blue};
}}

QComboBox::drop-down {{
    width: 24px;
    border: 0;
}}

QSpinBox {{
    background: {colors.card};
    border: 1px solid {colors.separator_soft};
    border-radius: 8px;
    padding: 5px 24px 5px 10px;
    min-height: 26px;
    color: {colors.text};
    selection-background-color: {colors.blue};
    selection-color: {colors.highlighted_text};
}}

QSpinBox:focus {{
    border-color: {colors.blue};
}}

QSpinBox::up-button,
QSpinBox::down-button {{
    subcontrol-origin: border;
    width: 18px;
    border: 0;
    background: {colors.card};
}}

QSpinBox::up-button {{
    subcontrol-position: top right;
    border-top-right-radius: 8px;
}}

QSpinBox::down-button {{
    subcontrol-position: bottom right;
    border-bottom-right-radius: 8px;
}}

QSpinBox::up-button:hover,
QSpinBox::down-button:hover {{
    background: {colors.hover};
}}

QCheckBox {{
    color: {colors.secondary_text};
    spacing: 6px;
}}

QCheckBox::indicator {{
    width: 18px;
    height: 18px;
    border-radius: 8px;
    border: 1px solid {colors.separator};
    background: {colors.card};
}}

QCheckBox::indicator:checked {{
    background: {colors.blue};
    border: 1px solid {colors.blue};
}}

QToolButton {{
    background: {colors.card};
    border: 1px solid {colors.separator_soft};
    border-radius: 8px;
    min-width: 30px;
    min-height: 30px;
    padding: 2px;
    color: {colors.text};
}}

QToolButton:hover {{
    background: {colors.hover};
    border-color: {colors.separator};
}}

QToolButton:pressed {{
    background: {colors.pressed};
}}

QPushButton {{
    background: {colors.raised};
    border: 1px solid {colors.separator_soft};
    border-radius: 8px;
    min-height: 28px;
    padding: 5px 14px;
    color: {colors.text};
    font-weight: 600;
}}

QPushButton:hover {{
    background: {colors.hover};
    border-color: {colors.separator};
}}

QPushButton#chartBacktestButton[active="true"] {{
    background: {colors.blue};
    border-color: {colors.blue};
    color: {colors.highlighted_text};
}}

QPushButton#chartBacktestButton[active="true"]:hover {{
    background: {colors.blue_pressed};
    border-color: {colors.blue_pressed};
}}

QPushButton:pressed {{
    background: {colors.pressed};
}}

QPushButton:disabled {{
    color: {colors.tertiary_text};
    background: {colors.card_muted};
    border-color: {colors.separator_soft};
}}

QSplitter::handle {{
    background: transparent;
}}

QScrollBar:vertical {{
    background: transparent;
    width: 10px;
    margin: 2px;
}}

QScrollBar::handle:vertical {{
    background: rgba(142, 142, 147, 0.45);
    border-radius: 5px;
    min-height: 24px;
}}

QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical {{
    height: 0;
}}
"""


IOS_STYLE_SHEET = style_sheet_for(UiThemeMode.LIGHT)


__all__ = [
    "DEFAULT_THEME_MODE",
    "DARK_THEME",
    "IOS_BACKGROUND",
    "IOS_BLUE",
    "IOS_BLUE_PRESSED",
    "IOS_CARD",
    "IOS_CARD_MUTED",
    "IOS_GREEN",
    "IOS_ORANGE",
    "IOS_RED",
    "IOS_SECONDARY_TEXT",
    "IOS_SEPARATOR",
    "IOS_SEPARATOR_SOFT",
    "IOS_STYLE_SHEET",
    "IOS_TEXT",
    "IOS_TERTIARY_TEXT",
    "LIGHT_THEME",
    "ThemeColors",
    "UiThemeMode",
    "apply_ios_palette",
    "apply_theme_palette",
    "coerce_theme_mode",
    "get_theme_colors",
    "style_sheet_for",
]
