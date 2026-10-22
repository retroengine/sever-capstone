"""One small set of line icons, drawn as SVG (24 × 24, 2 px strokes), coloured on demand."""

from functools import cache

from PySide6.QtCore import QByteArray, QRectF, QSize, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

from . import theme

PATHS = {
    "home": '<path d="M3 11l9-7 9 7"/><path d="M5 10v10h14V10"/><path d="M10 20v-6h4v6"/>',
    "map": '<circle cx="6" cy="7" r="2"/><circle cx="17" cy="6" r="2"/>'
    '<circle cx="9" cy="16" r="2"/><circle cx="18" cy="17" r="2"/>'
    '<circle cx="12" cy="10" r="1.5"/>',
    "receipt": '<path d="M6 3h12v18l-3-2-3 2-3-2-3 2z"/><path d="M9 8h6M9 12h6"/>',
    "engine": '<rect x="6" y="6" width="12" height="12" rx="2"/>'
    '<path d="M9 2v4M15 2v4M9 18v4M15 18v4M2 9h4M2 15h4M18 9h4M18 15h4"/>',
    "shield": '<path d="M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z"/>'
    '<path d="M8.5 12l2.5 2.5 4.5-5"/>',
    "search": '<circle cx="11" cy="11" r="7"/><path d="M20 20l-4-4"/>',
    "plus": '<path d="M12 5v14M5 12h14"/>',
    "trash": '<path d="M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3"/>',
    "forget": '<circle cx="9" cy="8" r="4"/><path d="M2 21c0-4 3-6 7-6s7 2 7 6"/>'
    '<path d="M17 8l5 5M22 8l-5 5"/>',
    "layers": '<path d="M12 3l9 5-9 5-9-5z"/><path d="M3 13l9 5 9-5"/>',
    "check": '<path d="M5 12l5 5 9-10"/>',
    "x": '<path d="M6 6l12 12M18 6L6 18"/>',
    "info": '<circle cx="12" cy="12" r="9"/><path d="M12 11v6"/><circle cx="12" cy="7.5" r="0.6"/>',
    "play": '<path d="M7 4l13 8-13 8z"/>',
    "list": '<path d="M9 6h11M9 12h11M9 18h11"/><path d="M4 6h1M4 12h1M4 18h1"/>',
    "left": '<path d="M15 5l-7 7 7 7"/>',
    "right": '<path d="M9 5l7 7-7 7"/>',
    "refresh": '<path d="M20 11a8 8 0 1 0-2 6"/><path d="M20 4v7h-7"/>',
    "zap": '<path d="M13 2L4 14h7l-1 8 9-12h-7z"/>',
    "disk": '<rect x="3" y="5" width="18" height="14" rx="2"/><path d="M3 13h18"/>'
    '<circle cx="17" cy="16" r="0.6"/>',
    "log": '<path d="M6 3h9l4 4v14H6z"/><path d="M15 3v4h4M9 12h7M9 16h7"/>',
    "bug": '<rect x="7" y="8" width="10" height="12" rx="5"/><path d="M12 8v12M3 13h4M17 13h4'
    'M4 7l3 3M20 7l-3 3M4 20l3-3M20 20l-3-3M9 5l1 3M15 5l-1 3"/>',
    "text": '<path d="M5 6h14M12 6v13"/>',
    "spark": '<path d="M12 2l2.4 6.6L21 11l-6.6 2.4L12 20l-2.4-6.6L3 11l6.6-2.4z"/>',
    "eye": '<path d="M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12z"/>'
    '<circle cx="12" cy="12" r="3"/>',
}


@cache
def icon(name: str, colour: str = theme.TEXT, size: int = 20) -> QIcon:
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
        f'stroke="{colour}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
        f"{PATHS[name]}</svg>"
    )
    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    ic = QIcon()
    for dpr in (1, 2):
        pm = QPixmap(QSize(size * dpr, size * dpr))
        pm.setDevicePixelRatio(dpr)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        renderer.render(p, QRectF(0, 0, size, size))
        p.end()
        ic.addPixmap(pm)
    return ic
