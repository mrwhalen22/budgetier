"""A passcode to open Budgetier and to come back after time away. Only a salted hash is kept."""
import json
from unittest import mock

from budgetier.ui import locking, settings
from tests.qt import QtCase


class Hashing(QtCase):
    def test_only_a_salted_hash_is_kept(self):
        lock = locking.made("1234", 15)
        self.assertNotIn("1234", json.dumps(lock))
        self.assertTrue(locking.matches(lock, "1234"))
        self.assertFalse(locking.matches(lock, "1235"))
        self.assertNotEqual(lock["hash"], locking.made("1234", 15)["hash"])  # salted afresh each time

    def test_a_lock_that_cant_be_read_is_no_lock(self):
        for bad in ({"salt": "zz", "hash": "00"}, {"hash": "00"}, "1234", {"salt": "00", "hash": "00", "after": "soon"}):
            settings.save(self.budget.home, lock=bad)
            self.assertIsNone(locking.saved(self.budget.home), bad)


class Locked(QtCase):
    def setUp(self):
        super().setUp()
        settings.save(self.budget.home, lock=locking.made("2468", 15))

    def test_it_opens_locked_and_the_passcode_lets_you_in(self):
        win = self.window()
        self.assertTrue(win.locked)
        self.assertFalse(win.centralWidget().isVisibleTo(win))  # hidden, not only covered
        self.assertTrue(all(not s.isEnabled() for s in win.shortcuts))
        win.lock_screen.code.setText("2468")
        win.lock_screen.go.click()
        self.assertFalse(win.locked)
        self.assertTrue(win.centralWidget().isVisibleTo(win))
        self.assertTrue(win.away.timer.isActive())
        self.assertEqual(win.away.timer.interval(), 15 * 60_000)

    def test_a_wrong_passcode_and_too_many_of_them(self):
        win = self.window()
        for _ in range(locking.TRIES - 1):
            win.lock_screen.code.setText("0000")
            win.lock_screen.attempt()
        self.assertEqual(win.lock_screen.said.text(), "That isn't it. Try again.")
        win.lock_screen.code.setText("0000")
        win.lock_screen.attempt()
        win.lock_screen.code.setText("2468")
        win.lock_screen.attempt()  # right, but too soon
        self.assertTrue(win.locked)
        self.assertIn("Wait", win.lock_screen.said.text())
        with mock.patch.object(locking.time, "monotonic", return_value=win.lock_screen.until + 1):
            win.lock_screen.code.setText("2468")
            win.lock_screen.attempt()
        self.assertFalse(win.locked)

    def test_time_away_locks_it_and_open_dialogs_close(self):
        win = self.window()
        win.lock_screen.code.setText("2468")
        win.lock_screen.attempt()
        from budgetier.ui.tabs.budgets import goal_form
        dialog = goal_form(win.context())
        self.assertTrue(dialog.isVisible())
        win.away.timer.timeout.emit()
        self.assertTrue(win.locked)
        self.assertFalse(dialog.isVisible())
        self.assertFalse(win.away.timer.isActive())


class SettingItUp(QtCase):
    def test_set_change_and_turn_off(self):
        win = self.window()
        self.assertFalse(win.locked)
        win.lock()  # nothing to lock with yet
        self.assertFalse(win.locked)
        dialog = locking.setup(win)
        f = dialog.fields
        f["new"].setText("12")
        f["again"].setText("12")
        dialog.main.click()
        self.assertIn("at least", dialog.error.text())
        f["new"].setText("1357")
        f["again"].setText("1358")
        dialog.main.click()
        self.assertIn("don't match", dialog.error.text())
        f["again"].setText("1357")
        f["after"].setCurrentIndex(f["after"].findData(5))
        dialog.main.click()
        lock = locking.saved(self.budget.home)
        self.assertTrue(locking.matches(lock, "1357"))
        self.assertEqual(win.away.timer.interval(), 5 * 60_000)
        win.lock()
        self.assertTrue(win.locked)
        win.lock_screen.code.setText("1357")
        win.lock_screen.attempt()

        dialog = locking.setup(win)
        [off] = [b for b in dialog.buttons if b.text() == "Turn off"]
        dialog.fields["current"].setText("nope")
        off.click()
        self.assertIsNotNone(locking.saved(self.budget.home))  # not without the passcode
        dialog.fields["current"].setText("1357")
        off.click()
        self.assertIsNone(locking.saved(self.budget.home))
        self.assertFalse(win.away.timer.isActive())

    def test_it_can_be_found_on_the_accounts_tab(self):
        from PySide6.QtWidgets import QPushButton
        win = self.window()
        win.show_tab("Accounts")
        names = [b.text() for b in win.pages["Accounts"].widget().findChildren(QPushButton)]
        self.assertIn("Passcode", names)
