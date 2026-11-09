"""Dialogs, the note that pops up after a change, and the button that's busy while it works.

Escape does what a dialog's first button does, because closing can have a job
to finish, and Enter in a field presses the dialog's main button.
"""
from __future__ import annotations

import html
import logging
from collections.abc import Callable

from PySide6.QtCore import QPoint, Qt, QTimer
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..storage import BudgetError
from . import motion, theme, widgets

log = logging.getLogger("budgetier")
TOAST_SECONDS = 5
ACTION_SECONDS = 8  # longer when it offers something, like Undo, to give time to reach it


def attempt(work: Callable, *args) -> tuple[bool, object]:
    """Run a change to the data. (True, its result), or (False, words to show): a problem
    the app expected says what to do, and anything else is logged and kept short."""
    try:
        return True, work(*args)
    except BudgetError as e:
        return False, str(e)
    except Exception:
        log.exception("%s failed", getattr(work, "__name__", "a change"))
        return False, "Something went wrong, so that didn't finish. Details are in the logs folder in your data folder."


def busy(button: QPushButton, label: str, work: Callable[[], None]) -> None:
    """The button can't be pressed twice, and says what's happening while the work runs."""
    words = button.text()
    button.setEnabled(False)
    button.setText(label)
    QApplication.processEvents()
    try:
        work()
    finally:
        try:
            button.setEnabled(True)
            button.setText(words)
        except RuntimeError:  # the dialog it was on has closed for good
            pass


class Dialog(QDialog):
    """A title, a line under it, the body, and buttons along the bottom with room for an error."""

    def __init__(self, parent: QWidget, title: str, lead: str = ""):
        super().__init__(parent)
        self.setObjectName("dialog")
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(520)
        column = QVBoxLayout(self)
        column.setContentsMargins(*(theme.SPACE[6],) * 4)
        column.setSpacing(theme.SPACE[3])
        self.heading = widgets.text(title, "h2")
        self.lead = widgets.text(lead, "dim")
        self.lead.setVisible(bool(lead))
        column.addWidget(self.heading)
        column.addWidget(self.lead)
        self.body = QVBoxLayout()
        self.body.setSpacing(theme.SPACE[3])
        column.addLayout(self.body)
        foot = QHBoxLayout()
        foot.setSpacing(theme.SPACE[2])
        self.error = widgets.text("", "error")
        self.error.setAccessibleName("Problem")
        foot.addWidget(self.error, 1)
        self.buttons_row = foot
        column.addLayout(foot)
        self.buttons: list[QPushButton] = []
        self.main: QPushButton | None = None  # pressed by Enter in a field

    def showEvent(self, event):  # noqa: N802 - Qt's name
        super().showEvent(event)
        motion.fade_in(self)

    def set_lead(self, words: str) -> None:
        self.lead.setText(words)
        self.lead.setVisible(bool(words))

    def show_error(self, words: str) -> None:
        self.error.setText(words)
        if words:
            announce(self.error)

    def set_buttons(self, buttons: list[tuple[str, Callable[[], None], str]]) -> None:
        """(label, what it does, kind) for each, left to right. The last is the main one."""
        for old in self.buttons:
            self.buttons_row.removeWidget(old)
            old.deleteLater()
        self.buttons = []
        for label, run, kind in buttons:
            button = QPushButton(label)
            if kind:
                button.setProperty("kind", kind)
            button.setAutoDefault(False)
            button.clicked.connect(lambda _=False, run=run: run())
            self.buttons_row.addWidget(button)
            self.buttons.append(button)
        self.main = self.buttons[-1] if self.buttons else None

    def keyPressEvent(self, event):  # noqa: N802 - Qt's name
        if event.key() == Qt.Key_Escape:
            if self.buttons and all(b.isEnabled() for b in self.buttons):  # while something is saving, it waits
                self.buttons[0].click()
            return
        if event.key() in (Qt.Key_Return, Qt.Key_Enter) and isinstance(self.focusWidget(), QLineEdit) and self.main:
            self.main.click()
            return
        super().keyPressEvent(event)

    def dismiss(self) -> None:
        """Close, doing nothing else."""
        QDialog.reject(self)

    def reject(self):  # the window's own close button does what Escape does
        if self.buttons:
            self.buttons[0].click()
        else:
            super().reject()


def confirm(parent: QWidget, title: str, words: str, run: Callable[[], tuple[bool, object]], action: str = "Remove",
            done: Callable[[object], None] | None = None) -> Dialog:
    """Ask before something that can't be undone. run returns attempt()'s answer."""
    dialog = Dialog(parent, title)
    dialog.body.addWidget(widgets.text(words))

    def go():
        def work():
            ok, result = run()
            if not ok:
                dialog.show_error(str(result))
                return
            dialog.accept()
            if done:
                done(result)
        busy(dialog.buttons[-1], "Working...", work)

    dialog.set_buttons([("Cancel", dialog.dismiss, ""), (action, go, "danger")])
    dialog.open()
    return dialog


def announce(widget: QWidget) -> None:
    """Tell a screen reader that this just appeared."""
    try:
        from PySide6.QtGui import QAccessible, QAccessibleEvent
        QAccessible.updateAccessibility(QAccessibleEvent(widget, QAccessible.Event.Alert))
    except (ImportError, AttributeError, RuntimeError):  # no screen reader support here: nothing to tell
        pass


class Toast(QLabel):
    """A short note at the bottom of the window that goes away by itself."""

    def __init__(self, window: QWidget):
        super().__init__(window)
        self.setObjectName("toast")
        self.setTextFormat(Qt.PlainText)
        self.setAlignment(Qt.AlignCenter)
        self.setAccessibleName("Note")
        self.hide()
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(lambda: motion.reveal(self, ms=motion.NORMAL, out=True, then=self.hide))
        self.action: tuple[str, Callable[[], None]] | None = None
        self.words = ""  # what it says, without the link
        self.linkActivated.connect(lambda _link: self.act())

    def stay(self, words: str) -> None:
        """Until told otherwise, for work that may take a while."""
        self.say(words)
        self.timer.stop()

    def act(self) -> None:
        """Do what the note offers, once."""
        action, self.action = self.action, None
        if action:
            self.hide()
            action[1]()

    def say(self, words: str, action: tuple[str, Callable[[], None]] | None = None) -> None:
        """action: (label, what it does), offered as a link after the words, like Undo."""
        if not words:
            return
        self.action, self.words = action, words
        if action:
            # The words can hold a merchant's name, so they're escaped before they're shown as rich text.
            link = theme.current().get("page", "#ffffff")
            self.setTextFormat(Qt.RichText)
            self.setTextInteractionFlags(Qt.LinksAccessibleByMouse)
            self.setText(f'{html.escape(words)}&nbsp;&nbsp;<a href="act" style="color: {link}; font-weight: 600;">'
                         f'{html.escape(action[0])}</a>')
        else:
            self.setTextFormat(Qt.PlainText)
            self.setTextInteractionFlags(Qt.NoTextInteraction)
            self.setText(words)
        self.setAccessibleName(f"{words} {action[0]}" if action else words)
        self.adjustSize()
        at = self.spot()
        if self.isVisible() and self.graphicsEffect() is None:
            self.move(at)  # already showing: just the new words
        else:
            self.show()
            motion.reveal(self)
            motion.slide(self, at, start=at + QPoint(0, theme.SPACE[2]))
        self.raise_()
        self.timer.start((ACTION_SECONDS if action else TOAST_SECONDS) * 1000)
        announce(self)

    def spot(self) -> QPoint:
        parent = self.parentWidget()
        return QPoint((parent.width() - self.width()) // 2, parent.height() - self.height() - theme.SPACE[6])

    def follow(self) -> None:
        """Stay centered at the bottom when the window changes size."""
        if self.isVisible():
            motion.stop(self)  # a slide still on its way to the old spot would pull it back
            self.move(self.spot())
