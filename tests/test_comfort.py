"""The window stays usable while it reads changes, opens where you left it, and answers the keyboard."""
from pathlib import Path
from unittest import mock

from budgetier import views
from tests import fake
from tests.qt import QtCase

try:
    from PySide6.QtCore import Qt
except ImportError:  # the tests skip themselves without Qt
    pass


class ReadingInTheBackground(QtCase):
    def targets(self, win):
        return {t["category"]: t["value"] for t in win.snapshot.budget_targets}

    def test_a_change_is_read_while_the_window_stays_usable(self):
        win = self.window(background=True)
        self.budget.save_budget("Groceries", "amount", "400")
        win.changed("Budget saved.")
        self.assertTrue(win.loading)
        self.assertNotIn("Groceries", self.targets(win))  # still the numbers as they were
        win.show_tab("Spending")  # and the window still answers
        self.assertTrue(win.runner.wait())
        self.assertFalse(win.loading)
        self.assertEqual(self.targets(win)["Groceries"], 40000)
        self.assertFalse(win.busy_note.isVisible())

    def test_changes_made_while_reading_are_read_together(self):
        win = self.window(background=True)
        with mock.patch.object(views, "from_budget", wraps=views.from_budget) as read:
            for amount in ("100", "200", "300"):
                self.budget.save_budget("Groceries", "amount", amount)
                win.changed()
            self.assertTrue(win.runner.wait())
        self.assertLessEqual(read.call_count, 2)  # the first, then once for everything after it
        self.assertEqual(self.targets(win)["Groceries"], 30000)

    def test_a_read_that_trips_up_is_done_again_on_the_window(self):
        win = self.window(background=True)
        self.budget.save_budget("Groceries", "amount", "250")
        real = views.from_budget
        with mock.patch.object(views, "from_budget", side_effect=[RuntimeError("changed size during iteration"), real(self.budget)]):
            with self.assertLogs("budgetier", "ERROR"):
                win.changed()
                self.assertTrue(win.runner.wait())
        self.assertEqual(self.targets(win)["Groceries"], 25000)

    def test_the_first_read_happens_before_the_window_shows(self):
        win = self.window(background=True)
        self.assertFalse(win.loading)
        self.assertTrue(win.snapshot.txns)


class OpensWhereYouLeftIt(QtCase):
    def test_the_tab_period_accounts_and_size_come_back(self):
        from budgetier.ui import settings
        from budgetier.ui.app import Window
        win = self.window()
        win.show_tab("Savings")
        win.choose(views.Choice("2025", frozenset({"card-0002"})))
        win.close()
        saved = settings.load(self.budget.home)["window"]["geometry"]
        with mock.patch.object(Window, "restoreGeometry") as restored:
            again = self.window()
        self.assertEqual(bytes(restored.call_args.args[0].toBase64()).decode(), saved)  # Qt fits it to the screens there are
        self.assertEqual(again.tab, "Savings")
        self.assertEqual(again.choice, views.Choice("2025", frozenset({"card-0002"})))
        self.assertEqual(again.range_box.currentData(), "2025")
        self.assertEqual(again.accounts_button.text(), "1 of 3 accounts")

    def test_whats_gone_since_is_left_out(self):
        from budgetier.ui import settings
        settings.save(self.budget.home, window={"tab": "Nowhere", "range": "1999", "accounts": ["gone-0009", 5],
                                                "geometry": "not base64!"})
        win = self.window()
        self.assertEqual((win.tab, win.choice), ("Overview", views.Choice("12")))

    def test_junk_starts_a_new_window(self):
        from budgetier.ui import settings
        for junk in ("junk", ["a"], {"tab": 3, "range": None, "accounts": "x", "geometry": 7}):
            settings.save(self.budget.home, window=junk)
            win = self.window()
            self.assertEqual((win.tab, win.choice), ("Overview", views.Choice("12")))

    def test_a_new_data_folder_starts_on_the_overview(self):
        win = self.window(fake.build(Path(self.dir) / "fresh"))
        self.assertEqual(win.tab, "Overview")


class Shortcuts(QtCase):
    def setUp(self):
        super().setUp()
        self.win = self.window()
        self.win.activateWindow()

    def press(self, key, modifier=None):
        from PySide6.QtTest import QTest
        QTest.keyClick(self.win.stack, key, modifier if modifier is not None else Qt.NoModifier)
        self.app.processEvents()

    def test_numbers_show_tabs(self):
        from budgetier.ui.app import TABS
        self.press(Qt.Key_3, Qt.ControlModifier)
        self.assertEqual(self.win.tab, TABS[2])
        self.press(Qt.Key_9, Qt.ControlModifier)
        self.assertEqual(self.win.tab, TABS[8])

    def test_find_opens_transactions_with_the_search_ready(self):
        self.win.find()
        self.assertEqual(self.win.tab, "Transactions")
        from PySide6.QtWidgets import QLineEdit
        [search] = self.win.pages["Transactions"].widget().findChildren(QLineEdit, "search")
        self.assertTrue(search.hasFocus())

    def test_f1_is_help_and_the_rest_do_what_their_buttons_do(self):
        self.press(Qt.Key_F1)
        self.assertEqual(self.win.tab, "Help")
        with mock.patch.object(self.win.importing, "add_files") as add, mock.patch.object(self.win.banking, "act") as sync:
            self.press(Qt.Key_I, Qt.ControlModifier)
            self.press(Qt.Key_R, Qt.ControlModifier)
        add.assert_called_once()
        sync.assert_called_once()

    def test_a_dialog_keeps_them_from_firing_behind_it(self):
        from budgetier.ui.dialogs import Dialog
        dialog = Dialog(self.win, "Something")
        dialog.open()
        self.app.processEvents()
        from PySide6.QtTest import QTest
        QTest.keyClick(dialog, Qt.Key_3, Qt.ControlModifier)
        self.assertEqual(self.win.tab, "Overview")
        dialog.dismiss()

    def test_they_are_shown_where_they_apply(self):
        from budgetier.ui import keys
        self.assertEqual(self.win.tab_buttons["Spending"].toolTip(), keys.shown("Ctrl+2"))
        self.assertEqual(self.win.add_button.toolTip(), keys.shown("Ctrl+I"))
        self.win.show_tab("Help")
        from budgetier.ui.widgets import Table
        tables = self.win.pages["Help"].widget().findChildren(Table)
        listed = [tables[-1].item(r, 0).text() for r in range(tables[-1].rowCount())]
        self.assertIn("Find a transaction", listed)
        self.assertIn("Sync banks", listed)
