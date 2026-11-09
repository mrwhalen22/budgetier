"""Syncing by itself: when Budgetier opens, or once a day, only if you choose it."""
import datetime as dt
from datetime import timedelta
from unittest import mock

from budgetier.storage import BudgetError
from tests.qt import QtCase


def connected(budget, mode, hours_ago=None):
    s = budget.sync
    s.state.update(connected=True, links={"bank/chk": {"account": "chk-0001", "since": None}}, auto=mode)
    if hours_ago is not None:
        s.state["last_sync"] = (dt.datetime.now() - timedelta(hours=hours_ago)).isoformat(timespec="seconds")
    s._save()


class WhenItsDue(QtCase):
    def test_off_unless_chosen(self):
        connected(self.budget, "off", hours_ago=48)
        self.assertFalse(self.budget.sync.auto_due(opening=True))
        self.assertEqual(self.budget.sync.status()["auto"], "off")

    def test_when_it_opens_unless_synced_within_the_hour(self):
        connected(self.budget, "open", hours_ago=3)
        self.assertTrue(self.budget.sync.auto_due(opening=True))
        self.assertFalse(self.budget.sync.auto_due())  # only as it opens
        connected(self.budget, "open", hours_ago=0.5)
        self.assertFalse(self.budget.sync.auto_due(opening=True))

    def test_once_a_day(self):
        connected(self.budget, "daily", hours_ago=21)
        self.assertTrue(self.budget.sync.auto_due())
        connected(self.budget, "daily", hours_ago=5)
        self.assertFalse(self.budget.sync.auto_due())

    def test_never_without_accounts_to_update(self):
        connected(self.budget, "daily")
        self.budget.sync.state["links"] = {}
        self.assertFalse(self.budget.sync.auto_due())

    def test_choices(self):
        self.budget.sync.set_auto("daily")
        self.assertEqual(self.budget.sync.auto, "daily")
        with self.assertRaises(BudgetError):
            self.budget.sync.set_auto("hourly")
        self.budget.sync.state["auto"] = "weird"
        self.assertEqual(self.budget.sync.auto, "off")


class InTheWindow(QtCase):
    def test_it_syncs_as_it_opens(self):
        connected(self.budget, "open", hours_ago=3)
        with mock.patch.object(type(self.budget.sync), "sync", return_value={"added": 2, "problems": [], "unlinked": 0}) as ran:
            win = self.window()
            from PySide6.QtCore import QCoreApplication
            QCoreApplication.processEvents()
            self.assertTrue(win.runner.wait())
        ran.assert_called_once()
        self.assertEqual(win.toast.words, "Synced: 2 new transactions.")

    def test_a_problem_is_a_note_not_a_dialog(self):
        connected(self.budget, "open", hours_ago=3)
        with mock.patch.object(type(self.budget.sync), "sync", side_effect=BudgetError("SimpleFIN couldn't be reached.")):
            win = self.window()
            from PySide6.QtCore import QCoreApplication
            QCoreApplication.processEvents()
            self.assertTrue(win.runner.wait())
        self.assertEqual(win.toast.words, "Couldn't sync by itself: SimpleFIN couldn't be reached.")

    def test_not_while_locked_but_once_unlocked(self):
        from budgetier.ui import locking, settings
        settings.save(self.budget.home, lock=locking.made("2468", 0))
        connected(self.budget, "open", hours_ago=3)
        with mock.patch.object(type(self.budget.sync), "sync", return_value={"added": 0, "problems": [], "unlinked": 0}) as ran:
            win = self.window()
            from PySide6.QtCore import QCoreApplication
            QCoreApplication.processEvents()
            ran.assert_not_called()
            win.lock_screen.code.setText("2468")
            win.lock_screen.attempt()
            self.assertTrue(win.runner.wait())
        ran.assert_called_once()

    def test_chosen_on_the_accounts_tab(self):
        from budgetier.ui.popup import Dropdown
        connected(self.budget, "off")
        win = self.window()
        win.show_tab("Accounts")
        box = win.pages["Accounts"].widget().findChild(Dropdown, "autoSync")
        box.setCurrentIndex(box.findData("daily"))
        box.activated.emit(box.currentIndex())
        self.assertEqual(self.budget.sync.auto, "daily")
        self.assertEqual(win.toast.words, "Once a day, while it's open.")
