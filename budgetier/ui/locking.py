"""A passcode to open Budgetier, and to come back to it after time away.

It keeps someone else at this computer out of the window. It doesn't encrypt the files in
the data folder: those are protected by your sign-in to the computer, and by the disk
encryption your system offers (BitLocker on Windows, FileVault on a Mac), which is what to
turn on to protect them from someone who has the disk.

Only a salted hash of the passcode is kept, in settings.json, worked out slowly on purpose so
that it can't be guessed quickly from the file.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
import time

from PySide6.QtCore import QEvent, QObject, Qt, QTimer
from PySide6.QtWidgets import QApplication, QDialog, QFrame, QLineEdit, QPushButton, QVBoxLayout

from . import settings, theme, widgets
from .dialogs import Dialog
from .importing import field
from .popup import Dropdown

SAVED_AS = "lock"
ROUNDS = 200_000
SHORTEST = 4
AFTER = ((0, "Only when it opens"), (5, "After 5 minutes away"), (15, "After 15 minutes away"), (60, "After an hour away"))
TRIES = 5  # wrong passcodes in a row before waiting
WAIT_SECONDS = 30


def digest(code: str, salt: bytes) -> str:
    return hashlib.pbkdf2_hmac("sha256", code.encode("utf-8"), salt, ROUNDS).hex()


def made(code: str, after: int) -> dict:
    salt = secrets.token_bytes(16)
    return {"salt": salt.hex(), "hash": digest(code, salt), "after": after}


def saved(home) -> dict | None:
    """The lock as saved, or None for no lock. One that can't be read is no lock, rather
    than one nobody can open."""
    lock = settings.load(home).get(SAVED_AS)
    try:
        bytes.fromhex(lock["salt"])
        bytes.fromhex(lock["hash"])
    except (TypeError, KeyError, ValueError):
        return None
    return lock if isinstance(lock.get("after", 0), int) else None


def matches(lock: dict, code: str) -> bool:
    return hmac.compare_digest(digest(code, bytes.fromhex(lock["salt"])), lock["hash"])


class Away(QObject):
    """Notices time away: no key or mouse in the app for the minutes chosen."""

    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(window.lock)
        QApplication.instance().installEventFilter(self)

    def start(self, minutes: int) -> None:
        self.timer.stop()
        if minutes:
            self.timer.setInterval(minutes * 60_000)
            self.timer.start()

    def eventFilter(self, _watched, event):  # noqa: N802 - Qt's name
        if self.timer.isActive() and event.type() in (QEvent.KeyPress, QEvent.MouseButtonPress, QEvent.MouseMove,
                                                       QEvent.Wheel):
            self.timer.start()
        return False


class LockScreen(QFrame):
    """Covers the window until the passcode is entered. What's behind it is hidden, not just
    covered, so a screen reader can't read it either."""

    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.setObjectName("lockScreen")
        self.wrong = 0
        self.until = 0.0
        self.code = QLineEdit()
        self.code.setEchoMode(QLineEdit.Password)
        self.code.setAccessibleName("Passcode")
        self.code.setPlaceholderText("Passcode")
        self.code.setMaximumWidth(theme.px(280))
        self.code.returnPressed.connect(self.attempt)
        self.go = QPushButton("Unlock")
        self.go.setProperty("kind", "primary")
        self.go.clicked.connect(lambda _=False: self.attempt())
        self.said = widgets.text("", "sub")
        self.said.setAlignment(Qt.AlignCenter)
        title = widgets.text("Budgetier is locked", "h1")
        title.setAlignment(Qt.AlignCenter)
        layout = QVBoxLayout(self)
        layout.addStretch(1)
        layout.addWidget(title, 0, Qt.AlignHCenter)
        layout.addWidget(widgets.text("Enter your passcode to carry on.", "sub"), 0, Qt.AlignHCenter)
        layout.addWidget(self.code, 0, Qt.AlignHCenter)
        layout.addWidget(self.go, 0, Qt.AlignHCenter)
        layout.addWidget(self.said, 0, Qt.AlignHCenter)
        layout.addStretch(2)
        layout.setSpacing(theme.SPACE[3])
        self.hide()

    def cover(self) -> None:
        self.setGeometry(self.window.rect())
        self.code.clear()
        self.said.setText("")
        self.show()
        self.raise_()
        self.code.setFocus()

    def attempt(self) -> None:
        if time.monotonic() < self.until:
            self.said.setText(f"Too many tries. Wait {int(self.until - time.monotonic()) + 1} seconds.")
            return
        lock = saved(self.window.mine.home)
        if lock is None or matches(lock, self.code.text()):
            self.wrong = 0
            self.window.unlock()
            return
        self.wrong += 1
        self.code.clear()
        if self.wrong >= TRIES:
            self.wrong = 0
            self.until = time.monotonic() + WAIT_SECONDS
            self.said.setText(f"Too many tries. Wait {WAIT_SECONDS} seconds.")
        else:
            self.said.setText("That isn't it. Try again.")


def setup(window) -> Dialog:
    """Set a passcode, change when it locks, or turn it off. Changing an existing lock needs
    its passcode first, so someone passing by can't just turn it off."""
    home = window.mine.home
    lock = saved(home)
    dialog = Dialog(window, "Passcode",
                    "Ask for a passcode when Budgetier opens, and after time away. It keeps others at this computer out "
                    "of the app; to protect the files themselves, turn on your system's disk encryption.")
    current = QLineEdit()
    current.setEchoMode(QLineEdit.Password)
    current.setAccessibleName("Current passcode")
    new = QLineEdit()
    new.setEchoMode(QLineEdit.Password)
    new.setAccessibleName("New passcode")
    again = QLineEdit()
    again.setEchoMode(QLineEdit.Password)
    again.setAccessibleName("New passcode again")
    after = Dropdown()
    after.setAccessibleName("Lock")
    for minutes, label in AFTER:
        after.addItem(label, minutes)
    after.setCurrentIndex(max(after.findData(lock.get("after", 15) if lock else 15), 0))
    if lock:
        dialog.body.addWidget(field("Current passcode", current))
    dialog.body.addWidget(field("New passcode" if lock else "Passcode", new))
    dialog.body.addWidget(field("Once more", again))
    dialog.body.addWidget(field("Lock", after))
    if lock:
        dialog.body.addWidget(widgets.text("Leave the new passcode blank to keep the one you have.", "sub"))
    dialog.fields = {"current": current, "new": new, "again": again, "after": after}

    def checked() -> bool:
        if lock and not matches(lock, current.text()):
            dialog.show_error("The current passcode isn't right.")
            return False
        return True

    def save() -> None:
        if not checked():
            return
        code = new.text()
        if not code and lock:
            keep = {**lock, "after": after.currentData()}
            settings.save(home, **{SAVED_AS: keep})
        elif len(code) < SHORTEST:
            return dialog.show_error(f"Use at least {SHORTEST} characters.")
        elif code != again.text():
            return dialog.show_error("The two passcodes don't match.")
        else:
            settings.save(home, **{SAVED_AS: made(code, after.currentData())})
        dialog.dismiss()
        window.lock_changed()
        window.toast.say("Passcode saved. Press Ctrl+L to lock now.")

    def turn_off() -> None:
        if not checked():
            return
        settings.save(home, **{SAVED_AS: None})
        dialog.dismiss()
        window.lock_changed()
        window.toast.say("Passcode turned off.")

    dialog.set_buttons([("Cancel", dialog.dismiss, ""), *([("Turn off", turn_off, "")] if lock else []),
                        ("Save", save, "primary")])
    dialog.open()
    (current if lock else new).setFocus()
    return dialog


def close_dialogs(window) -> None:
    """What was open goes, so nothing is left showing over the lock."""
    for dialog in window.findChildren(QDialog):
        if dialog.isVisible():
            dialog.reject()
