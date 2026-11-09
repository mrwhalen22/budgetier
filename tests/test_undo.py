"""Undo: the last small change can be put back, from the note at the bottom or with Ctrl+Z."""
from pathlib import Path

from budgetier.service import BudgetError
from tests import fake
from tests.qt import QtCase
from tests.support import Tmp

try:
    from PySide6.QtCore import Qt
except ImportError:  # the tests skip themselves without Qt
    pass


class PuttingBack(Tmp):
    def setUp(self):
        super().setUp()
        self.budget = fake.build(Path(self.dir) / "home")

    def test_a_budget_comes_back_as_it_was(self):
        self.budget.undoable(self.budget.save_budget, "Dining", "amount", "450")
        self.assertEqual(self.budget.budgets()["Dining"]["value"], 45000)
        self.budget.undo()
        self.assertEqual(self.budget.budgets()["Dining"]["value"], 30000)
        self.assertFalse(self.budget.can_undo())

    def test_a_file_that_didnt_exist_goes_again(self):
        self.budget.edits_path.unlink(missing_ok=True)
        tx = next(r for r in self.budget.ledger.rows if r["description"] == "NETFLIX.COM")
        self.budget.undoable(self.budget.save_edit, {**tx, "n": 0}, "Entertainment", "")
        self.assertTrue(self.budget.edits_path.exists())
        self.budget.undo()
        self.assertFalse(self.budget.edits_path.exists())

    def test_account_details_come_back_in_the_open_ledger_too(self):
        self.budget.undoable(self.budget.update_account, "sav-0003", "Rainy Day", "retirement", "", "")
        self.assertEqual(self.budget.ledger.accounts["sav-0003"]["type"], "retirement")
        self.budget.undo()
        self.assertEqual(self.budget.ledger.accounts["sav-0003"]["name"], "Bank Savings 0003")
        self.assertEqual(self.budget.ledger.accounts["sav-0003"]["type"], "savings")

    def test_a_newer_change_is_never_lost_to_an_undo(self):
        self.budget.undoable(self.budget.save_budget, "Dining", "amount", "450")
        self.budget.save_budget("Groceries", "amount", "600")  # not through undoable: something else
        with self.assertRaises(BudgetError):
            self.budget.undo()
        self.assertIn("Groceries", self.budget.budgets())
        self.assertFalse(self.budget.can_undo())

    def test_a_change_that_changes_nothing_has_nothing_to_undo(self):
        with self.assertRaises(BudgetError):
            self.budget.undo()
        self.budget.undoable(self.budget.save_budget, "Dining", "amount", "300")  # as it already was
        self.assertFalse(self.budget.can_undo())

    def test_a_failed_change_leaves_the_last_undo_alone(self):
        self.budget.undoable(self.budget.save_budget, "Dining", "amount", "450")
        with self.assertRaises(BudgetError):
            self.budget.undoable(self.budget.save_budget, "Dining", "amount", "nope")
        self.budget.undo()
        self.assertEqual(self.budget.budgets()["Dining"]["value"], 30000)


class FromTheWindow(QtCase):
    def setUp(self):
        super().setUp()
        self.win = self.window()

    def dining(self):
        return {t["category"]: t["value"] for t in self.win.snapshot.budget_targets}["Dining"]

    def change(self):
        self.budget.undoable(self.budget.save_budget, "Dining", "amount", "450")
        self.win.changed("Budget saved.", undo=True)

    def test_the_note_offers_undo_and_it_works(self):
        self.change()
        self.assertEqual(self.dining(), 45000)
        self.assertEqual(self.win.toast.action[0], "Undo")
        self.assertIn("Undo", self.win.toast.text())
        self.win.toast.act()
        self.assertEqual(self.dining(), 30000)
        self.assertEqual(self.win.toast.words, "Undone.")
        self.assertIsNone(self.win.toast.action)  # an undo isn't itself offered for undoing

    def test_ctrl_z_does_the_same(self):
        from PySide6.QtTest import QTest
        self.change()
        self.win.activateWindow()
        QTest.keyClick(self.win.stack, Qt.Key_Z, Qt.ControlModifier)
        self.assertEqual(self.dining(), 30000)
        QTest.keyClick(self.win.stack, Qt.Key_Z, Qt.ControlModifier)
        self.assertEqual(self.win.toast.words, "There's nothing to undo.")

    def test_a_note_that_cant_be_undone_offers_nothing(self):
        self.win.changed("Removed.")
        self.assertIsNone(self.win.toast.action)
        self.assertEqual(self.win.toast.text(), "Removed.")

    def test_words_beside_the_link_are_only_text(self):
        self.change()
        self.win.toast.say("<img src=x> <b>SHOP</b> saved.", ("Undo", lambda: None))
        self.assertIn("&lt;img src=x&gt;", self.win.toast.text())
        self.assertNotIn("<b>", self.win.toast.text())

    def test_changing_a_transaction_in_its_dialog_can_be_undone(self):
        from budgetier.ui.tabs.transactions import Transactions
        self.win.show_tab("Transactions")
        [tab] = self.win.pages["Transactions"].widget().findChildren(Transactions)
        tab.query.setText("best buy")
        tab.table.cellClicked.emit(0, 1)
        dialog = self.win.editing.dialog
        dialog.one.setChecked(True)
        box = dialog.category
        box.setCurrentIndex(box.findData("Gifts & Donations"))
        box.activated.emit(box.currentIndex())
        dialog.main.click()
        self.assertEqual(self.win.toast.action[0], "Undo")
        self.assertTrue(any(t.edited for t in self.win.snapshot.txns))
        self.win.toast.act()
        self.assertFalse(any(t.edited for t in self.win.snapshot.txns))
        self.assertEqual(self.budget.edits(), {})
