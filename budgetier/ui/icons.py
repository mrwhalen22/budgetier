"""The window's icons: line drawings on a 24 pixel grid, colored to suit the theme."""
from __future__ import annotations

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QIcon, QImage, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

TABS = {
    "Overview": '<rect x="3.5" y="3.5" width="7" height="8" rx="1.5"/><rect x="13.5" y="3.5" width="7" height="5" rx="1.5"/>'
                '<rect x="13.5" y="11.5" width="7" height="9" rx="1.5"/><rect x="3.5" y="14.5" width="7" height="6" rx="1.5"/>',
    "Spending": '<circle cx="12" cy="12" r="8.5"/><path d="M12 3.5V12l6 6"/>',
    "Budgets": '<circle cx="12" cy="12" r="8.5"/><circle cx="12" cy="12" r="4.5"/><path d="M12 12h.01"/>',
    "Recurring": '<path d="M4 11a8 8 0 0 1 13.7-5.2L20 8"/><path d="M20 3.5V8h-4.5"/><path d="M20 13a8 8 0 0 1-13.7 5.2L4 16"/>'
                 '<path d="M4 20.5V16h4.5"/>',
    "Largest": '<path d="M4 20h16"/><path d="M7 16V10"/><path d="M12 16V5"/><path d="M17 16v-3"/>',
    "Savings": '<path d="M3.5 17 9.5 11l4 4 7-8"/><path d="M15.5 7h5v5"/>',
    "Investments": '<ellipse cx="12" cy="6" rx="7" ry="2.5"/><path d="M5 6v6c0 1.4 3.1 2.5 7 2.5s7-1.1 7-2.5V6"/>'
                   '<path d="M5 12v6c0 1.4 3.1 2.5 7 2.5s7-1.1 7-2.5v-6"/>',
    "Net worth": '<path d="M12 3.5v17"/><path d="M5 7.5h14"/><path d="M5 7.5 2.5 14a3 3 0 0 0 5 0z"/>'
                 '<path d="M19 7.5 16.5 14a3 3 0 0 0 5 0z"/><path d="M8.5 20.5h7"/>',
    "Year in review": '<rect x="3.5" y="5" width="17" height="15.5" rx="2"/><path d="M3.5 10h17"/><path d="M8 3v4"/>'
                      '<path d="M16 3v4"/><path d="M8 14h3"/><path d="M8 17h6"/>',
    "Transactions": '<path d="M8 6h12"/><path d="M8 12h12"/><path d="M8 18h12"/><path d="M4 6h.01"/><path d="M4 12h.01"/>'
                    '<path d="M4 18h.01"/>',
    "Rules": '<path d="M4 7h10"/><path d="M18 7h2"/><circle cx="16" cy="7" r="2"/><path d="M4 17h2"/><path d="M10 17h10"/>'
             '<circle cx="8" cy="17" r="2"/>',
    "Accounts": '<rect x="3" y="5.5" width="18" height="13" rx="2.5"/><path d="M3 10h18"/><path d="M7 15h3"/>',
    "Help": '<circle cx="12" cy="12" r="8.5"/><path d="M9.5 9.5a2.5 2.5 0 1 1 3.6 2.2c-.7.4-1.1.9-1.1 1.8"/>'
            '<path d="M12 16.8h.01"/>',
}
SUN = ('<circle cx="12" cy="12" r="4"/><path d="M12 3v2M12 19v2M3 12h2M19 12h2"/>'
       '<path d="M5.6 5.6 7 7M17 17l1.4 1.4M5.6 18.4 7 17M17 7l1.4-1.4"/>')
# The brand mark is filled, not drawn in lines.
BRAND = '<rect x="3" y="12" width="4.5" height="9" rx="1.5"/><rect x="9.75" y="7" width="4.5" height="14" rx="1.5"/>' \
        '<rect x="16.5" y="3" width="4.5" height="18" rx="1.5"/>'


def svg(body: str, color: str, filled: bool = False) -> str:
    paint = f'fill="{color}"' if filled else \
        f'fill="none" stroke="{color}" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"'
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" {paint}>{body}</svg>'


def pixmap(body: str, color: str, size: int, ratio: float = 1.0, filled: bool = False) -> QPixmap:
    """Drawn at the screen's own density, so lines stay sharp on high resolution screens."""
    pixels = max(1, round(size * ratio))
    image = QImage(pixels, pixels, QImage.Format_ARGB32_Premultiplied)
    image.fill(Qt.transparent)
    painter = QPainter(image)
    QSvgRenderer(QByteArray(svg(body, color, filled).encode())).render(painter, QRectF(0, 0, pixels, pixels))
    painter.end()
    result = QPixmap.fromImage(image)
    result.setDevicePixelRatio(ratio)
    return result


def icon(body: str, color: str, size: int = 18, ratio: float = 1.0) -> QIcon:
    return QIcon(pixmap(body, color, size, ratio))


def tab_icon(name: str, normal: str, selected: str, size: int = 18, ratio: float = 1.0) -> QIcon:
    """One color normally and another when the tab is the one showing."""
    both = QIcon()
    both.addPixmap(pixmap(TABS[name], normal, size, ratio), QIcon.Normal, QIcon.Off)
    both.addPixmap(pixmap(TABS[name], selected, size, ratio), QIcon.Normal, QIcon.On)
    return both
