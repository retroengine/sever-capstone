"""Colours, type and the stylesheet. One dark theme, built for a projector and a laptop screen."""

import colorsys

from PySide6.QtGui import QColor, QFont

BG = "#0e1016"
PANEL = "#161922"
PANEL_2 = "#1d2130"
LINE = "#2a2f40"
TEXT = "#e7e9f0"
MUTED = "#8c92a6"
ACCENT = "#7c9cff"
OK = "#3ecf8e"
BAD = "#ff5d6c"
WARN = "#f5b14c"
YOURS = "#ffffff"
YOURS_RING = "#ffd166"
HOLDING = "#9aa0b4"

FAMILY = "Ubuntu Sans"
MONO = "Ubuntu Sans Mono"


def font(size: int = 11, weight: QFont.Weight = QFont.Weight.Normal, mono: bool = False) -> QFont:
    f = QFont(MONO if mono else FAMILY)
    f.setFamilies([MONO if mono else FAMILY, "DejaVu Sans Mono" if mono else "DejaVu Sans"])
    f.setPointSize(size)
    f.setWeight(weight)
    return f


def rgba(colour: str, alpha: int) -> str:
    """``#rrggbb`` with an alpha, as Qt style sheets want it (they read 8-digit hex as ARGB)."""
    c = QColor(colour)
    return f"rgba({c.red()}, {c.green()}, {c.blue()}, {alpha})"


def group_colour(index: int, spawned: bool) -> QColor:
    """Hues spread by the golden angle so neighbouring group numbers look different; spawned
    groups a little lighter and less saturated."""
    h = (index * 0.618033988749895) % 1.0
    s, v = (0.55, 0.95) if spawned else (0.70, 0.92)
    r, g, b = colorsys.hsv_to_rgb(h, s, v)
    return QColor(int(r * 255), int(g * 255), int(b * 255))


STYLE = f"""
* {{ color: {TEXT}; font-family: "{FAMILY}", "DejaVu Sans"; font-size: 11pt; }}
QMainWindow, QWidget#root {{ background: {BG}; }}
QWidget {{ background: transparent; }}
QFrame#card {{ background: {PANEL}; border: 1px solid {LINE}; border-radius: 12px; }}
QFrame#card2 {{ background: {PANEL_2}; border: 1px solid {LINE}; border-radius: 10px; }}
QFrame#hover {{ background: rgba(22,25,34,240); border: 1px solid {LINE}; border-radius: 12px; }}
QFrame#toast {{ background: {PANEL_2}; border: 1px solid {ACCENT}; border-radius: 12px; }}
QFrame#story {{ background: #1a2140; border: 1px solid {ACCENT}; border-radius: 12px; }}
QLabel#h1 {{ font-size: 26pt; font-weight: 700; }}
QLabel#h2 {{ font-size: 16pt; font-weight: 650; }}
QLabel#h3 {{ font-size: 12.5pt; font-weight: 650; }}
QLabel#muted {{ color: {MUTED}; }}
QLabel#big {{ font-size: 30pt; font-weight: 700; }}
QLabel#mono {{ font-family: "{MONO}", "DejaVu Sans Mono"; font-size: 10pt; }}
QPushButton {{ background: {PANEL_2}; border: 1px solid {LINE}; border-radius: 9px;
    padding: 7px 14px; }}
QPushButton:hover {{ border-color: {ACCENT}; }}
QPushButton:pressed {{ background: {LINE}; }}
QPushButton:disabled {{ color: {MUTED}; border-color: {PANEL_2}; }}
QPushButton#primary {{ background: {ACCENT}; color: #0b0d14; border: none; font-weight: 650; }}
QPushButton#primary:hover {{ background: #9bb3ff; }}
QPushButton#danger {{ background: #3a1d24; border: 1px solid {BAD}; color: #ffd6da; }}
QPushButton#nav {{ background: transparent; border: none; border-radius: 8px; text-align: left;
    padding: 9px 12px; color: {MUTED}; font-size: 11.5pt; }}
QPushButton#nav:hover {{ color: {TEXT}; background: {PANEL}; }}
QPushButton#nav:checked {{ color: {TEXT}; background: {PANEL_2}; font-weight: 650; }}
QPushButton#show {{ padding: 2px 8px; border-radius: 6px; font-size: 9.5pt; }}
QLineEdit, QPlainTextEdit, QTextEdit, QComboBox, QSpinBox {{ background: {PANEL_2};
    border: 1px solid {LINE}; border-radius: 8px; padding: 6px 8px;
    selection-background-color: {ACCENT}; }}
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus {{ border-color: {ACCENT}; }}
QComboBox QAbstractItemView {{ background: {PANEL_2}; border: 1px solid {LINE}; }}
QScrollArea {{ border: none; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {LINE}; border-radius: 4px; min-height: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
QTableWidget, QListWidget {{ background: {PANEL}; border: 1px solid {LINE}; border-radius: 10px;
    gridline-color: {LINE}; alternate-background-color: {PANEL_2}; }}
QHeaderView::section {{ background: {PANEL_2}; color: {MUTED}; border: none; padding: 6px; }}
QTableWidget::item:selected, QListWidget::item:selected {{ background: #2a3561; }}
QProgressBar {{ background: {PANEL_2}; border: 1px solid {LINE}; border-radius: 6px; height: 10px;
    text-align: center; font-size: 9pt; }}
QProgressBar::chunk {{ background: {ACCENT}; border-radius: 6px; }}
QToolTip {{ background: {PANEL_2}; color: {TEXT}; border: 1px solid {LINE}; padding: 6px; }}
"""
