"""Bar and line charts by month, drawn by hand.

Hover a month, or focus the chart and use the left and right arrows, to read its values.
"""
from __future__ import annotations

import html
import math
from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QToolTip, QWidget

from . import fmt

LEFT, RIGHT, TOP, BOTTOM = 40, 2, 8, 22
LABEL_EVERY = 62  # pixels each month label needs


@dataclass
class Series:
    name: str
    values: list[int | None]  # cents per month; None leaves a gap in a line
    color: str = ""
    color_for: Callable[[int], str] | None = None  # a bar's color by its value

    def paint(self, value: int) -> str:
        return self.color_for(value) if self.color_for else self.color


def nice_max(value: float) -> float:
    if value <= 0:
        return 1
    power = 10 ** math.floor(math.log10(value))
    n = value / power
    return (1 if n <= 1 else 2 if n <= 2 else 2.5 if n <= 2.5 else 5 if n <= 5 else 10) * power


class Chart(QWidget):
    def __init__(self, months: list[str], series: list[Series], tokens: dict[str, str], kind: str = "bars",
                 stacked: bool = False, height: int = 260, partial_month: str | None = None):
        super().__init__()
        self.months, self.series, self.tokens = months, series, tokens
        self.kind, self.stacked, self.partial_month = kind, stacked, partial_month
        self.base = height
        self.at = -1  # the month being read
        self.setMinimumHeight(height)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setAccessibleName("Chart. Use the left and right arrow keys to read each month.")
        self.setAccessibleDescription(". ".join(self.spoken(i) for i in range(len(months))))

    def sizeHint(self):  # noqa: N802 - Qt's name
        return QSize(400, self.base)

    # ---- numbers

    def values_at(self, i: int) -> list[int | None]:
        return [s.values[i] for s in self.series]

    def bounds(self) -> tuple[float, float]:
        if self.stacked:
            columns = [self.values_at(i) for i in range(len(self.months))]
            hi = max([sum(max(v or 0, 0) for v in c) for c in columns] + [0])
            lo = min([sum(min(v or 0, 0) for v in c) for c in columns] + [0])
        else:
            every = [v for s in self.series for v in s.values if v is not None]
            hi, lo = max(every + [0]), min(every + [0])
        return lo, hi

    def has_values(self) -> bool:
        return any(v is not None for s in self.series for v in s.values)

    def tip(self, i: int) -> tuple[str, list[tuple[str, str, str]]]:
        """A month's title, then (name, amount, color) rows."""
        month = self.months[i]
        title = fmt.month_name(month) + (" (so far)" if month == self.partial_month and self.kind == "bars" else "")
        shown = [s for s in self.series if s.values[i] is not None and (not self.stacked or s.values[i])]
        rows = [(s.name, fmt.money(s.values[i]), s.paint(s.values[i])) for s in shown]
        if self.kind == "bars":
            rows.reverse()
        if self.stacked:
            rows.append(("Total", fmt.money(sum(v or 0 for v in self.values_at(i))), ""))
        return title, rows

    def spoken(self, i: int) -> str:
        title, rows = self.tip(i)
        if self.stacked:
            rows = rows[-1:]
        return f"{title}: " + ", ".join(f"{name} {amount}" for name, amount, _ in rows)

    # ---- layout

    def frame(self):
        width, height = max(self.width(), 280), self.height()
        lo, hi = self.bounds()
        top = nice_max(max(hi, -lo / 2))
        tick = top / 4
        bottom = -math.ceil(-lo / tick) * tick if lo < 0 else 0
        band = (width - LEFT - RIGHT) / max(len(self.months), 1)

        def y(v: float) -> float:
            return TOP + (height - TOP - BOTTOM) * (top - v) / (top - bottom)

        def x(i: int) -> float:
            return LEFT + band * i

        return width, height, top, tick, bottom, band, x, y

    def index_at(self, px: float) -> int:
        _, _, _, _, _, band, _, _ = self.frame()
        i = int((px - LEFT) // band) if band else -1
        return i if 0 <= i < len(self.months) else -1

    # ---- drawing

    def paintEvent(self, _event):  # noqa: N802 - Qt's name
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        t = self.tokens
        if self.kind == "lines" and not self.has_values():
            painter.setPen(QColor(t["muted"]))
            painter.drawText(self.rect(), Qt.AlignCenter, "No data in this period.")
            return
        width, height, top, tick, bottom, band, x, y = self.frame()
        small = QFont(self.font())
        small.setPixelSize(11)
        painter.setFont(small)

        if 0 <= self.at < len(self.months):
            painter.fillRect(QRectF(x(self.at), TOP, band, height - TOP - BOTTOM), _qcolor(t["hover"]))
        v = bottom
        while v <= top + tick / 2:
            painter.setPen(QPen(_qcolor(t["line"] if v == 0 else t["line-soft"]), 1))
            painter.drawLine(QPointF(LEFT, y(v)), QPointF(width - RIGHT, y(v)))
            painter.setPen(QColor(t["muted"]))
            painter.drawText(QRectF(0, y(v) - 8, LEFT - 8, 16), Qt.AlignRight | Qt.AlignVCenter, fmt.short(v))
            v += tick
        every = math.ceil(len(self.months) / max(1, math.floor((width - LEFT - RIGHT) / LABEL_EVERY)))
        painter.setPen(QColor(t["muted"]))
        for i, m in enumerate(self.months):
            if i % every == 0:
                year = len(self.months) <= 6 or m.endswith("-01")
                middle = x(i) + band / 2
                painter.drawText(QRectF(middle - 60, height - BOTTOM + 4, 120, BOTTOM - 4), Qt.AlignHCenter | Qt.AlignTop,
                                 fmt.month_name(m, year))
        if self.kind == "lines":
            self._lines(painter, band, x, y)
        else:
            self._bars(painter, band, x, y)

    def _bars(self, painter: QPainter, band: float, x, y) -> None:
        inner = min(band * .72, 96)
        painter.setPen(Qt.NoPen)
        for i in range(len(self.months)):
            if self.stacked:
                up = down = 0
                w = min(inner, max(26, band * .42))
                bx = x(i) + (band - w) / 2
                for s in self.series:
                    v = s.values[i] or 0
                    if not v:
                        continue
                    a = up if v > 0 else down
                    b = a + v
                    if v > 0:
                        up = b
                    else:
                        down = b
                    h = max(abs(y(a) - y(b)) - 2, 1)
                    painter.setBrush(QColor(s.paint(v)))
                    painter.drawRoundedRect(QRectF(bx, y(max(a, b)), w, h), 2.5, 2.5)
            else:
                n = len(self.series)
                w = min((inner - 3 * (n - 1)) / n, max(15, band * .28))
                total = w * n + 3 * (n - 1)
                start = x(i) + (band - total) / 2
                for k, s in enumerate(self.series):
                    v = s.values[i] or 0
                    h = abs(y(v) - y(0))
                    if h > 0:
                        painter.setBrush(QColor(s.paint(v)))
                        radius = min(4, w / 2)
                        painter.drawRoundedRect(QRectF(start + k * (w + 3), y(max(v, 0)), w, max(h, 1)), radius, radius)

    def _lines(self, painter: QPainter, band: float, x, y) -> None:
        every = [v for s in self.series for v in s.values if v is not None]
        for s in self.series:
            path, pen_down, ends = QPainterPath(), False, []
            for i, v in enumerate(s.values):
                if v is None:
                    pen_down = False
                    continue
                point = QPointF(x(i) + band / 2, y(v))
                path.lineTo(point) if pen_down else path.moveTo(point)
                ends.append(point.x())
                pen_down = True
            color = QColor(s.color)
            if len(self.series) == 1 and len(self.months) > 1 and ends:  # a soft wash under a lone line
                base = y(max(0, min(every)))
                wash = QPainterPath(path)
                wash.lineTo(ends[-1], base)
                wash.lineTo(ends[0], base)
                wash.closeSubpath()
                gradient = QLinearGradient(0, 0, 0, self.height())
                faint, clear = QColor(color), QColor(color)
                faint.setAlphaF(.2)
                clear.setAlphaF(0)
                gradient.setColorAt(0, faint)
                gradient.setColorAt(1, clear)
                painter.fillPath(wash, QBrush(gradient))
            painter.setPen(QPen(color, 2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            painter.setBrush(Qt.NoBrush)
            painter.drawPath(path)
            painter.setPen(QPen(QColor(self.tokens["surface"]), 2))
            painter.setBrush(color)
            for i, v in enumerate(s.values):
                if v is not None and (len(self.months) <= 2 or i == len(s.values) - 1):
                    painter.drawEllipse(QPointF(x(i) + band / 2, y(v)), 4, 4)

    # ---- reading it

    def tip_html(self, i: int) -> str:
        title, rows = self.tip(i)
        lines = "".join(f"<tr><td>{f'<span style=color:{c}>&#9679;</span> ' if c else ''}{html.escape(name)}</td>"
                        f"<td align=right>&nbsp;&nbsp;{html.escape(amount)}</td></tr>" for name, amount, c in rows)
        return f"<b>{html.escape(title)}</b><table>{lines}</table>"

    def _read(self, i: int, at) -> None:
        self.at = i
        self.update()
        if i < 0:
            QToolTip.hideText()
            return
        QToolTip.showText(at, self.tip_html(i), self)

    def mouseMoveEvent(self, event):  # noqa: N802 - Qt's name
        i = self.index_at(event.position().x())
        if i != self.at:
            self._read(i, event.globalPosition().toPoint())

    def leaveEvent(self, event):  # noqa: N802 - Qt's name
        self._read(-1, None)
        super().leaveEvent(event)

    def keyPressEvent(self, event):  # noqa: N802 - Qt's name
        move = {Qt.Key_Right: 1, Qt.Key_Left: -1}.get(event.key())
        if not move or not self.months:
            return super().keyPressEvent(event)
        last = len(self.months) - 1
        i = last if self.at < 0 and move < 0 else min(max(self.at + move, 0), last)
        _, _, _, _, _, band, x, _ = self.frame()
        self._read(i, self.mapToGlobal(QPointF(x(i) + band / 2, TOP + 12).toPoint()))
        self.setAccessibleDescription(self.spoken(i))

    def focusOutEvent(self, event):  # noqa: N802 - Qt's name
        self._read(-1, None)
        super().focusOutEvent(event)


def _qcolor(css: str) -> QColor:
    """The tokens' rgba(r, g, b, .08) as a color."""
    if css.startswith("rgba("):
        r, g, b, a = (p.strip() for p in css[5:-1].split(","))
        color = QColor(int(r), int(g), int(b))
        color.setAlphaF(float(a))
        return color
    return QColor(css)
