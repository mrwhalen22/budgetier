"""Dropdowns and the menus they open: a rounded panel with a soft shadow, rows with room,
headings that read as headings, and a chevron drawn to match the theme.

Qt's own combo box popup can't be rounded or shadowed under a style sheet, so a Dropdown
opens its own list instead. It is still a QComboBox, so everything that reads or sets one
works as before, and choosing a row emits `activated` as Qt's popup does.
"""
from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QEvent, QPoint, QPointF, QRect, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QFrame,
    QListView,
    QMenu,
    QStyle,
    QStyledItemDelegate,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from . import motion, theme

SHADOW = 12  # room around a panel for its shadow
GAP = 4  # between a field and the panel it opens
INSET = 4  # between a panel's edge and its rows
ROW, HEADING, SEPARATOR = 32, 28, 9
MOST = 360  # the tallest a list gets before it scrolls
CHEVRON = theme.CHEVRON


def _color(css: str) -> QColor:
    if css.startswith("rgba("):
        r, g, b, a = (p.strip() for p in css[5:-1].split(","))
        color = QColor(int(r), int(g), int(b))
        color.setAlphaF(float(a))
        return color
    return QColor(css)


def paint_panel(painter: QPainter, rect: QRectF, t: dict[str, str], radius: float = theme.RADIUS["md"]) -> None:
    """A raised panel: a soft shadow below, the surface, and a hairline edge."""
    painter.save()
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setPen(Qt.NoPen)
    dark = QColor(t["surface"]).lightnessF() < .5
    strength = .05 if dark else .022
    for i in range(SHADOW, 0, -2):  # layers that fade outwards, a little lower than the panel
        shade = QColor(0, 0, 0)
        shade.setAlphaF(strength * (1 - i / (SHADOW + 1)) ** 1.6 * 2)
        painter.setBrush(shade)
        painter.drawRoundedRect(rect.adjusted(-i * .7, -i * .4, i * .7, i), radius + i * .6, radius + i * .6)
    painter.setBrush(QColor(t["surface"]))
    painter.setPen(QPen(QColor(t["line"]), 1))
    painter.drawRoundedRect(rect.adjusted(.5, .5, -.5, -.5), radius, radius)
    painter.restore()


def paint_chevron(painter: QPainter, center: QPointF, color: str, size: float = 4) -> None:
    painter.save()
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setPen(QPen(QColor(color), 1.5, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    path = QPainterPath(QPointF(center.x() - size, center.y() - size / 2))
    path.lineTo(center.x(), center.y() + size / 2)
    path.lineTo(center.x() + size, center.y() - size / 2)
    painter.drawPath(path)
    painter.restore()


def place(panel: QSize, field: QRect, screen: QRect, gap: int = GAP, right: bool = False) -> QPoint:
    """Where a panel's top-left goes, as a window with SHADOW around it: under the field, or
    over it when there's no room below, and kept on the screen. Lined up with the field's
    left edge, or its right edge when `right`."""
    x = field.right() + 1 - panel.width() if right else field.left()
    x = min(max(x, screen.left() + SHADOW), screen.right() - SHADOW - panel.width())
    y = field.bottom() + 1 + gap
    if y + panel.height() > screen.bottom() - SHADOW and field.top() - gap - panel.height() >= screen.top():
        y = field.top() - gap - panel.height()
    return QPoint(x - SHADOW, y - SHADOW)


def _is_separator(index) -> bool:
    return index.data(Qt.AccessibleDescriptionRole) == "separator"


def _is_heading(index) -> bool:
    return not (index.flags() & Qt.ItemIsEnabled) and not _is_separator(index)


class Rows(QStyledItemDelegate):
    """Draws a dropdown's rows: choices, headings and separators."""

    def __init__(self, box: Dropdown):
        super().__init__(box)
        self.box = box

    def sizeHint(self, option, index):  # noqa: N802 - Qt's name
        if _is_separator(index):
            return QSize(0, SEPARATOR)
        width = QFontMetrics(option.font).horizontalAdvance(str(index.data() or "")) + 2 * theme.SPACE[3] + 24
        if self.box.dot_for:
            width += 16
        return QSize(width, HEADING if _is_heading(index) else ROW)

    def paint(self, painter, option, index):
        t = theme.current()
        r = QRectF(option.rect)
        bar = option.widget.verticalScrollBar() if isinstance(option.widget, QListView) else None
        if bar is not None and bar.isVisible():  # leave the scroll bar its own lane
            r.adjust(0, 0, -(bar.width() + 2), 0)
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        if _is_separator(index):
            painter.setPen(QPen(_color(t["line-soft"]), 1))
            y = r.center().y()
            painter.drawLine(QPointF(r.left() + 8, y), QPointF(r.right() - 8, y))
            painter.restore()
            return
        text = str(index.data() or "")
        x = r.left() + theme.SPACE[3]
        if _is_heading(index):
            font = QFont(option.font)
            font.setPixelSize(theme.TEXT["xs"])
            font.setWeight(QFont.DemiBold)
            painter.setFont(font)
            painter.setPen(QColor(t["muted"]))
            painter.drawText(QRectF(x, r.top() + 6, r.width() - x, r.height() - 6), Qt.AlignLeft | Qt.AlignVCenter, text)
            painter.restore()
            return
        chosen = index.row() == self.box.currentIndex()
        if option.state & QStyle.State_Selected:
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(t["accent-soft"]))
            painter.drawRoundedRect(r.adjusted(0, 1, 0, -1), theme.RADIUS["sm"], theme.RADIUS["sm"])
        if self.box.dot_for:
            value = index.data(Qt.UserRole)
            color = self.box.dot_for(text if value is None else value)
            if color:
                painter.setPen(Qt.NoPen)
                painter.setBrush(QColor(color))
                painter.drawEllipse(QPointF(x + 4, r.center().y()), 4, 4)
            x += 16
        font = QFont(option.font)
        font.setPixelSize(theme.TEXT["sm"])
        if chosen:
            font.setWeight(QFont.DemiBold)
        painter.setFont(font)
        painter.setPen(QColor(t["ink"]))
        painter.drawText(QRectF(x, r.top(), r.right() - x - 28, r.height()), Qt.AlignLeft | Qt.AlignVCenter,
                         QFontMetrics(font).elidedText(text, Qt.ElideRight, int(r.right() - x - 28)))
        if chosen:  # a tick for what's chosen now
            painter.setPen(QPen(QColor(t["accent"]), 1.8, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            cx, cy = r.right() - 16, r.center().y()
            tick = QPainterPath(QPointF(cx - 4.5, cy))
            tick.lineTo(cx - 1.5, cy + 3)
            tick.lineTo(cx + 4.5, cy - 3.5)
            painter.setBrush(Qt.NoBrush)
            painter.drawPath(tick)
        painter.restore()


class ListPopup(QFrame):
    """The list a Dropdown opens."""

    def __init__(self, box: Dropdown):
        super().__init__(None, Qt.Popup | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
        self.box = box
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_NoMouseReplay)  # a click on the field closes the list, not reopens it
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setObjectName("popup")
        column = QVBoxLayout(self)
        column.setContentsMargins(*(SHADOW + INSET,) * 4)
        self.list = QListView()
        self.list.setObjectName("popup-list")
        self.list.setModel(box.model())
        self.list.setItemDelegate(Rows(box))
        self.list.setFrameShape(QFrame.NoFrame)
        self.list.setMouseTracking(True)
        self.list.setUniformItemSizes(False)
        self.list.setSelectionMode(QAbstractItemView.SingleSelection)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.list.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.list.setAccessibleName(box.accessibleName())
        self.list.entered.connect(self._hover)
        self.list.clicked.connect(lambda index: self.choose(index.row()))
        self.list.installEventFilter(self)
        column.addWidget(self.list)
        self.setFocusProxy(self.list)

    def _hover(self, index) -> None:
        if index.flags() & Qt.ItemIsEnabled:
            self.list.setCurrentIndex(index)

    def choose(self, row: int) -> None:
        index = self.box.model().index(row, self.box.modelColumn())
        if not (index.flags() & Qt.ItemIsEnabled):
            return
        box = self.box
        self.close()
        box.setCurrentIndex(row)
        box.activated.emit(row)

    def eventFilter(self, watched, event):  # noqa: N802 - Qt's name
        if watched is self.list and event.type() == QEvent.KeyPress:
            if event.key() in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space):
                if self.list.currentIndex().isValid():
                    self.choose(self.list.currentIndex().row())
                return True
            if event.key() in (Qt.Key_Escape, Qt.Key_Tab, Qt.Key_Backtab):
                self.close()
                return True
        return super().eventFilter(watched, event)

    def open(self) -> None:
        box, rows = self.box, self.list
        delegate = rows.itemDelegate()
        option = _option(rows)
        height = sum(delegate.sizeHint(option, box.model().index(r, box.modelColumn())).height()
                     for r in range(box.count()))
        height = min(height, MOST) + 2 * INSET
        width = max(box.width(), rows.sizeHintForColumn(0) + 2 * INSET + (12 if height >= MOST else 0))
        panel = QSize(width, height)
        field = QRect(box.mapToGlobal(QPoint(0, 0)), box.size())
        screen = (box.screen() or QApplication.primaryScreen()).availableGeometry()
        at = place(panel, field, screen)
        self.resize(panel.width() + 2 * SHADOW, panel.height() + 2 * SHADOW)
        current = box.model().index(box.currentIndex(), box.modelColumn())
        if current.isValid():
            rows.setCurrentIndex(current)
            rows.scrollTo(current, QAbstractItemView.PositionAtCenter)
        above = at.y() + SHADOW < field.top()
        start = at + QPoint(0, 6 if above else -6)
        self.move(at)
        self.show()
        rows.setFocus()
        motion.fade_in(self)
        motion.slide(self, at, start=start)

    def paintEvent(self, _event):  # noqa: N802 - Qt's name
        painter = QPainter(self)
        paint_panel(painter, QRectF(self.rect()).adjusted(SHADOW, SHADOW, -SHADOW, -SHADOW), theme.current())

    def hideEvent(self, event):  # noqa: N802 - Qt's name
        if self.box is not None and getattr(self.box, "_popup", None) is self:
            self.box._popup = None
            self.box.update()
        super().hideEvent(event)


def _option(view: QListView):
    from PySide6.QtWidgets import QStyleOptionViewItem
    option = QStyleOptionViewItem()
    view.initViewItemOption(option)
    return option


class Dropdown(QComboBox):
    """A combo box that opens a styled list, draws its own chevron, and leaves the mouse
    wheel to the page unless it has focus, so scrolling past one doesn't change it."""

    def __init__(self, parent: QWidget | None = None, dot_for: Callable[[str], str | None] | None = None):
        super().__init__(parent)
        self.dot_for = dot_for
        self._popup: ListPopup | None = None
        self.setFocusPolicy(Qt.StrongFocus)

    def showPopup(self):  # noqa: N802 - Qt's name
        if self._popup is not None:
            return
        self._popup = ListPopup(self)
        self._popup.open()
        self.update()

    def hidePopup(self):  # noqa: N802 - Qt's name
        if self._popup is not None:
            self._popup.close()

    def popup(self) -> ListPopup | None:
        return self._popup

    def wheelEvent(self, event):  # noqa: N802 - Qt's name
        if self.hasFocus():
            super().wheelEvent(event)
        else:
            event.ignore()

    def paintEvent(self, event):  # noqa: N802 - Qt's name
        super().paintEvent(event)
        t = theme.current()
        painter = QPainter(self)
        color = t["ink"] if self.underMouse() or self._popup else t["muted"]
        paint_chevron(painter, QPointF(self.width() - CHEVRON / 2 - 2, self.height() / 2 + .5),
                      color if self.isEnabled() else t["line"])


class Picker(QToolButton):
    """A button that opens a menu, drawn like a Dropdown."""

    def paintEvent(self, event):  # noqa: N802 - Qt's name
        super().paintEvent(event)
        t = theme.current()
        painter = QPainter(self)
        open_now = self.menu() is not None and self.menu().isVisible()
        paint_chevron(painter, QPointF(self.width() - CHEVRON / 2 - 2, self.height() / 2 + .5),
                      t["ink"] if self.underMouse() or open_now else t["muted"])


class Menu(QMenu):
    """A menu on a rounded, shadowed panel. Ticking a row doesn't close it, so several can
    be changed at once."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowFlags(self.windowFlags() | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setContentsMargins(*(SHADOW + INSET,) * 4)
        self.setObjectName("menu")

    def showEvent(self, event):  # noqa: N802 - Qt's name
        super().showEvent(event)
        owner = self.parentWidget()
        if isinstance(owner, QToolButton):  # line the panel up under its button, as a Dropdown's list
            self.setMinimumWidth(owner.width() + 2 * SHADOW)
            field = QRect(owner.mapToGlobal(QPoint(0, 0)), owner.size())
            screen = (owner.screen() or QApplication.primaryScreen()).availableGeometry()
            panel = QSize(max(self.width(), owner.width() + 2 * SHADOW) - 2 * SHADOW, self.height() - 2 * SHADOW)
            at = place(panel, field, screen, right=True)
            motion.slide(self, at, start=at + QPoint(0, -6))
        motion.fade_in(self)

    def paintEvent(self, event):  # noqa: N802 - Qt's name
        painter = QPainter(self)
        paint_panel(painter, QRectF(self.rect()).adjusted(SHADOW, SHADOW, -SHADOW, -SHADOW), theme.current())
        painter.end()
        super().paintEvent(event)

    def mouseReleaseEvent(self, event):  # noqa: N802 - Qt's name
        action = self.actionAt(event.position().toPoint())
        if action is not None and action.isCheckable():
            action.trigger()
            return
        super().mouseReleaseEvent(event)
