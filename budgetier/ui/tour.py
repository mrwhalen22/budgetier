"""The tour: a few steps, each pointing at one part of the window.

It starts by itself the first time there's data to show, whether that's when Budgetier opens,
after your first files or sync, or in the sample data, and from Help any time after. Seeing it
to the end, or skipping it, is remembered in your own settings.json, not the sample's.
"""
from __future__ import annotations

from PySide6.QtCore import QEvent, QPoint, QRect, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPainterPath
from PySide6.QtWidgets import QFrame, QPushButton, QVBoxLayout, QWidget

from . import settings, theme, widgets

START_AFTER = 500  # milliseconds, so the window has drawn first
PAD = 5
COACH_WIDTH = 340
# Where each step points, by the window's attribute or the tab's name, then what it says.
STEPS = [
    ("add_button", "Add more history",
     "Choose CSV exports or a Synchrony PDF any time. You check everything on a review screen before it's saved."),
    ("bank_button", "Keep accounts up to date", "Connect your banks through SimpleFIN, or sync the ones you've connected."),
    ("Overview", "See the big picture", "Spending, income and how much of each dollar you keep, by month."),
    ("Budgets", "Set monthly budgets",
     "Give a category a target, in dollars or as a percent of income, and see what's left each month."),
    ("Recurring", "Spot regular bills", "Subscriptions and repeat payments are found automatically."),
    ("Savings", "Watch what you keep", "Your savings rate, the goals you're saving toward, and your net worth."),
    ("Rules", "Teach it your merchants",
     "Give unknown purchases a name and category. It applies to all your history and future imports."),
    ("Accounts", "Manage your accounts",
     "Manage bank sync, set card balances, remove files or accounts, and export to Excel."),
    ("Help", "Find help any time", "See which banks work and how to get the most accurate numbers."),
]


def seen(home) -> bool:
    return bool(settings.load(home).get("toured"))


class Tour(QWidget):
    """Dims the window except for one part, with a note beside it."""

    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.at = 0
        self.setAttribute(Qt.WA_NoSystemBackground)
        self.coach = QFrame(self)
        self.coach.setObjectName("coach")
        self.coach.setFixedWidth(COACH_WIDTH)
        self.coach.setAccessibleName("Tour")
        column = QVBoxLayout(self.coach)
        column.setContentsMargins(*(theme.SPACE[4],) * 4)
        column.setSpacing(theme.SPACE[2])
        self.title = widgets.text("", "h3")
        self.words = widgets.text("")
        self.count = widgets.text("", "s")
        self.skip = QPushButton("Skip")
        self.skip.setProperty("kind", "small")
        self.skip.clicked.connect(self.end)
        self.next = QPushButton("Next")
        self.next.setProperty("kind", "small-primary")
        self.next.clicked.connect(lambda: self.show_step(self.at + 1))
        foot = widgets.row(self.count, self.skip, self.next, stretch_last=True)
        foot.layout().insertStretch(1, 1)
        column.addWidget(self.title)
        column.addWidget(self.words)
        column.addWidget(foot)
        window.installEventFilter(self)

    def target(self, name: str) -> QWidget:
        return getattr(self.window, name, None) or self.window.tab_buttons[name]

    def show_step(self, n: int) -> None:
        if n >= len(STEPS):
            return self.end()
        self.at = n
        name, title, words = STEPS[n]
        self.title.setText(title)
        self.words.setText(words)
        self.count.setText(f"{n + 1} of {len(STEPS)}")
        self.next.setText("Done" if n + 1 == len(STEPS) else "Next")
        self.place()
        self.show()
        self.raise_()
        self.next.setFocus()

    def spot(self) -> QRect:
        target = self.target(STEPS[self.at][0])
        corner = target.mapTo(self.window, QPoint(0, 0))
        return QRect(corner, target.size()).adjusted(-PAD, -PAD, PAD, PAD)

    def place(self) -> None:
        self.setGeometry(self.window.rect())
        spot = self.spot()
        self.coach.adjustSize()
        x = min(spot.right() + 16, self.width() - COACH_WIDTH - 16)
        y = min(spot.top(), self.height() - self.coach.height() - 16)
        self.coach.move(x, max(y, 16))
        self.update()

    def paintEvent(self, _event):  # noqa: N802 - Qt's name
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        everything = QPainterPath()
        everything.addRect(self.rect())
        hole = QPainterPath()
        hole.addRoundedRect(self.spot(), theme.RADIUS["md"], theme.RADIUS["md"])
        scrim = QColor(0, 0, 0)
        scrim.setAlphaF(.45)
        painter.fillPath(everything.subtracted(hole), scrim)
        painter.setPen(QColor(self.window.tokens()["accent"]))
        painter.setBrush(Qt.NoBrush)
        painter.drawRoundedRect(self.spot(), theme.RADIUS["md"], theme.RADIUS["md"])

    def eventFilter(self, watched, event):  # noqa: N802 - Qt's name
        if watched is self.window and event.type() == QEvent.Resize and self.isVisible():
            self.place()
        return False

    def keyPressEvent(self, event):  # noqa: N802 - Qt's name
        if event.key() == Qt.Key_Escape:
            return self.end()
        super().keyPressEvent(event)

    def mousePressEvent(self, event):  # noqa: N802 - Qt's name
        event.accept()  # the rest of the window waits until the tour is done

    def end(self) -> None:
        self.hide()
        self.window.removeEventFilter(self)
        settings.save(self.window.mine.home, toured=True)
        self.deleteLater()
        self.window.tour = None


def start(window) -> Tour:
    if window.tour is not None:
        window.tour.end()
    window.tour = Tour(window)
    window.tour.show_step(0)
    return window.tour


def maybe_start(window) -> None:
    """The first time there's data, once the window has drawn."""
    if window.snapshot.txns and not seen(window.mine.home):
        QTimer.singleShot(START_AFTER, lambda: window.tour is None and not seen(window.mine.home) and start(window))
