"""Small pieces every tab uses: text, cards, tiles, banners, chips, bars and tables.

Anything that shows bank text goes through text() or a table cell, which never read it as
HTML. Qt would otherwise show a description that looks like HTML as HTML.
"""
from __future__ import annotations

import html
from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import QPoint, QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLayout,
    QPushButton,
    QSizePolicy,
    QStyledItemDelegate,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from . import icons, theme

ALERT = '<path d="M12 4 3 19.5h18L12 4Z"/><path d="M12 10v4.5"/><path d="M12 17.2h.01"/>'
INFO = '<circle cx="12" cy="12" r="8.5"/><path d="M12 11v5"/><path d="M12 8h.01"/>'


def text(value: str, kind: str = "", wrap: bool = True) -> QLabel:
    """A label that only ever shows text. Qt shows anything that looks like HTML as HTML,
    and bank descriptions are whatever the bank sent, so no label is allowed to guess."""
    label = QLabel()
    label.setTextFormat(Qt.PlainText)
    label.setText(value)
    label.setWordWrap(wrap)
    label.setTextInteractionFlags(Qt.TextSelectableByMouse)
    if kind:
        label.setProperty("kind", kind)
    return label


def column(*children, spacing: int = theme.SPACE[2], margins: tuple = (0, 0, 0, 0)) -> QWidget:
    box = QWidget()
    layout = QVBoxLayout(box)
    layout.setContentsMargins(*margins)
    layout.setSpacing(spacing)
    for child in children:
        if child is not None:
            layout.addWidget(child)
    return box


def row(*children, spacing: int = theme.SPACE[2], stretch_last: bool = False) -> QWidget:
    box = QWidget()
    layout = QHBoxLayout(box)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(spacing)
    for child in children:
        if child is not None:
            layout.addWidget(child)
    if not stretch_last:
        layout.addStretch(1)
    return box


def card(*children, title: str = "", note: str = "") -> QFrame:
    frame = QFrame()
    frame.setProperty("kind", "card")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(*(theme.SPACE[5],) * 4)
    layout.setSpacing(theme.SPACE[2])
    if title:
        layout.addWidget(text(title, "h2"))
    if note:
        layout.addWidget(text(note, "dim"))
    for child in children:
        if child is not None:
            layout.addWidget(child)
    layout.addStretch(1)  # contents stay at the top when a neighbouring card is taller
    return frame


class Grid(QWidget):
    """Lays its children out in as many equal columns as fit, like the page's auto-fit grids."""

    def __init__(self, children: list[QWidget], least: int, gap: int = theme.SPACE[4], most: int = 4, top: bool = False):
        super().__init__()
        self.children_, self.least, self.gap, self.most = [c for c in children if c is not None], least, gap, most
        self.top = top  # line children up at the top, for ones of different heights
        self.grid = QGridLayout(self)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setSpacing(gap)
        self.columns = 0
        self._place(min(len(self.children_), most) or 1)

    def _place(self, columns: int) -> None:
        if columns == self.columns:
            return
        self.columns = columns
        for child in self.children_:
            self.grid.removeWidget(child)
        for i, child in enumerate(self.children_):
            self.grid.addWidget(child, i // columns, i % columns, Qt.AlignTop if self.top else Qt.Alignment())
        for c in range(self.most):
            self.grid.setColumnStretch(c, 1 if c < columns else 0)

    def resizeEvent(self, event):  # noqa: N802 - Qt's name
        fits = max(1, (event.size().width() + self.gap) // (self.least + self.gap))
        self._place(max(1, min(fits, len(self.children_), self.most)))
        super().resizeEvent(event)


def tile(key: str, value: str, sub: str = "", tone: str = "") -> QFrame:
    frame = QFrame()
    frame.setProperty("kind", "tile")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(theme.SPACE[5], theme.SPACE[4], theme.SPACE[5], theme.SPACE[4])
    layout.setSpacing(theme.SPACE[1])
    layout.addWidget(text(key, "k"))
    big = text(value, "v")
    big.setProperty("tone", tone)
    layout.addWidget(big)
    if sub:
        layout.addWidget(text(sub, "s"))
    layout.addStretch(1)
    frame.setAccessibleName(f"{key}: {value}" + (f", {sub}" if sub else ""))
    return frame


def tiles(*items) -> Grid | None:
    present = [t for t in items if t is not None]
    return Grid(present, 190) if present else None


def _icon_label(body: str, color: str, size: int = 16) -> QLabel:
    label = QLabel()
    label.setPixmap(icons.pixmap(body, color, size, label.devicePixelRatioF()))
    label.setFixedSize(size, size)
    return label


def banner(level: str, title: str, detail: str, tokens: dict[str, str]) -> QFrame:
    frame = QFrame()
    frame.setProperty("kind", "banner")
    frame.setProperty("level", "warn" if level == "warning" else "info")
    layout = QHBoxLayout(frame)
    layout.setContentsMargins(theme.SPACE[3], theme.SPACE[2], theme.SPACE[3], theme.SPACE[2])
    layout.setSpacing(theme.SPACE[2])
    ink = tokens["warn-ink" if level == "warning" else "info-ink"]
    layout.addWidget(_icon_label(ALERT if level == "warning" else INFO, ink), 0, Qt.AlignTop)
    words = column(text(title, "b"), text(detail, "banner-text"), spacing=0)
    layout.addWidget(words, 1)
    return frame


class Notices(QFrame):
    """The checks worth a warning, folded into one line until opened."""

    def __init__(self, checks: list[dict], tokens: dict[str, str]):
        super().__init__()
        self.setProperty("kind", "banner")
        self.setProperty("level", "warn")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(theme.SPACE[3], theme.SPACE[2], theme.SPACE[3], theme.SPACE[2])
        layout.setSpacing(theme.SPACE[2])
        n = len(checks)
        self.toggle = QPushButton(f"{n} thing{'s' if n != 1 else ''} to check:  {checks[0]['title']}")
        self.toggle.setProperty("kind", "banner-head")
        self.toggle.setIcon(QIcon(icons.pixmap(ALERT, tokens["warn-ink"], 16, self.devicePixelRatioF())))
        self.toggle.setCheckable(True)
        self.toggle.setAccessibleName(f"{n} things to check")
        self.list = column(*(column(text(c["title"], "b"), text(c["detail"], "banner-text"), spacing=0) for c in checks),
                           margins=(theme.SPACE[6], 0, 0, theme.SPACE[1]))
        self.list.setVisible(False)
        self.toggle.toggled.connect(self.list.setVisible)
        layout.addWidget(self.toggle)
        layout.addWidget(self.list)


def notices(checks: list[dict], tokens: dict[str, str]) -> Notices | None:
    return Notices(checks, tokens) if checks else None


class Dot(QWidget):
    def __init__(self, color: str, size: int = 8):
        super().__init__()
        self.color = QColor(color)
        self.setFixedSize(size, size)

    def paintEvent(self, _event):  # noqa: N802 - Qt's name
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        painter.setBrush(self.color)
        painter.drawEllipse(self.rect())


ICON = 24  # a table's icons: a merchant's initials, or a category's dot in the middle


def dot_icon(color: str, size: int = 8, ratio: float = 2.0) -> QIcon:
    pixels, dot = round(ICON * ratio), round(size * ratio)
    pixmap = QPixmap(pixels, pixels)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor(color))
    painter.drawEllipse((pixels - dot) // 2, (pixels - dot) // 2, dot, dot)
    painter.end()
    pixmap.setDevicePixelRatio(ratio)
    return QIcon(pixmap)


def mono_icon(name: str, color: str, size: int = ICON, ratio: float = 2.0) -> QIcon:
    """A merchant's initials in a circle of its category's color."""
    pixels = round(size * ratio)
    pixmap = QPixmap(pixels, pixels)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    fill = QColor(color)
    fill.setAlpha(36)
    painter.setPen(Qt.NoPen)
    painter.setBrush(fill)
    painter.drawEllipse(0, 0, pixels, pixels)
    font = QFont()
    font.setPixelSize(round(size * .4 * ratio))
    font.setWeight(QFont.DemiBold)
    painter.setFont(font)
    painter.setPen(QColor(color))
    initials = "".join(w[0] for w in name.split()[:2] if w).upper()
    painter.drawText(QRectF(0, 0, pixels, pixels), Qt.AlignCenter, initials)
    painter.end()
    pixmap.setDevicePixelRatio(ratio)
    return QIcon(pixmap)


class Flow(QLayout):
    """Children left to right, onto a new line when one is full, like wrapped words."""

    def __init__(self, parent=None, gap: int = theme.SPACE[3], line_gap: int = theme.SPACE[1]):
        super().__init__(parent)
        self.items, self.gap, self.line_gap = [], gap, line_gap
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item):  # noqa: N802 - Qt's name
        self.items.append(item)

    def count(self):
        return len(self.items)

    def itemAt(self, i):  # noqa: N802 - Qt's name
        return self.items[i] if 0 <= i < len(self.items) else None

    def takeAt(self, i):  # noqa: N802 - Qt's name
        return self.items.pop(i) if 0 <= i < len(self.items) else None

    def expandingDirections(self):  # noqa: N802 - Qt's name
        return Qt.Orientations()

    def hasHeightForWidth(self):  # noqa: N802 - Qt's name
        return True

    def heightForWidth(self, width):  # noqa: N802 - Qt's name
        return self._arrange(QRect(0, 0, width, 0), move=False)

    def setGeometry(self, rect):  # noqa: N802 - Qt's name
        super().setGeometry(rect)
        self._arrange(rect, move=True)

    def sizeHint(self):  # noqa: N802 - Qt's name
        return self.minimumSize()

    def minimumSize(self):  # noqa: N802 - Qt's name
        size = QSize()
        for item in self.items:
            size = size.expandedTo(item.minimumSize())
        return size

    def _arrange(self, rect: QRect, move: bool) -> int:
        x, y, line = rect.x(), rect.y(), 0
        for item in self.items:
            hint = item.sizeHint()
            if x + hint.width() > rect.right() + 1 and line:
                x, y, line = rect.x(), y + line + self.line_gap, 0
            if move:
                item.setGeometry(QRect(QPoint(x, y), hint))
            x += hint.width() + self.gap
            line = max(line, hint.height())
        return y + line - rect.y()


def legend(items: list[tuple[str, str]]) -> QWidget:
    """(name, color) pairs, wrapped onto as many lines as they need."""
    box = QWidget()
    flow = Flow(box)
    for name, color in items:
        flow.addWidget(row(Dot(color), text(name, "legend", wrap=False), spacing=theme.SPACE[1], stretch_last=True))
    return box


def chip(category: str, color: str) -> QWidget:
    return row(Dot(color), text(category, "chip", wrap=False), spacing=theme.SPACE[2])


class _Track(QWidget):
    def __init__(self, share: float, color: str, line: str):
        super().__init__()
        self.share, self.color, self.line = share, QColor(color), QColor(line)
        self.setFixedHeight(4)

    def paintEvent(self, _event):  # noqa: N802 - Qt's name
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        rect = QRectF(self.rect())
        painter.setBrush(self.line)
        painter.drawRoundedRect(rect, 2, 2)
        painter.setBrush(self.color)
        painter.drawRoundedRect(QRectF(0, 0, max(rect.width() * self.share, 2), rect.height()), 2, 2)


class HBar(QFrame):
    """One row of a bar list: a name, its share and amount, and a bar. Selecting it opens
    its transactions."""
    clicked = Signal()

    def __init__(self, name: str, value_text: str, share: float, fill: float, color: str | None, tokens: dict[str, str]):
        super().__init__()
        self.setProperty("kind", "hbar")
        self.setFocusPolicy(Qt.StrongFocus)
        self.setCursor(Qt.PointingHandCursor)
        self.setAccessibleName(f"{name}, {value_text}, {round(share * 100)}%")
        grid = QGridLayout(self)
        grid.setContentsMargins(theme.SPACE[2], theme.SPACE[2], theme.SPACE[2], theme.SPACE[2])
        grid.setHorizontalSpacing(theme.SPACE[3])
        grid.setVerticalSpacing(theme.SPACE[1])
        label = text(name, "strong", wrap=False)
        label.setTextInteractionFlags(Qt.NoTextInteraction)
        label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        label.setToolTip(html.escape(name))
        grid.addWidget(row(Dot(color) if color else None, label, spacing=theme.SPACE[2], stretch_last=True), 0, 0)
        pct = text(f"{round(share * 100)}%", "pct", wrap=False)
        amount = text(value_text, "strong", wrap=False)
        for part in (pct, amount):
            part.setTextInteractionFlags(Qt.NoTextInteraction)
        grid.addWidget(row(pct, amount, spacing=theme.SPACE[2], stretch_last=True), 0, 1, Qt.AlignRight)
        grid.addWidget(_Track(fill, color or tokens["accent"], tokens["line"]), 1, 0, 1, 2)
        grid.setColumnStretch(0, 1)

    def mouseReleaseEvent(self, event):  # noqa: N802 - Qt's name
        if event.button() == Qt.LeftButton and self.rect().contains(event.position().toPoint()):
            self.clicked.emit()
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event):  # noqa: N802 - Qt's name
        if event.key() in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space):
            self.clicked.emit()
            return
        super().keyPressEvent(event)


def hbars(items: list[tuple[str, int, str | None, Callable[[], None]]], fmt: Callable[[int], str],
          tokens: dict[str, str]) -> QWidget:
    """(name, value, color or None, on select) for each bar, largest first."""
    top = max([v for _, v, _, _ in items] + [1])
    total = sum(v for _, v, _, _ in items) or 1
    bars = []
    for name, value, color, chosen in items:
        bar = HBar(name, fmt(value), value / total, max(value / top, .005), color, tokens)
        bar.clicked.connect(chosen)
        bars.append(bar)
    return column(*bars, spacing=0)


@dataclass
class Cell:
    text: str
    right: bool = False  # numbers line up on the right
    tone: str = ""  # pos, neg, dim, up or down
    icon: QIcon | None = None
    tip: str = ""
    bold: bool = False
    background: QColor | None = None


class _Shade(QStyledItemDelegate):
    """Paints a cell's own background, which a style sheet's item rules would otherwise hide."""

    def paint(self, painter, option, index):
        shade = index.data(Qt.BackgroundRole)
        if shade is not None:
            painter.fillRect(option.rect, shade)
        super().paint(painter, option, index)


class Table(QTableWidget):
    """A read-only table as tall as its rows, so the tab scrolls rather than the table.
    Cells are always plain text. Selecting a row, by click or Enter, calls on_row."""

    def __init__(self, headers: list[str], rows: list[list[Cell]], tokens: dict[str, str],
                 on_row: Callable[[int], None] | None = None, on_cell: Callable[[int, int], None] | None = None,
                 numeric: set[int] | None = None, stretch: int = -1):
        super().__init__(len(rows), len(headers))
        self.tokens, self.on_row, self.on_cell = tokens, on_row, on_cell
        self.setProperty("kind", "table")
        self.setProperty("clickable", bool(on_row or on_cell))
        self.setItemDelegate(_Shade(self))
        self.setHorizontalHeaderLabels(headers)
        self.verticalHeader().hide()
        self.setShowGrid(False)
        self.setWordWrap(False)
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setSelectionMode(QAbstractItemView.SingleSelection if on_row else QAbstractItemView.NoSelection)
        self.setFocusPolicy(Qt.StrongFocus if on_row or on_cell else Qt.NoFocus)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setIconSize(QSize(ICON, ICON))
        header = self.horizontalHeader()
        header.setHighlightSections(False)
        header.setSectionResizeMode(QHeaderView.ResizeToContents)
        # One column takes the spare width so the table fills its card: the last by default.
        header.setStretchLastSection(stretch == -1)
        if stretch >= 0:
            header.setSectionResizeMode(stretch, QHeaderView.Stretch)
        header.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        for c in numeric or set():
            item = self.horizontalHeaderItem(c)
            item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
        colors = {"pos": tokens["good"], "neg": tokens["bad"], "dim": tokens["muted"], "up": tokens["bad"],
                  "down": tokens["good"]}
        for r, cells in enumerate(rows):
            for c, cell in enumerate(cells):
                item = QTableWidgetItem(cell.text)
                item.setTextAlignment((Qt.AlignRight if cell.right else Qt.AlignLeft) | Qt.AlignVCenter)
                if cell.tone in colors:
                    item.setForeground(QColor(colors[cell.tone]))
                if cell.icon:
                    item.setIcon(cell.icon)
                if cell.tip:
                    item.setToolTip(html.escape(cell.tip))
                if cell.bold:
                    font = item.font()
                    font.setWeight(QFont.DemiBold)
                    item.setFont(font)
                if cell.background is not None:
                    item.setBackground(cell.background)
                self.setItem(r, c, item)
        if on_row or on_cell:
            self.setCursor(Qt.PointingHandCursor)
            self.cellClicked.connect(self._chosen)
            self.cellActivated.connect(self._chosen)
        self.verticalHeader().setDefaultSectionSize(40)
        self.fit()

    def _chosen(self, r: int, c: int) -> None:
        if self.on_cell:
            self.on_cell(r, c)
        elif self.on_row:
            self.on_row(r)

    def fit(self) -> None:
        height = self.horizontalHeader().sizeHint().height() + sum(self.rowHeight(r) for r in range(self.rowCount()))
        bar = self.horizontalScrollBar().sizeHint().height() if self.horizontalScrollBar().isVisible() else 0
        self.setFixedHeight(height + 2 * self.frameWidth() + bar)


def empty(words: str) -> QLabel:
    label = text(words, "empty")
    label.setAlignment(Qt.AlignCenter)
    return label


def check(label: str, on: bool, changed: Callable[[bool], None]) -> QWidget:
    from PySide6.QtWidgets import QCheckBox
    box = QCheckBox(label)
    box.setChecked(on)
    box.toggled.connect(changed)
    return box
