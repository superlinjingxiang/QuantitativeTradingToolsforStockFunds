"""iOS-inspired visual theme for the desktop shell."""

from __future__ import annotations

from PySide6 import QtGui, QtWidgets

IOS_BACKGROUND = "#F2F2F7"
IOS_CARD = "#FFFFFF"
IOS_CARD_MUTED = "#F9F9FB"
IOS_SEPARATOR = "#D1D1D6"
IOS_SEPARATOR_SOFT = "#E5E5EA"
IOS_TEXT = "#1C1C1E"
IOS_SECONDARY_TEXT = "#6E6E73"
IOS_TERTIARY_TEXT = "#8E8E93"
IOS_BLUE = "#007AFF"
IOS_BLUE_PRESSED = "#005ECF"
IOS_GREEN = "#34C759"
IOS_RED = "#FF3B30"
IOS_ORANGE = "#FF9500"


def apply_ios_palette(app: QtWidgets.QApplication) -> None:
    """Apply a light iOS-style palette and system font."""

    families = set(QtGui.QFontDatabase.families())
    family = "Microsoft YaHei UI"
    if family not in families:
        family = "Microsoft YaHei" if "Microsoft YaHei" in families else "Segoe UI"
    font = QtGui.QFont(family)
    font.setPointSize(10)
    app.setFont(font)

    palette = QtGui.QPalette()
    palette.setColor(QtGui.QPalette.ColorRole.Window, QtGui.QColor(IOS_BACKGROUND))
    palette.setColor(QtGui.QPalette.ColorRole.WindowText, QtGui.QColor(IOS_TEXT))
    palette.setColor(QtGui.QPalette.ColorRole.Base, QtGui.QColor(IOS_CARD))
    palette.setColor(QtGui.QPalette.ColorRole.AlternateBase, QtGui.QColor(IOS_CARD_MUTED))
    palette.setColor(QtGui.QPalette.ColorRole.Text, QtGui.QColor(IOS_TEXT))
    palette.setColor(QtGui.QPalette.ColorRole.Button, QtGui.QColor(IOS_CARD))
    palette.setColor(QtGui.QPalette.ColorRole.ButtonText, QtGui.QColor(IOS_BLUE))
    palette.setColor(QtGui.QPalette.ColorRole.Highlight, QtGui.QColor(IOS_BLUE))
    palette.setColor(QtGui.QPalette.ColorRole.HighlightedText, QtGui.QColor("#FFFFFF"))
    app.setPalette(palette)


IOS_STYLE_SHEET = f"""
QMainWindow,
QWidget#appRoot {{
    background: {IOS_BACKGROUND};
    color: {IOS_TEXT};
    font-family: "Microsoft YaHei UI", "Microsoft YaHei", "Segoe UI";
}}

QStatusBar {{
    background: {IOS_BACKGROUND};
    border-top: 1px solid {IOS_SEPARATOR_SOFT};
    color: {IOS_SECONDARY_TEXT};
}}

QLabel {{
    color: {IOS_TEXT};
}}

QLabel#marketTime,
QLabel#stateLabel,
QLabel#chartSummary {{
    color: {IOS_SECONDARY_TEXT};
    font-size: 12px;
}}

QLabel#healthBanner {{
    border: 1px solid rgba(52, 199, 89, 0.40);
    border-radius: 8px;
    padding: 6px 12px;
    background: rgba(52, 199, 89, 0.12);
    color: #176C2E;
    font-weight: 600;
}}

QLabel#healthBanner[blocked="true"] {{
    background: rgba(255, 59, 48, 0.12);
    color: #8E120B;
    border-color: rgba(255, 59, 48, 0.44);
}}

QGroupBox {{
    background: {IOS_CARD};
    border: 1px solid {IOS_SEPARATOR_SOFT};
    border-radius: 8px;
    margin-top: 18px;
    padding: 14px 10px 10px 10px;
    font-weight: 700;
    color: {IOS_TEXT};
}}

QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 10px;
    top: 0px;
    padding: 0 4px;
    color: {IOS_SECONDARY_TEXT};
    font-size: 12px;
}}

QLineEdit {{
    background: {IOS_CARD};
    border: 1px solid {IOS_SEPARATOR_SOFT};
    border-radius: 8px;
    min-height: 28px;
    padding: 5px 12px;
    selection-background-color: {IOS_BLUE};
}}

QLineEdit:focus {{
    border: 1px solid {IOS_BLUE};
}}

QListWidget,
QTextBrowser {{
    background: {IOS_CARD};
    border: 1px solid {IOS_SEPARATOR_SOFT};
    border-radius: 8px;
    padding: 4px;
    color: {IOS_TEXT};
    selection-background-color: rgba(0, 122, 255, 0.14);
    selection-color: {IOS_TEXT};
}}

QListWidget::item {{
    min-height: 28px;
    border-radius: 6px;
    padding: 5px 8px;
}}

QListWidget::item:selected,
QListWidget::item:hover {{
    background: rgba(0, 122, 255, 0.12);
    color: {IOS_TEXT};
}}

QTabWidget::pane {{
    border: 1px solid {IOS_SEPARATOR_SOFT};
    border-radius: 8px;
    background: {IOS_CARD};
    top: -1px;
}}

QTabBar::tab {{
    background: #E9E9EE;
    color: {IOS_SECONDARY_TEXT};
    border: 1px solid #E0E0E6;
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
    background: {IOS_CARD};
    color: {IOS_TEXT};
    border-color: {IOS_SEPARATOR};
    font-weight: 700;
}}

QComboBox {{
    background: {IOS_CARD};
    border: 1px solid {IOS_SEPARATOR_SOFT};
    border-radius: 8px;
    padding: 5px 28px 5px 10px;
    min-height: 26px;
    color: {IOS_TEXT};
}}

QComboBox:focus {{
    border-color: {IOS_BLUE};
}}

QComboBox::drop-down {{
    width: 24px;
    border: 0;
}}

QCheckBox {{
    color: {IOS_SECONDARY_TEXT};
    spacing: 6px;
}}

QCheckBox::indicator {{
    width: 18px;
    height: 18px;
    border-radius: 8px;
    border: 1px solid {IOS_SEPARATOR};
    background: {IOS_CARD};
}}

QCheckBox::indicator:checked {{
    background: {IOS_BLUE};
    border: 1px solid {IOS_BLUE};
}}

QToolButton {{
    background: {IOS_CARD};
    border: 1px solid {IOS_SEPARATOR_SOFT};
    border-radius: 8px;
    min-width: 30px;
    min-height: 30px;
    padding: 2px;
}}

QToolButton:hover {{
    background: #F7F7FA;
    border-color: {IOS_SEPARATOR};
}}

QToolButton:pressed {{
    background: #E9E9EE;
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


__all__ = [
    "IOS_BACKGROUND",
    "IOS_BLUE",
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
    "apply_ios_palette",
]
