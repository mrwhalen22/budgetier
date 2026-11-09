"""Splitting one transaction into parts with their own categories."""
from pathlib import Path

from budgetier import analyze, views
from budgetier.service import BudgetError
from tests import fake
from tests.qt import QtCase
from tests.support import ACCOUNTS, Tmp, row


class Parts(Tmp):
    ROWS = [row("card", 3, "COSTCO WHSE #1", -20000), row("card", 3, "COSTCO WHSE #1", -20000)]

    def key(self, n=0):
        return analyze.edit_keys(self.ROWS)[n]

    def test_a_split_stands_as_its_parts(self):
        splits = {self.key(0): {"parts": [{"category": "Groceries", "cents": 15000}, {"category": "Home", "cents": 5000}]}}
        out = analyze.classify(self.ROWS, ACCOUNTS, [], {}, splits)
        self.assertEqual([(r["category"], r["cents"], r["kind"]) for r in out],
                         [("Groceries", -15000, "expense"), ("Home", -5000, "expense"), ("Groceries", -20000, "expense")])
        self.assertTrue(out[0]["split"] and out[1]["split"] and not out[2].get("split"))
        self.assertEqual(out[0]["whole"], -20000)

    def test_a_refund_splits_the_same_way_round(self):
        rows = [row("card", 3, "COSTCO WHSE #1", 20000)]
        splits = {analyze.edit_keys(rows)[0]: {"parts": [{"category": "Groceries", "cents": 12000},
                                                         {"category": "Home", "cents": 8000}]}}
        out = analyze.classify(rows, ACCOUNTS, [], {}, splits)
        self.assertEqual([(r["cents"], r["kind"]) for r in out], [(12000, "refund"), (8000, "refund")])

    def test_a_split_that_no_longer_adds_up_is_left_out(self):
        splits = {self.key(0): {"parts": [{"category": "Groceries", "cents": 15000}, {"category": "Home", "cents": 4000}]}}
        out = analyze.classify(self.ROWS, ACCOUNTS, [], {}, splits)
        self.assertEqual(len(out), 2)

    def test_what_a_split_must_be(self):
        good = {"parts": [{"category": "A", "cents": 1}, {"category": "B", "cents": 2}]}
        self.assertTrue(analyze.valid_split(good))
        for bad in ({"parts": [{"category": "A", "cents": 1}]}, {"parts": [{"category": "", "cents": 1}, {"category": "B", "cents": 2}]},
                    {"parts": [{"category": "A", "cents": 0}, {"category": "B", "cents": 2}]},
                    {"parts": [{"category": "A", "cents": 1.5}, {"category": "B", "cents": 2}]}, "x", {}):
            self.assertFalse(analyze.valid_split(bad), bad)


class Saving(Tmp):
    def setUp(self):
        super().setUp()
        self.budget = fake.build(Path(self.dir) / "home")
        self.s = views.from_budget(self.budget)
        self.tx = next(t for t in self.s.txns if t.description == "BEST BUY 00123")

    def save(self, *parts):
        self.budget.save_split(views.edit_target(self.s, self.tx), self.tx.whole,
                               [{"category": c, "amount": a} for c, a in parts])

    def test_parts_must_come_to_the_whole(self):
        with self.assertRaises(BudgetError) as e:
            self.save(("Shopping", "1000"), ("Gifts & Donations", "200"))
        self.assertIn("short by $99.99", str(e.exception))
        with self.assertRaises(BudgetError):
            self.save(("Shopping", "1299.99"))  # one part isn't a split
        with self.assertRaises(BudgetError):
            self.save(("", "1000"), ("Shopping", "299.99"))

    def test_a_saved_split_shows_as_parts_and_empty_lines_are_skipped(self):
        self.save(("Shopping", "1000"), ("", ""), ("Gifts & Donations", "299.99"))
        s = views.from_budget(self.budget)
        parts = [t for t in s.txns if t.description == "BEST BUY 00123"]
        self.assertEqual([(t.category, t.cents, t.split) for t in parts],
                         [("Shopping", -100000, True), ("Gifts & Donations", -29999, True)])
        self.assertEqual(views.spending(s, views.Choice("all")).categories[0][0], "Housing")
        self.budget.clear_split(views.edit_target(s, parts[1]))  # either part finds the whole
        self.assertEqual(len([t for t in views.from_budget(self.budget).txns if t.description == "BEST BUY 00123"]), 1)

    def test_one_category_for_all_of_it_replaces_the_split(self):
        self.save(("Shopping", "1000"), ("Gifts & Donations", "299.99"))
        s = views.from_budget(self.budget)
        part = next(t for t in s.txns if t.description == "BEST BUY 00123")
        self.budget.save_edit(views.edit_target(s, part), "Gifts & Donations", "")
        self.assertEqual(self.budget.splits(), {})
        whole = [t for t in views.from_budget(self.budget).txns if t.description == "BEST BUY 00123"]
        self.assertEqual([(t.category, t.cents) for t in whole], [("Gifts & Donations", -129999)])

    def test_it_can_be_undone(self):
        self.budget.undoable(self.save, ("Shopping", "1000"), ("Gifts & Donations", "299.99"))
        self.budget.undo()
        self.assertEqual(self.budget.splits(), {})


class TheDialog(QtCase):
    def open(self, win):
        from budgetier.ui.splitting import split
        tx = next(t for t in win.snapshot.txns if t.description == "BEST BUY 00123")
        return split(win, tx)

    def test_splitting_from_the_dialog(self):
        win = self.window()
        dialog = self.open(win)
        first, second = dialog.parts
        self.assertEqual(first.amount.text(), "1299.99")
        first.amount.setText("1000")
        second.category.setCurrentIndex(second.category.findData("Gifts & Donations"))
        second.amount.setText("299.99")
        dialog.main.click()
        parts = [t for t in win.snapshot.txns if t.description == "BEST BUY 00123"]
        self.assertEqual(len(parts), 2)
        self.assertEqual(win.toast.words, "Split into 2 parts.")
        self.assertEqual(win.toast.action[0], "Undo")

    def test_what_doesnt_add_up_says_so_and_saves_nothing(self):
        win = self.window()
        dialog = self.open(win)
        first, second = dialog.parts
        second.category.setCurrentIndex(second.category.findData("Gifts & Donations"))
        second.amount.setText("10")
        dialog.main.click()
        self.assertTrue(dialog.isVisible())
        self.assertEqual(self.budget.splits(), {})

    def test_a_part_can_be_added_with_whats_left(self):
        from PySide6.QtWidgets import QPushButton
        win = self.window()
        dialog = self.open(win)
        dialog.parts[0].amount.setText("1000")
        [add] = [b for b in dialog.findChildren(QPushButton) if b.text() == "Add a part"]
        add.click()
        self.assertEqual(len(dialog.parts), 3)
        self.assertEqual(dialog.parts[2].amount.text(), "299.99")
        dialog.dismiss()

    def test_a_split_one_opens_with_its_parts_and_can_be_undone(self):
        win = self.window()
        s = win.snapshot
        tx = next(t for t in s.txns if t.description == "BEST BUY 00123")
        self.budget.save_split(views.edit_target(s, tx), tx.whole,
                               [{"category": "Shopping", "amount": "1000"}, {"category": "Home", "amount": "299.99"}])
        win.changed()
        dialog = self.open(win)
        self.assertEqual([p.value()["category"] for p in dialog.parts], ["Shopping", "Home"])
        [undo] = [b for b in dialog.buttons if b.text() == "Undo split"]
        undo.click()
        self.assertEqual(len([t for t in win.snapshot.txns if t.description == "BEST BUY 00123"]), 1)

    def test_the_edit_dialog_offers_it(self):
        from budgetier.ui.tabs.transactions import Transactions
        win = self.window()
        win.show_tab("Transactions")
        [tab] = win.pages["Transactions"].widget().findChildren(Transactions)
        tab.query.setText("best buy")
        tab.table.cellClicked.emit(0, 1)
        [button] = [b for b in win.editing.dialog.buttons if b.text() == "Split"]
        button.click()
        from budgetier.ui.dialogs import Dialog
        shown = [d for d in win.findChildren(Dialog) if d.isVisible() and d.windowTitle() == "Split this transaction"]
        self.assertEqual(len(shown), 1)
