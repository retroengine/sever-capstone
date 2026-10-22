"""Colours, type and the style sheet, on an 8 px grid.

Light by default (``SEVER_STUDIO_THEME=dark`` for the dark palette). Type scale (points, times the
presenter's text size): 22 title, 15 heading, 11 body, 9.5 small.
"""

import colorsys
import os

from PySide6.QtGui import QColor, QFont

PALETTES = {
    "light": {
        "BG": "#f5f6fa",
        "SURFACE": "#ffffff",
        "SURFACE_2": "#f0f2f7",
        "LINE": "#dde1ea",
        "TEXT": "#1d2331",
        "MUTED": "#687087",
        "ACCENT": "#3b5bdb",
        "ACCENT_HOVER": "#2f4bc2",
        "ON_ACCENT": "#ffffff",
        "OK": "#138a5a",
        "BAD": "#d6334a",
        "WARN": "#b26a00",
        "YOURS": "#ffb703",
        "YOURS_RING": "#1d2331",
        "HOLDING": "#8a93a6",
        "SPAWNED": "#7c4dcc",
        "TOUR": "#eef2ff",
        "SHADOW": "#1d2331",
    },
    "dark": {
        "BG": "#0d0f15",
        "SURFACE": "#151822",
        "SURFACE_2": "#1c2030",
        "LINE": "#2a3042",
        "TEXT": "#e8eaf1",
        "MUTED": "#8a90a4",
        "ACCENT": "#7c9cff",
        "ACCENT_HOVER": "#9bb3ff",
        "ON_ACCENT": "#0b0d14",
        "OK": "#3ecf8e",
        "BAD": "#ff5d6c",
        "WARN": "#f5b14c",
        "YOURS": "#ffffff",
        "YOURS_RING": "#ffd166",
        "HOLDING": "#9aa0b4",
        "SPAWNED": "#c9a2ff",
        "TOUR": "#1a2140",
        "SHADOW": "#000000",
    },
}
MODE = "dark" if os.environ.get("SEVER_STUDIO_THEME") == "dark" else "light"
_P = PALETTES[MODE]
BG, SURFACE, SURFACE_2, LINE = _P["BG"], _P["SURFACE"], _P["SURFACE_2"], _P["LINE"]
TEXT, MUTED, ACCENT, ACCENT_HOVER, ON_ACCENT = (
    _P["TEXT"],
    _P["MUTED"],
    _P["ACCENT"],
    _P["ACCENT_HOVER"],
    _P["ON_ACCENT"],
)
OK, BAD, WARN = _P["OK"], _P["BAD"], _P["WARN"]
YOURS, YOURS_RING, HOLDING, SPAWNED, TOUR, SHADOW = (
    _P["YOURS"],
    _P["YOURS_RING"],
    _P["HOLDING"],
    _P["SPAWNED"],
    _P["TOUR"],
    _P["SHADOW"],
)
LIGHT = MODE == "light"

FAMILY = "Ubuntu Sans"
MONO = "Ubuntu Sans Mono"

TITLE, HEADING, BODY, SMALL = 22.0, 15.0, 11.0, 9.5

#: The presenter's text size (A− / A+), and the colour-blind-safe palette switch.
scale = 1.0
safe_palette = False

#: Okabe and Ito's eight colours, which stay distinct for the common colour-vision deficiencies.
OKABE_ITO = ["#e69f00", "#56b4e9", "#009e73", "#f0e442", "#0072b2", "#d55e00", "#cc79a7", "#000000"]


def pt(size: float) -> float:
    return round(size * scale, 1)


def font(
    size: float = BODY, weight: QFont.Weight = QFont.Weight.Normal, mono: bool = False
) -> QFont:
    f = QFont()
    f.setFamilies([MONO, "DejaVu Sans Mono"] if mono else [FAMILY, "DejaVu Sans"])
    f.setPointSizeF(pt(size))
    f.setWeight(weight)
    return f


def rgba(colour: str, alpha: int) -> str:
    """``#rrggbb`` with an alpha, as style sheets want it (they read 8-digit hex as ARGB)."""
    c = QColor(colour)
    return f"rgba({c.red()}, {c.green()}, {c.blue()}, {alpha})"


def group_colour(index: int, spawned: bool) -> QColor:
    """Hues spread by the golden angle, so neighbouring group numbers look different; spawned
    groups lighter. With the safe palette, the eight Okabe–Ito colours in turn."""
    if safe_palette:
        c = QColor(OKABE_ITO[index % len(OKABE_ITO)])
        return (c.darker(115) if LIGHT else c.lighter(125)) if spawned else c
    h = (index * 0.618033988749895) % 1.0
    if LIGHT:
        s, v = (0.70, 0.78) if spawned else (0.80, 0.72)
    else:
        s, v = (0.55, 0.95) if spawned else (0.70, 0.92)
    r, g, b = colorsys.hsv_to_rgb(h, s, v)
    return QColor(int(r * 255), int(g * 255), int(b * 255))


def stylesheet() -> str:
    return f"""
* {{ color: {TEXT}; font-family: "{FAMILY}", "DejaVu Sans"; font-size: {pt(BODY)}pt; }}
QMainWindow, QWidget#root {{ background: {BG}; }}
QWidget {{ background: transparent; }}
QToolTip {{ background: {SURFACE_2}; color: {TEXT}; border: 1px solid {LINE}; padding: 6px;
    font-size: {pt(SMALL)}pt; }}
QFrame#card {{ background: {SURFACE}; border: 1px solid {LINE}; border-radius: 12px; }}
QFrame#card2 {{ background: {SURFACE_2}; border: 1px solid {LINE}; border-radius: 10px; }}
QFrame#float {{ background: {rgba(SURFACE, 238)}; border: 1px solid {LINE}; border-radius: 14px; }}
QFrame#popover {{ background: {SURFACE_2}; border: 1px solid {ACCENT}; border-radius: 12px; }}
QFrame#rail {{ background: {SURFACE}; border-right: 1px solid {LINE}; }}
QFrame#topbar {{ background: {BG}; border-bottom: 1px solid {LINE}; }}
QFrame#drawer {{ background: {SURFACE}; border-left: 1px solid {LINE}; }}
QFrame#tour {{ background: {rgba(TOUR, 248)}; border: 1px solid {ACCENT};
    border-radius: 14px; }}
QLabel#title {{ font-size: {pt(TITLE)}pt; font-weight: 700; }}
QLabel#heading {{ font-size: {pt(HEADING)}pt; font-weight: 650; }}
QLabel#strong {{ font-weight: 650; }}
QLabel#muted {{ color: {MUTED}; }}
QLabel#small {{ color: {MUTED}; font-size: {pt(SMALL)}pt; }}
QLabel#big {{ font-size: {pt(TITLE + 4)}pt; font-weight: 700; }}
QLabel#mono {{ font-family: "{MONO}", "DejaVu Sans Mono"; font-size: {pt(SMALL)}pt; }}
QPushButton {{ background: {SURFACE_2}; border: 1px solid {LINE}; border-radius: 9px;
    padding: 6px 12px; }}
QPushButton:hover {{ border-color: {ACCENT}; }}
QPushButton:pressed {{ background: {LINE}; }}
QPushButton:disabled {{ color: {MUTED}; border-color: {SURFACE_2}; }}
QPushButton#primary {{ background: {ACCENT}; color: {ON_ACCENT}; border: none; font-weight: 650; }}
QPushButton#primary:hover {{ background: {ACCENT_HOVER}; }}
QPushButton#danger {{ background: {rgba(BAD, 24)}; border: 1px solid {rgba(BAD, 160)};
    color: {BAD}; }}
QPushButton#ghost {{ background: transparent; border: none; color: {MUTED}; padding: 4px 8px; }}
QPushButton#ghost:hover {{ color: {TEXT}; }}
QPushButton#rail {{ background: transparent; border: none; border-radius: 10px; padding: 8px; }}
QPushButton#rail:hover {{ background: {SURFACE_2}; }}
QPushButton#rail:checked {{ background: {rgba(ACCENT, 50)}; }}
QPushButton#pill {{ background: {SURFACE_2}; border: 1px solid {LINE}; border-radius: 14px;
    padding: 4px 12px; font-weight: 600; }}
QPushButton#pill:hover {{ border-color: {ACCENT}; }}
QPushButton#fab {{ background: {ACCENT}; color: {ON_ACCENT}; border: none; border-radius: 20px;
    padding: 9px 16px; font-weight: 700; }}
QLineEdit, QPlainTextEdit, QSpinBox {{ background: {SURFACE_2}; border: 1px solid {LINE};
    border-radius: 9px; padding: 6px 9px; selection-background-color: {ACCENT}; }}
QLineEdit:focus, QPlainTextEdit:focus {{ border-color: {ACCENT}; }}
QLineEdit#search {{ border-radius: 18px; padding: 8px 14px; background: {rgba(SURFACE_2, 245)}; }}
QTabWidget::pane {{ border: none; }}
QTabBar::tab {{ background: transparent; color: {MUTED}; padding: 8px 16px; border: none;
    border-bottom: 2px solid transparent; font-weight: 600; }}
QTabBar::tab:selected {{ color: {TEXT}; border-bottom: 2px solid {ACCENT}; }}
QTabBar::tab:hover {{ color: {TEXT}; }}
QScrollArea {{ border: none; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {LINE}; border-radius: 4px; min-height: 30px; }}
QScrollBar:horizontal {{ height: 0; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QListWidget, QTableWidget {{ background: {SURFACE}; border: 1px solid {LINE}; border-radius: 10px;
    alternate-background-color: {SURFACE_2}; gridline-color: {LINE}; }}
QListWidget::item {{ padding: 6px 8px; border-radius: 6px; }}
QListWidget::item:selected, QTableWidget::item:selected {{ background: {rgba(ACCENT, 70)}; }}
QHeaderView::section {{ background: {SURFACE_2}; color: {MUTED}; border: none; padding: 6px; }}
QProgressBar {{ background: {SURFACE_2}; border: none; border-radius: 4px; height: 8px; }}
QProgressBar::chunk {{ background: {ACCENT}; border-radius: 4px; }}
QPlainTextEdit#console {{ font-family: "{MONO}", "DejaVu Sans Mono"; font-size: {pt(SMALL)}pt; }}
"""
