"""Updates: a quiet check when the window opens, a check by hand, and installing.

Only an installed copy can update. The quiet check doesn't hold the window, since it reads
nothing of yours and being offline isn't worth a message.
"""
from __future__ import annotations

import sys

from PySide6.QtCore import QTimer

from ..service import app_version
from . import widgets
from .dialogs import Dialog

CLOSE_AFTER = 500  # milliseconds, so the note is seen before the window goes


def steps(system: str, reopens: bool) -> str:
    if reopens:
        return "Budgetier closes, Windows asks for your permission, and it opens again when the update is done."
    if system == "linux":
        return "When the download opens, unpack it over your Budgetier folder."
    return "When the download opens, drag Budgetier to Applications and replace the old copy."


class Updating:
    def __init__(self, window):
        self.window = window
        self.found: dict | None = None

    @property
    def updates(self):
        return self.window.budget.updates

    def status(self) -> dict:
        return self.updates.status()

    # ---- checking

    def check_quietly(self) -> None:
        self.window.runner.quietly(self.updates.check, (False,), self._checked)

    def check_by_hand(self) -> None:
        self.window.runner.start(self.updates.check, (True,), lambda ok, found: self._checked(ok, found, by_hand=True),
                                 "Checking for updates...")

    def _checked(self, ok: bool, found, by_hand: bool = False) -> None:
        if not ok:
            if by_hand:
                self.window.toast.say(str(found))
            return
        self.found = found if found["available"] else None
        button = self.window.update_button
        button.setVisible(bool(self.found))
        if self.found:
            button.setText(f"Update to {self.found['version']}")
        if by_hand:
            if self.found:
                self.form()
            else:
                self.window.toast.say("You have the latest version.")

    def set_automatic(self, on: bool) -> None:
        from .dialogs import attempt
        ok, result = attempt(self.updates.set_automatic, on)
        if not ok:
            self.window.toast.say(str(result))
        self.window.render()

    # ---- installing

    def form(self) -> Dialog:
        found = self.found
        dialog = Dialog(self.window, f"Update to {found['version']}", f"You have version {app_version()}.")
        dialog.body.addWidget(widgets.text(f"{steps(sys.platform, found['reopens'])} Your data isn't touched."))
        dialog.set_buttons([("Cancel", dialog.dismiss, ""), ("Update", lambda: self._install(dialog), "primary")])
        dialog.open()
        return dialog

    def _install(self, dialog: Dialog) -> None:
        dialog.main.setEnabled(False)
        dialog.main.setText("Downloading...")

        def answered(ok: bool, done) -> None:
            if not ok:
                dialog.main.setEnabled(True)
                dialog.main.setText("Update")
                return dialog.show_error(str(done))
            dialog.dismiss()
            if done["closing"]:
                note = Dialog(self.window, "Updating", "Budgetier is closing to finish the update.")
                note.open()
                QTimer.singleShot(CLOSE_AFTER, self.window.close)
                return
            last = ("Quit Budgetier, then unpack the download over your Budgetier folder." if sys.platform == "linux"
                    else "Quit Budgetier, then drag it to Applications and replace the old copy.")
            almost = Dialog(self.window, "Almost done")
            almost.body.addWidget(widgets.text(last))
            almost.set_buttons([("Done", almost.dismiss, "primary")])
            almost.open()
        self.window.runner.start(self.updates.install, (), answered, "Downloading the update...")
