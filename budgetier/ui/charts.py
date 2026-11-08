"""Bar and line charts by month, drawn by hand.

Hover a month, or focus the chart and use the left and right arrows, to read its values in
a note pinned above that month. The bars grow in when a chart first shows.
"""
from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, QSize, Qt, QTimer
from PySide6.QtGui import QBrush, QColor, QFont, QFontMetrics, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget

from . import fmt, motion, theme
from .popup import SHADOW, paint_panel

LEFT, RIGHT, TOP, BOTTOM = 44, 2, 8, 22
LABEL_EVERY = 62  # pixels each month label needs
PICK = "Select a month to see just that month."  # under charts that can
STACK_GAP = 3  # a slice at least this tall gets a hairline between it and the next
grow_next = True  # whether charts made now grow in; the window turns it off for a redraw after a change


@dataclass
class Series:
    name: str
    values: list[int | None]  # cents per month; None leaves a gap in a line
    color: str = ""
    color_for: Callable[[int], str] | None = None  # a bar's color by its value

    def paint(self, value: int) -> str:
        return self.color_for(value) if self.color_for else self.color


def nice_max(value: float) -> float:
    """The round number at or above value: 1, 2, 2.5 or 5 times a power of ten."""
    if value <= 0:
        return 1
    power = 10 ** math.floor(math.log10(value))
    n = value / power
    return (1 if n <= 1 else 2 if n <= 2 else 2.5 if n <= 2.5 else 5 if n <= 5 else 10) * power


def scale(lo: float, hi: float, steps: int = 4) -> tuple[float, float, float]:
    """(bottom, top, step) for an axis: a round step first, so every label is round too."""
    span = max(hi, -lo / 2, 0)
    step = nice_max(span / steps) if span > 0 else 1
    top = max(math.ceil(hi / step - 1e-9), 1) * step
    bottom = -math.ceil(-lo / step - 1e-9) * step if lo < 0 else 0
    return bottom, top, step


def _tabular(font: QFont) -> QFont:
    """Digits all the same width, so amounts line up in a column."""
    try:
        font.setFeature(QFont.Tag("tnum"), 1)
    except (AttributeError, TypeError):  # an older Qt: proportional digits it is
        pass
    return font


class Tip(QWidget):
    """The note that reads out a month: its name, a row per series, and a total."""

    PAD, ROW, SWATCH = 12, 22, 9

    def __init__(self, chart: QWidget):
        super().__init__(chart, Qt.ToolTip | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
        self.setObjectName("chart-tip")
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.title, self.rows = "", []
        self.font_title = QFont(chart.font())
        self.font_title.setPixelSize(theme.TEXT["sm"])
        self.font_title.setWeight(QFont.DemiBold)
        self.font_row = _tabular(QFont(chart.font()))
        self.font_row.setPixelSize(theme.TEXT["sm"])
        self.font_total = _tabular(QFont(self.font_row))
        self.font_total.setWeight(QFont.DemiBold)

    def set(self, title: str, rows: list[tuple[str, str, str]]) -> None:
        """rows are (name, amount, color); a row with no color is the total."""
        self.title, self.rows = title, rows
        names = QFontMetrics(self.font_row)
        amounts = QFontMetrics(self.font_total)
        name_w = max([names.horizontalAdvance(n) for n, _, _ in rows] + [0])
        amount_w = max([amounts.horizontalAdvance(a) for _, a, _ in rows] + [0])
        width = max(QFontMetrics(self.font_title).horizontalAdvance(title),
                    self.SWATCH + 8 + name_w + 24 + amount_w) + 2 * self.PAD
        total = any(not c for _, _, c in rows)
        height = 2 * self.PAD + 20 + 4 + self.ROW * len(rows) + (6 if total else 0)
        self.resize(width + 2 * SHADOW, height + 2 * SHADOW)
        self.setAccessibleDescription(f"{title}: " + ", ".join(f"{n} {a}" for n, a, _ in rows))
        self.update()

    def panel(self) -> QSize:
        return self.size() - QSize(2 * SHADOW, 2 * SHADOW)

    def show_at(self, anchor: QPoint, bounds: QRect) -> None:
        """Above the anchor, centered on it, kept inside bounds; below it when there's no room."""
        panel = self.panel()
        x = min(max(anchor.x() - panel.width() // 2, bounds.left() + 4), bounds.right() - 4 - panel.width())
        y = anchor.y() - 10 - panel.height()
        if y < bounds.top() + 4:
            y = anchor.y() + 14
        at = QPoint(x - SHADOW, y - SHADOW)
        if self.isVisible():
            motion.slide(self, at)
        else:
            self.move(at)
            self.show()
            motion.fade_in(self)

    def paintEvent(self, _event):  # noqa: N802 - Qt's name
        t = theme.current()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        box = QRectF(self.rect()).adjusted(SHADOW, SHADOW, -SHADOW, -SHADOW)
        paint_panel(painter, box, t)
        left, right = box.left() + self.PAD, box.right() - self.PAD
        y = box.top() + self.PAD
        painter.setFont(self.font_title)
        painter.setPen(QColor(t["ink"]))
        painter.drawText(QRectF(left, y, right - left, 20), Qt.AlignLeft | Qt.AlignVCenter, self.title)
        y += 24
        for name, amount, color in self.rows:
            if not color:  # the total, under a line
                y += 3
                painter.setPen(QPen(QColor(t["line"]), 1))
                painter.drawLine(QPointF(left, y), QPointF(right, y))
                y += 3
                painter.setFont(self.font_total)
                painter.setPen(QColor(t["ink"]))
                painter.drawText(QRectF(left, y, right - left, self.ROW), Qt.AlignLeft | Qt.AlignVCenter, name)
            else:
                painter.setPen(Qt.NoPen)
                painter.setBrush(QColor(color))
                s = self.SWATCH
                painter.drawRoundedRect(QRectF(left, y + (self.ROW - s) / 2, s, s), 2.5, 2.5)
                painter.setFont(self.font_row)
                painter.setPen(QColor(t["ink-2"]))
                painter.drawText(QRectF(left + s + 8, y, right - left - s - 8, self.ROW), Qt.AlignLeft | Qt.AlignVCenter, name)
                painter.setFont(self.font_total)
            painter.setPen(QColor(t["ink"]))
            painter.drawText(QRectF(left, y, right - left, self.ROW), Qt.AlignRight | Qt.AlignVCenter, amount)
            y += self.ROW


class Chart(QWidget):
    def __init__(self, months: list[str], series: list[Series], tokens: dict[str, str], kind: str = "bars",
                 stacked: bool = False, height: int = 260, partial_month: str | None = None,
                 labels: list[str] | None = None, titles: list[str] | None = None,
                 on_pick: Callable[[str], None] | None = None):
        """labels and titles, for a chart that isn't of months: what the axis says under each
        point, and what its note is headed. on_pick: what choosing a month does, by clicking it
        or with Enter, such as showing just that month."""
        super().__init__()
        self.months, self.series, self.tokens = months, series, tokens
        self.labels, self.titles, self.on_pick = labels, titles, on_pick
        self.kind, self.stacked, self.partial_month = kind, stacked, partial_month
        self.base = height
        self.at = -1  # the month being read
        self.grown = 0.0 if motion.on() and grow_next else 1.0  # how far the bars have grown in
        self.shade = 0.0  # how strongly the month being read is shaded
        self.note: Tip | None = None
        self.setMinimumHeight(height)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setAccessibleName("Chart. Use the left and right arrow keys to read each month"
                               + (", and Enter to see just that one." if on_pick else "."))
        self.setAccessibleDescription(". ".join(self.spoken(i) for i in range(len(months))))

    def sizeHint(self):  # noqa: N802 - Qt's name
        return QSize(400, self.base)

    def showEvent(self, event):  # noqa: N802 - Qt's name
        super().showEvent(event)
        if self.grown < 1:
            motion.progress(self, self._grow, name="_growing")

    def _grow(self, value: float) -> None:
        self.grown = value
        self.update()

    def _shade(self, value: float) -> None:
        self.shade = value
        self.update()

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
        title = self.titles[i] if self.titles else \
            fmt.month_name(month) + (" (so far)" if month == self.partial_month and self.kind == "bars" else "")
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
        bottom, top, tick = scale(lo, hi)
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

    def peak(self, i: int) -> float:
        """The highest value drawn in a month, where its note points."""
        values = self.values_at(i)
        if self.stacked:
            return sum(max(v or 0, 0) for v in values)
        return max([v for v in values if v is not None] + [0])

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

        if 0 <= self.at < len(self.months) and self.shade > 0:
            shade = _qcolor(t["hover"])
            shade.setAlphaF(shade.alphaF() * self.shade)
            painter.setPen(Qt.NoPen)
            painter.setBrush(shade)
            painter.drawRoundedRect(QRectF(x(self.at) + 2, TOP, band - 4, height - TOP - BOTTOM), 6, 6)
        v = bottom
        while v <= top + tick / 2:
            painter.setPen(QPen(_qcolor(t["line"] if v == 0 else t["line-soft"]), 1))
            painter.drawLine(QPointF(LEFT, y(v)), QPointF(width - RIGHT, y(v)))
            painter.setPen(QColor(t["muted"]))
            painter.drawText(QRectF(0, y(v) - 8, LEFT - 8, 16), Qt.AlignRight | Qt.AlignVCenter, fmt.short(v))
            v += tick
        every = math.ceil(len(self.months) / max(1, math.floor((width - LEFT - RIGHT) / LABEL_EVERY)))
        for i, m in enumerate(self.months):
            if i % every == 0:
                year = len(self.months) <= 6 or m.endswith("-01")
                middle = x(i) + band / 2
                painter.setPen(QColor(t["ink"] if i == self.at else t["muted"]))
                painter.drawText(QRectF(middle - 60, height - BOTTOM + 4, 120, BOTTOM - 4), Qt.AlignHCenter | Qt.AlignTop,
                                 self.labels[i] if self.labels else fmt.month_name(m, year))

        def grown(v: float) -> float:
            return y(v * self.grown)
        if self.kind == "lines":
            self._lines(painter, band, x, grown)
        else:
            self._bars(painter, band, x, grown)

    def _bars(self, painter: QPainter, band: float, x, y) -> None:
        inner = min(band * .72, 96)
        painter.setPen(Qt.NoPen)
        for i in range(len(self.months)):
            if self.stacked:
                self._stack(painter, i, x(i) + (band - min(inner, max(26, band * .42))) / 2,
                            min(inner, max(26, band * .42)), y)
                continue
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

    def _stack(self, painter: QPainter, i: int, left: float, w: float, y) -> None:
        """One month's slices, rounded as one bar, with a hairline between slices big enough
        to need it. Tiny slices sit flush instead of turning into stripes."""
        up = down = 0
        slices = []
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
            slices.append((min(a, b), max(a, b), s.paint(v)))
        if not slices:
            return
        outline = QPainterPath()
        top_y, bottom_y = y(up), y(down)
        outline.addRoundedRect(QRectF(left, top_y, w, max(bottom_y - top_y, 1)), 4, 4)
        painter.save()
        painter.setClipPath(outline)
        for low, high, color in slices:
            painter.fillRect(QRectF(left, y(high), w, max(y(low) - y(high), 1)), QColor(color))
        painter.setPen(QPen(QColor(self.tokens["surface"]), 1.5))
        for (low, high, _), (low2, high2, _) in zip(slices, slices[1:]):
            if y(low) - y(high) >= STACK_GAP and y(low2) - y(high2) >= STACK_GAP:
                edge = y(high) if high == low2 else y(low)
                painter.drawLine(QPointF(left, edge), QPointF(left + w, edge))
        painter.restore()

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
                if v is not None and (len(self.months) <= 2 or i == len(s.values) - 1 or i == self.at):
                    painter.drawEllipse(QPointF(x(i) + band / 2, y(v)), 4.5 if i == self.at else 4, 4.5 if i == self.at else 4)

    # ---- reading it

    def _read(self, i: int, _at=None) -> None:
        was = self.at
        self.at = i
        if i < 0:
            self.shade = 0
            if self.note is not None:
                self.note.hide()
            self.update()
            return
        if was < 0:
            motion.progress(self, self._shade, ms=motion.FAST, name="_shading")
        else:
            self.update()
        if self.note is None:
            self.note = Tip(self)
        self.note.set(*self.tip(i))
        _, _, _, _, _, band, x, y = self.frame()
        anchor = self.mapToGlobal(QPointF(x(i) + band / 2, min(y(self.peak(i)), self.height() - BOTTOM)).toPoint())
        window = self.window()
        bounds = QRect(window.mapToGlobal(QPoint(0, 0)), window.size())
        self.note.show_at(anchor, bounds)

    def mouseMoveEvent(self, event):  # noqa: N802 - Qt's name
        i = self.index_at(event.position().x())
        if i != self.at:
            self._read(i)
        if self.on_pick:
            self.setCursor(Qt.PointingHandCursor if i >= 0 else Qt.ArrowCursor)

    def mouseReleaseEvent(self, event):  # noqa: N802 - Qt's name
        i = self.index_at(event.position().x())
        if event.button() == Qt.LeftButton and i >= 0:
            self.pick(i)
        super().mouseReleaseEvent(event)

    def pick(self, i: int) -> None:
        """Choose a month. It happens once this click is over, since choosing redraws the tab
        this chart is on."""
        if self.on_pick and 0 <= i < len(self.months):
            month, chosen = self.months[i], self.on_pick
            QTimer.singleShot(0, lambda: chosen(month))

    def leaveEvent(self, event):  # noqa: N802 - Qt's name
        self._read(-1)
        super().leaveEvent(event)

    def keyPressEvent(self, event):  # noqa: N802 - Qt's name
        if event.key() in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space) and self.on_pick and self.at >= 0:
            self.pick(self.at)
            return
        move = {Qt.Key_Right: 1, Qt.Key_Left: -1}.get(event.key())
        if not move or not self.months:
            return super().keyPressEvent(event)
        last = len(self.months) - 1
        i = last if self.at < 0 and move < 0 else min(max(self.at + move, 0), last)
        self._read(i)
        self.setAccessibleDescription(self.spoken(i))

    def focusOutEvent(self, event):  # noqa: N802 - Qt's name
        self._read(-1)
        super().focusOutEvent(event)

    def hideEvent(self, event):  # noqa: N802 - Qt's name
        if self.note is not None:
            self.note.hide()
        super().hideEvent(event)


def _qcolor(css: str) -> QColor:
    """The tokens' rgba(r, g, b, .08) as a color."""
    if css.startswith("rgba("):
        r, g, b, a = (p.strip() for p in css[5:-1].split(","))
        color = QColor(int(r), int(g), int(b))
        color.setAlphaF(float(a))
        return color
    return QColor(css)
