"""Тёмная минималистичная тема с одним акцентным цветом."""

from __future__ import annotations

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

BG = "#14161a"
SURFACE = "#1c1f24"
SURFACE_2 = "#24282e"
BORDER = "#2f343c"
TEXT = "#e7e9ec"
MUTED = "#9aa2ad"
ACCENT = "#4c8dff"  # единственный акцентный цвет
ACCENT_HOVER = "#6aa0ff"
ACCENT_PRESSED = "#3a76e0"
DANGER = "#ef5f5f"  # только для ошибок и кнопки «Стоп»
DISABLED = "#5d636c"


STYLESHEET = f"""
QWidget {{
    color: {TEXT};
    font-size: 13px;
}}
QMainWindow, #root {{
    background: {BG};
}}
QScrollArea, #scrollContent {{
    background: {BG};
    border: none;
}}
QScrollBar:vertical {{
    background: transparent;
    width: 10px;
    margin: 2px;
}}
QScrollBar::handle:vertical {{
    background: {BORDER};
    border-radius: 4px;
    min-height: 24px;
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
}}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
    background: transparent;
}}

#card {{
    background: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 10px;
}}
#cardTitle {{
    font-size: 12px;
    font-weight: 600;
    color: {MUTED};
    letter-spacing: 0.5px;
}}
#appTitle {{
    font-size: 17px;
    font-weight: 700;
}}
#muted, #hint {{
    color: {MUTED};
}}
#hint {{
    font-size: 12px;
}}
#error {{
    color: {DANGER};
    font-size: 12px;
}}
#warning {{
    color: {MUTED};
    font-size: 12px;
}}
#summary {{
    color: {MUTED};
}}
#stat {{
    font-size: 13px;
}}
#statValue {{
    font-size: 15px;
    font-weight: 600;
}}

#statusPill {{
    border-radius: 11px;
    padding: 3px 10px;
    font-size: 12px;
    font-weight: 600;
    border: 1px solid {BORDER};
    background: {SURFACE_2};
    color: {MUTED};
}}
#statusPill[tone="active"] {{
    border-color: {ACCENT};
    color: {ACCENT_HOVER};
}}
#statusPill[tone="danger"] {{
    border-color: {DANGER};
    color: {DANGER};
}}

QLineEdit {{
    background: {SURFACE_2};
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 4px 6px;
    selection-background-color: {ACCENT};
    min-height: 20px;
}}
QLineEdit:focus {{
    border-color: {ACCENT};
}}
QLineEdit[invalid="true"] {{
    border-color: {DANGER};
}}
QLineEdit:disabled {{
    color: {DISABLED};
}}

QPushButton {{
    background: {SURFACE_2};
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 5px 10px;
    min-height: 20px;
}}
QPushButton:hover {{
    border-color: {MUTED};
}}
QPushButton:pressed {{
    background: {BORDER};
}}
QPushButton:disabled {{
    color: {DISABLED};
    border-color: {SURFACE_2};
}}
QPushButton:focus {{
    border-color: {ACCENT};
}}
QPushButton#stepButton {{
    padding: 0;
    min-width: 26px;
    max-width: 26px;
    font-size: 15px;
}}
QPushButton#segment {{
    border-radius: 0;
    padding: 5px 8px;
}}
QPushButton#segment[pos="first"] {{
    border-top-left-radius: 6px;
    border-bottom-left-radius: 6px;
}}
QPushButton#segment[pos="last"] {{
    border-top-right-radius: 6px;
    border-bottom-right-radius: 6px;
}}
QPushButton#segment:checked, QPushButton#preset:checked {{
    background: {ACCENT};
    border-color: {ACCENT};
    color: white;
}}
QPushButton#segment:checked:disabled, QPushButton#preset:checked:disabled {{
    background: {BORDER};
    border-color: {BORDER};
    color: {MUTED};
}}
QPushButton#preset {{
    padding: 3px 0;
    min-width: 40px;
}}

QPushButton#startButton {{
    background: {ACCENT};
    border: none;
    border-radius: 10px;
    color: white;
    font-size: 17px;
    font-weight: 700;
    min-height: 50px;
}}
QPushButton#startButton:hover {{
    background: {ACCENT_HOVER};
}}
QPushButton#startButton:pressed {{
    background: {ACCENT_PRESSED};
}}
QPushButton#startButton[mode="stop"] {{
    background: {DANGER};
}}
QPushButton#startButton[mode="stop"]:hover {{
    background: #f37a7a;
}}
QPushButton#startButton:disabled {{
    background: {SURFACE_2};
    color: {DISABLED};
}}

#keycap {{
    background: {SURFACE_2};
    border: 1px solid {BORDER};
    border-bottom-width: 2px;
    border-radius: 6px;
    padding: 4px 8px;
    font-weight: 600;
}}
#keycap[recording="true"] {{
    border-color: {ACCENT};
    color: {ACCENT_HOVER};
}}

QRadioButton {{
    spacing: 6px;
}}
QRadioButton::indicator {{
    width: 14px;
    height: 14px;
    border-radius: 8px;
    border: 1px solid {MUTED};
    background: {SURFACE_2};
}}
QRadioButton::indicator:checked {{
    border: 1px solid {ACCENT};
    background: qradialgradient(cx: 0.5, cy: 0.5, radius: 0.5, fx: 0.5, fy: 0.5,
        stop: 0 white, stop: 0.4 white, stop: 0.5 {ACCENT}, stop: 1 {ACCENT});
}}
QRadioButton::indicator:checked:disabled {{
    border-color: {DISABLED};
    background: qradialgradient(cx: 0.5, cy: 0.5, radius: 0.5, fx: 0.5, fy: 0.5,
        stop: 0 {MUTED}, stop: 0.4 {MUTED}, stop: 0.5 {SURFACE_2}, stop: 1 {SURFACE_2});
}}
QRadioButton:disabled {{
    color: {DISABLED};
}}

QToolTip {{
    background: {SURFACE_2};
    color: {TEXT};
    border: 1px solid {BORDER};
}}
"""


def apply_theme(app: QApplication) -> None:
    app.setStyle("Fusion")
    palette = QPalette()
    roles = {
        QPalette.ColorRole.Window: BG,
        QPalette.ColorRole.WindowText: TEXT,
        QPalette.ColorRole.Base: SURFACE_2,
        QPalette.ColorRole.AlternateBase: SURFACE,
        QPalette.ColorRole.Text: TEXT,
        QPalette.ColorRole.Button: SURFACE_2,
        QPalette.ColorRole.ButtonText: TEXT,
        QPalette.ColorRole.Highlight: ACCENT,
        QPalette.ColorRole.HighlightedText: "#ffffff",
        QPalette.ColorRole.ToolTipBase: SURFACE_2,
        QPalette.ColorRole.ToolTipText: TEXT,
        QPalette.ColorRole.PlaceholderText: MUTED,
        QPalette.ColorRole.Link: ACCENT,
    }
    for role, color in roles.items():
        palette.setColor(role, QColor(color))
    for role in (QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText, QPalette.ColorRole.WindowText):
        palette.setColor(QPalette.ColorGroup.Disabled, role, QColor(DISABLED))
    app.setPalette(palette)
    app.setStyleSheet(STYLESHEET)
