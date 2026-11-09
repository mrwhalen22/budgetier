"""Encrypting your data with a passcode, and asking for it: when Budgetier opens, and after time
away. How the encryption works is in budgetier/vault.py.

Turning it on encrypts every file in the data folder and shows a recovery key once. Without
the passcode or that key, nobody can read the files, so the key has to be kept somewhere safe.
"""
from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, Qt, QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication, QDialog, QFrame, QLineEdit, QPushButton, QVBoxLayout

from .. import storage, vault
from . import theme, widgets
from .dialogs import Dialog, confirm
from .editing import code_font
from .importing import field
from .popup import Dropdown

AFTER = ((0, "Only when it opens"), (5, "After 5 minutes away"), (15, "After 15 minutes away"), (60, "After an hour away"))
TRIES = 5  # wrong passcodes in a row before waiting
WAIT_SECONDS = 30
WARNING = ("If you lose both the passcode and the recovery key, nobody can open your data, not even with help. "
           "Keep the recovery key somewhere safe, away from this computer.")


def saved(home) -> dict | None:
    """The vault's header when the data folder is encrypted, or None."""
    try:
        return vault.read_header(home)
    except vault.WrongKey:
        return None


def lock_after(home) -> int:
    header = saved(home) or {}
    after = header.get("lock_after", 15)
    return after if after in dict(AFTER) else 15


def _password(name: str) -> QLineEdit:
    box = QLineEdit()
    box.setEchoMode(QLineEdit.Password)
    box.setAccessibleName(name)
    return box


class Away(QObject):
    """Notices time away: no key or mouse in the app for the minutes chosen."""

    def __init__(self, window):
        super().__init__(window)
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


class Tries:
    """Wrong passcodes in a row, and the wait after too many."""

    def __init__(self):
        self.wrong, self.until = 0, 0.0

    def waiting(self) -> int:
        import time
        return max(0, int(self.until - time.monotonic()) + 1) if time.monotonic() < self.until else 0

    def missed(self) -> str:
        import time
        self.wrong += 1
        if self.wrong >= TRIES:
            self.wrong, self.until = 0, time.monotonic() + WAIT_SECONDS
            return f"Too many tries. Wait {WAIT_SECONDS} seconds."
        return "That isn't it. Try again."


class LockScreen(QFrame):
    """Covers the window after time away, until the passcode is entered. What's behind it is
    hidden, not just covered, so a screen reader can't read it either."""

    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.setObjectName("lockScreen")
        self.tries = Tries()
        self.code = _password("Passcode")
        self.code.setPlaceholderText("Passcode")
        self.code.setMaximumWidth(theme.px(280))
        self.code.returnPressed.connect(self.attempt)
        self.go = QPushButton("Unlock")
        self.go.setProperty("kind", "primary")
        self.go.clicked.connect(lambda _=False: self.attempt())
        self.said = widgets.text("", "sub")
        self.said.setAlignment(Qt.AlignCenter)
        title = widgets.text("Budgetier is locked", "h1")
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
        wait = self.tries.waiting()
        if wait:
            self.said.setText(f"Too many tries. Wait {wait} seconds.")
            return
        if saved(self.window.mine.home) is None or vault.check(self.window.mine.home, self.code.text()):
            self.tries.wrong = 0
            self.window.unlock()
            return
        self.code.clear()
        self.said.setText(self.tries.missed())


# ---- when Budgetier opens


class Unlock(QDialog):
    """Asked for before anything is read, since nothing can be until the passcode is given.
    The recovery key opens it too, and then a new passcode is chosen."""

    def __init__(self, home):
        super().__init__()
        self.home = home
        self.opened: vault.Vault | None = None
        self.recovered = False
        self.tries = Tries()
        self.setObjectName("dialog")
        self.setWindowTitle("Budgetier")
        self.setMinimumWidth(theme.px(420))
        column = QVBoxLayout(self)
        column.setContentsMargins(*(theme.SPACE[6],) * 4)
        column.setSpacing(theme.SPACE[3])
        self.title = widgets.text("Your data is encrypted", "h2")
        self.lead = widgets.text("Enter your passcode to open it.", "dim")
        self.code = _password("Passcode")
        self.code.returnPressed.connect(self.attempt)
        self.said = widgets.text("", "error")
        self.go = QPushButton("Open")
        self.go.setProperty("kind", "primary")
        self.go.clicked.connect(lambda _=False: self.attempt())
        self.switch = QPushButton("Use the recovery key")
        self.switch.setProperty("kind", "small")
        self.switch.clicked.connect(lambda _=False: self.use_recovery(not self.recovered))
        quit_ = QPushButton("Quit")
        quit_.clicked.connect(lambda _=False: self.reject())
        for widget in (self.title, self.lead, self.code, self.said):
            column.addWidget(widget)
        column.addWidget(widgets.row(self.switch, quit_, self.go, spacing=theme.SPACE[2]))
        self.code.setFocus()

    def use_recovery(self, on: bool) -> None:
        self.recovered = on
        self.lead.setText("Enter the recovery key you saved when you turned encryption on. Then choose a new passcode."
                          if on else "Enter your passcode to open it.")
        self.code.setEchoMode(QLineEdit.Normal if on else QLineEdit.Password)
        self.code.setPlaceholderText("XXXXX-XXXXX-XXXXX-XXXXX-XXXXX" if on else "")
        self.switch.setText("Use the passcode" if on else "Use the recovery key")
        self.code.clear()
        self.said.setText("")
        self.code.setFocus()

    def attempt(self) -> None:
        wait = self.tries.waiting()
        if wait:
            return self.said.setText(f"Too many tries. Wait {wait} seconds.")
        try:
            opener = vault.open_with_recovery if self.recovered else vault.open_with
            self.opened = opener(self.home, self.code.text())
        except vault.WrongKey:
            self.code.clear()
            return self.said.setText(self.tries.missed() if not self.recovered else "That recovery key isn't right.")
        self.accept()


class NewPasscode(QDialog):
    """After opening with the recovery key: a new passcode, so the forgotten one stops working."""

    def __init__(self, opened: vault.Vault):
        super().__init__()
        self.opened = opened
        self.setObjectName("dialog")
        self.setWindowTitle("Budgetier")
        column = QVBoxLayout(self)
        column.setContentsMargins(*(theme.SPACE[6],) * 4)
        column.setSpacing(theme.SPACE[3])
        column.addWidget(widgets.text("Choose a new passcode", "h2"))
        self.new, self.again = _password("New passcode"), _password("New passcode again")
        column.addWidget(field("New passcode", self.new))
        column.addWidget(field("Once more", self.again))
        self.said = widgets.text("", "error")
        column.addWidget(self.said)
        go = QPushButton("Save")
        go.setProperty("kind", "primary")
        go.clicked.connect(lambda _=False: self.save())
        self.again.returnPressed.connect(self.save)
        column.addWidget(widgets.row(go))

    def save(self) -> None:
        problem = passcode_problem(self.new.text(), self.again.text())
        if problem:
            return self.said.setText(problem)
        self.opened.change_passcode(self.new.text())
        self.accept()


def unlock_at_start(home) -> bool:
    """Open an encrypted data folder before anything reads it. False: quit instead."""
    if saved(home) is None:
        return True
    app = QApplication.instance()
    theme.apply(app, theme.read_look((saved(home) or {}).get("look")))
    ask = Unlock(home)
    if ask.exec() != QDialog.Accepted or ask.opened is None:
        return False
    if ask.recovered and NewPasscode(ask.opened).exec() != QDialog.Accepted:
        return False
    storage.use_vault(ask.opened)
    return True


# ---- turning it on, changing it, and turning it off


def passcode_problem(code: str, again: str) -> str:
    if len(code) < vault.SHORTEST:
        return f"Use at least {vault.SHORTEST} characters."
    if code != again:
        return "The two passcodes don't match."
    return ""


def encrypt(home, code: str, after: int, look: dict) -> str:
    """Off the window's thread: the vault, then every file in it. Returns the recovery key."""
    opened, recovery = vault.create(home, code)
    opened.set_option(lock_after=after, look=look)
    storage.use_vault(opened)
    storage.seal_folder(opened)
    return recovery


def decrypt(home) -> None:
    """Every file back to plain, and only then the vault goes, so stopping partway leaves a
    folder that still opens with the passcode."""
    opened = storage.open_vault()
    storage.unseal_folder(opened)
    vault.header_path(home).unlink()
    storage.use_vault(None)


def show_recovery(window, key: str, first: bool) -> Dialog:
    """The recovery key, once. It can't be closed until you say it's saved."""
    dialog = Dialog(window, "Save your recovery key",
                    ("Your data is now encrypted. " if first else "This replaces your old recovery key, which no longer "
                     "works. ") + "This key opens it if you forget the passcode. It's shown only now.")
    shown = QLineEdit(key)
    shown.setReadOnly(True)
    shown.setAccessibleName("Recovery key")
    shown.setFont(code_font())
    copy = QPushButton("Copy")
    copy.setProperty("kind", "small")
    copy.clicked.connect(lambda _=False: (QGuiApplication.clipboard().setText(key), window.toast.say("Copied.")))
    dialog.body.addWidget(widgets.row(shown, copy, spacing=theme.SPACE[2]))
    dialog.body.addWidget(widgets.text(WARNING, "warn"))
    kept = widgets.check("I've saved my recovery key somewhere safe", False, lambda on: done.setEnabled(on))
    dialog.body.addWidget(kept)
    dialog.set_buttons([("Done", dialog.dismiss, "primary")])
    done = dialog.main
    done.setEnabled(False)
    dialog.kept = kept
    dialog.open()
    return dialog


def setup(window) -> Dialog | None:
    if window.blocked_by_sample():
        return None
    home = window.mine.home
    return _change(window, home) if saved(home) else _turn_on(window, home)


def _after_box(home) -> Dropdown:
    after = Dropdown()
    after.setAccessibleName("Lock")
    for minutes, label in AFTER:
        after.addItem(label, minutes)
    after.setCurrentIndex(max(after.findData(lock_after(home)), 0))
    return after


def _turn_on(window, home) -> Dialog:
    dialog = Dialog(window, "Encrypt your data",
                    "Encrypts everything Budgetier keeps about your money, so only someone with the passcode can read it, "
                    "even with the disk in hand. Budgetier asks for it when it opens, and after time away.")
    new, again = _password("Passcode"), _password("Passcode again")
    after = _after_box(home)
    dialog.body.addWidget(field("Passcode", new))
    dialog.body.addWidget(field("Once more", again))
    dialog.body.addWidget(field("Also ask", after))
    dialog.body.addWidget(widgets.text(WARNING, "warn"))
    dialog.fields = {"new": new, "again": again, "after": after}

    def go() -> None:
        problem = passcode_problem(new.text(), again.text())
        if problem:
            return dialog.show_error(problem)
        look = window.look
        dialog.dismiss()

        def answered(ok, key):
            if not ok:
                return window.toast.say(f"Couldn't encrypt: {key}")
            window.lock_changed()
            window.changed()
            show_recovery(window, key, True)
        window.runner.start(encrypt, (home, new.text(), after.currentData(),
                                      {"mode": look.mode, "palette": look.palette, "size": look.size}),
                            answered, "Encrypting your data...")

    dialog.set_buttons([("Cancel", dialog.dismiss, ""), ("Encrypt", go, "primary")])
    dialog.open()
    new.setFocus()
    return dialog


def _change(window, home) -> Dialog:
    dialog = Dialog(window, "Encryption", "Your data is encrypted. Enter your passcode to change how it's kept.")
    current, new, again = _password("Current passcode"), _password("New passcode"), _password("New passcode again")
    after = _after_box(home)
    dialog.body.addWidget(field("Current passcode", current))
    dialog.body.addWidget(field("New passcode, or blank to keep it", new))
    dialog.body.addWidget(field("Once more", again))
    dialog.body.addWidget(field("Also ask", after))
    dialog.fields = {"current": current, "new": new, "again": again, "after": after}

    def checked() -> bool:
        if not vault.check(home, current.text()):
            dialog.show_error("The current passcode isn't right.")
            return False
        return True

    def save() -> None:
        if not checked():
            return
        opened = storage.open_vault()
        if new.text() or again.text():
            problem = passcode_problem(new.text(), again.text())
            if problem:
                return dialog.show_error(problem)
            opened.change_passcode(new.text())
        opened.set_option(lock_after=after.currentData())
        dialog.dismiss()
        window.lock_changed()
        window.toast.say("Saved. Press Ctrl+L to lock now.")

    def recovery() -> None:
        if not checked():
            return
        dialog.dismiss()
        show_recovery(window, storage.open_vault().new_recovery_key(), False)

    def turn_off() -> None:
        if not checked():
            return
        dialog.dismiss()

        def answered(ok, result):
            if not ok:
                return window.toast.say(f"Couldn't decrypt: {result}")
            window.lock_changed()
            window.changed("Your data isn't encrypted any more.")
        confirm(window, "Turn off encryption?", "Your data will be saved unencrypted, readable by anyone with the disk. "
                "Budgetier stops asking for a passcode.", lambda: (True, None), action="Turn off",
                done=lambda _: window.runner.start(decrypt, (home,), answered, "Decrypting your data..."))

    dialog.set_buttons([("Cancel", dialog.dismiss, ""), ("New recovery key", recovery, ""), ("Turn off", turn_off, ""),
                        ("Save", save, "primary")])
    dialog.open()
    current.setFocus()
    return dialog


def close_dialogs(window) -> None:
    """What was open goes, so nothing is left showing over the lock."""
    for dialog in window.findChildren(QDialog):
        if dialog.isVisible():
            dialog.reject()

