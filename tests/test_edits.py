"""The Qt window's Transactions and Rules tabs, changing one transaction, and the categorize queue.

These save through the real Budget into a made-up data folder, so they check what was saved.
"""
import unittest
from datetime import date
from pathlib import Path

from tests.fake import UNSORTED, build
from tests.qt import QtCase


class Editing(QtCase):
    def setUp(self):
        super().setUp()
        self.win = self.window()

    @property
    def dialog(self):
        return self.win.editing.dialog

    def transactions(self):
        from budgetier.ui.tabs.transactions import Transactions
        self.win.show_tab("Transactions")
        [tab] = self.win.pages["Transactions"].widget().findChildren(Transactions)
        return tab

    def open_row(self, merchant: str):
        tab = self.transactions()
        tab.query.setText(merchant)
        tab.table.cellClicked.emit(0, 1)
        self.assertTrue(self.dialog.isVisible())
        return self.dialog

    def choose(self, category: str):
        box = self.dialog.category
        self.assertGreaterEqual(box.findData(category), 0, f"{category} isn't on the list")
        box.setCurrentIndex(box.findData(category))
        box.activated.emit(box.currentIndex())

    def save(self):
        self.dialog.main.click()

    def toast(self) -> str:
        return self.win.toast.text() if self.win.toast.isVisible() else ""

    def panel(self) -> str:
        from PySide6.QtWidgets import QLabel
        return " ".join(label.text() for label in self.dialog.panel.findChildren(QLabel))


class TransactionsTab(Editing):
    def test_newest_first_with_a_count(self):
        tab = self.transactions()
        self.assertEqual(tab.found[0].date, max(t.date for t in tab.found))
        self.assertRegex(tab.count.text(), r"^[\d,]+ transactions, net -?\$")

    def test_search_and_clear(self):
        tab = self.transactions()
        self.assertFalse(tab.clear.isVisibleTo(tab))
        tab.query.setText("kroger")
        self.assertEqual({t.merchant for t in tab.found}, {"Kroger"})
        self.assertTrue(tab.clear.isVisibleTo(tab))
        tab.clear.click()
        self.assertEqual(tab.query.text(), "")
        self.assertGreater(len(tab.found), 20)

    def test_category_and_kind_filters_combine(self):
        tab = self.transactions()
        tab.category.activated.emit(tab.category.findData("Groceries"))
        tab.kind.activated.emit(tab.kind.findData("expense"))
        self.assertTrue(tab.found)
        self.assertTrue(all(t.category == "Groceries" and t.kind == "expense" for t in tab.found))

    def test_a_heading_sorts_and_again_reverses(self):
        tab = self.transactions()
        tab.table.horizontalHeader().sectionClicked.emit(4)
        amounts = [t.cents for t in tab.found]
        self.assertEqual(amounts, sorted(amounts))
        tab.table.horizontalHeader().sectionClicked.emit(4)
        self.assertEqual([t.cents for t in tab.found], sorted(amounts, reverse=True))

    def test_show_more(self):
        rows = [{"date": date(2026, 1, 1 + d % 28), "account": "chk-0001", "description": f"SHOP {d}", "amount": "-1.00",
                 "cents": -100, "balance": None, "bank_category": "", "source": "x", "sync_id": ""} for d in range(260)]
        self.win = self.window(build(Path(self.dir) / "many", rows))
        tab = self.transactions()
        self.assertEqual(tab.table.rowCount(), 200)
        self.assertTrue(tab.more.isVisibleTo(tab))
        tab.more.click()
        self.assertEqual(tab.table.rowCount(), 260)
        self.assertFalse(tab.more.isVisibleTo(tab))

    def test_a_category_chosen_elsewhere_is_the_filter(self):
        self.win.open_transactions(category="Housing")
        tab = self.transactions()
        self.assertEqual(tab.category.currentData(), "Housing")
        self.assertEqual({t.category for t in tab.found}, {"Housing"})


class OneTransaction(Editing):
    def test_everything_that_matches_is_the_default(self):
        dialog = self.open_row("kroger")
        self.assertTrue(dialog.all.isChecked())
        self.assertTrue(dialog.match_box.isVisibleTo(dialog))
        self.assertEqual(dialog.desc.text()[:6], "KROGER")

    def test_just_this_one_hides_the_matching_text(self):
        dialog = self.open_row("kroger")
        dialog.one.setChecked(True)
        self.assertFalse(dialog.match_box.isVisibleTo(dialog))
        self.assertIn("only this transaction", dialog.lead.text())

    def test_saving_just_this_one_changes_only_it(self):
        dialog = self.open_row("best buy")
        dialog.one.setChecked(True)
        self.choose("Gifts & Donations")
        dialog.name.setText("One Off")
        rules_before = len(self.win.snapshot.rules)
        self.save()
        self.assertEqual(self.toast(), "Saved. Nothing else changed.")
        self.assertFalse(self.dialog)
        self.assertEqual([e["merchant"] for e in self.budget.edits().values()], ["One Off"])
        changed = [t for t in self.win.snapshot.txns if t.edited]
        self.assertEqual([(t.merchant, t.category) for t in changed], [("One Off", "Gifts & Donations")])
        self.assertEqual(len(self.win.snapshot.rules), rules_before)

    def test_an_edited_row_opens_as_itself_and_can_be_undone(self):
        dialog = self.open_row("best buy")
        dialog.one.setChecked(True)
        self.choose("Gifts & Donations")
        dialog.name.setText("One Off")
        self.save()
        dialog = self.open_row("one off")
        self.assertTrue(dialog.one.isChecked())
        self.assertEqual(dialog.name.text(), "One Off")
        undo = next(b for b in dialog.buttons if b.text() == "Undo change")
        undo.click()
        self.assertEqual(self.toast(), "Change undone.")
        self.assertEqual(self.budget.edits(), {})

    def test_a_rule_from_a_row_covers_everything_like_it(self):
        dialog = self.open_row("qqq")
        self.assertEqual(dialog.match.text(), "QQQ WIDGETS")
        self.choose("Shopping")
        self.save()
        self.assertEqual(self.toast(), "Rule saved. It matches 1 transaction.")
        self.assertIn("QQQ WIDGETS", [r["text"] for r in self.win.snapshot.rules])

    def test_the_preview_says_what_a_rule_would_match(self):
        dialog = self.open_row("kroger")
        dialog.match.setText("KROGER")
        dialog.preview()
        self.assertRegex(self.panel(), r"\d+ transactions match, totalling")
        dialog.match.setText("NOTHING LIKE THIS")
        dialog.preview()
        self.assertIn("No transactions match yet.", self.panel())

    def test_a_rule_needs_a_category(self):
        self.win.editing.new_rule()
        self.dialog.match.setText("SOMETHING")
        self.save()
        self.assertEqual(self.dialog.error.text(), "Choose a category.")
        self.assertTrue(self.dialog.isVisible())

    def test_a_new_category(self):
        self.win.editing.new_rule()
        self.choose("__new")
        self.assertTrue(self.dialog.new_box.isVisibleTo(self.dialog))
        self.dialog.new.setText("Hobbies")
        self.dialog.match.setText("DELTA AIR")
        self.save()
        self.assertIn("Hobbies", [r["category"] for r in self.win.snapshot.rules])

    def test_escape_cancels_and_enter_saves(self):
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        dialog = self.open_row("qqq")
        QTest.keyClick(dialog, Qt.Key_Escape)
        self.assertFalse(dialog.isVisible())
        dialog = self.open_row("qqq")
        self.choose("Shopping")
        dialog.name.setFocus()
        QTest.keyClick(dialog.name, Qt.Key_Return)
        self.assertEqual(self.toast(), "Rule saved. It matches 1 transaction.")

    def test_a_largest_row_opens_too(self):
        from budgetier.ui.widgets import Table
        self.win.show_tab("Largest")
        [table] = self.win.pages["Largest"].widget().findChildren(Table)
        table.cellClicked.emit(0, 0)
        self.assertTrue(self.dialog.isVisible())
        self.assertEqual(self.dialog.desc.text(), "BEST BUY 00123")

    def test_the_banks_words_show_as_text(self):
        from PySide6.QtCore import Qt
        text = "<img src=x> <b>SHOP</b>"
        rows = [{"date": date(2026, 1, 2), "account": "chk-0001", "description": text, "amount": "-5.00", "cents": -500,
                 "balance": None, "bank_category": "", "source": "x", "sync_id": ""}]
        self.win = self.window(build(Path(self.dir) / "hostile", rows))
        self.win.editing.categorize(self.win.snapshot.txns[0])
        self.assertEqual(self.dialog.desc.textFormat(), Qt.PlainText)
        self.assertEqual(self.dialog.desc.text(), text)


class Queue(Editing):
    def start(self):
        self.win.show_tab("Rules")
        self.names = [u.merchant for u in __import__("budgetier.views", fromlist=["x"]).uncategorized(self.win.snapshot)]
        self.win.editing.start_queue(self.names[0])
        return self.dialog

    def test_it_shows_its_place(self):
        dialog = self.start()
        self.assertIn(f"1 of {len(UNSORTED)}", dialog.lead.text())
        self.assertEqual(dialog.main.text(), "Save and next")
        self.assertEqual(dialog.name.text(), self.names[0])

    def test_save_moves_on_without_redrawing(self):
        dialog = self.start()
        before = self.win.snapshot
        self.choose("Shopping")
        self.save()
        self.assertIs(self.dialog, dialog)
        self.assertEqual(dialog.name.text(), self.names[1])
        self.assertIn("That rule matches 1 transaction. 2 of", dialog.lead.text())
        self.assertEqual(dialog.category.currentData(), "")
        self.assertIs(self.win.snapshot, before)

    def test_it_passes_over_what_a_saved_rule_covered(self):
        dialog = self.start()
        second = next(t for t in self.win.snapshot.txns if t.merchant == self.names[1]).description
        dialog.match.setText(second)  # a rule for the next one, saved from the first
        self.choose("Shopping")
        self.save()
        self.assertEqual(dialog.name.text(), self.names[2])

    def test_skip_saves_nothing(self):
        dialog = self.start()
        rules = len(self.budget.rules())
        next(b for b in dialog.buttons if b.text() == "Skip").click()
        self.assertEqual(dialog.name.text(), self.names[1])
        self.assertEqual(len(self.budget.rules()), rules)

    def test_stopping_early_says_what_was_saved(self):
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        dialog = self.start()
        self.choose("Shopping")
        self.save()
        self.assertEqual(dialog.buttons[0].text(), "Done")
        QTest.keyClick(dialog, Qt.Key_Escape)
        self.assertFalse(dialog.isVisible())
        self.assertEqual(self.toast(), "Saved 1 rule.")

    def test_stopping_with_nothing_saved_just_closes(self):
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        dialog = self.start()
        before = self.win.snapshot
        QTest.keyClick(dialog, Qt.Key_Escape)
        self.assertFalse(dialog.isVisible())
        self.assertEqual(self.toast(), "")
        self.assertIs(self.win.snapshot, before)

    def test_the_last_one_saves_and_finishes(self):
        dialog = self.start()
        for _ in self.names[:-1]:
            next(b for b in dialog.buttons if b.text() == "Skip").click()
        self.assertEqual(dialog.main.text(), "Save")
        self.choose("Shopping")
        self.save()
        self.assertFalse(dialog.isVisible())
        self.assertEqual(self.toast(), "Saved 1 rule.")


class RulesTab(Editing):
    def rules_table(self):
        from budgetier.ui.widgets import Table
        self.win.show_tab("Rules")
        return self.win.pages["Rules"].widget().findChildren(Table)

    def test_both_lists_show(self):
        needing, yours = self.rules_table()
        self.assertEqual(needing.rowCount(), len(UNSORTED))
        self.assertEqual(yours.item(0, 0).text(), "KROGER")

    def test_editing_a_rule_starts_from_it(self):
        _, yours = self.rules_table()
        yours.cellClicked.emit(0, 0)
        self.assertEqual(self.dialog.heading.text(), "Edit rule")
        self.assertEqual(self.dialog.match.text(), "KROGER")
        self.assertEqual(self.dialog.category.currentData(), "Groceries")

    def test_removing_a_rule_asks_first(self):
        from budgetier.ui.dialogs import Dialog
        self.win.editing.remove_rule(self.win.snapshot.rules[0])
        [ask] = [d for d in self.win.findChildren(Dialog) if d.isVisible()]
        self.assertEqual(ask.heading.text(), "Remove this rule?")
        ask.buttons[-1].click()
        self.assertEqual(self.toast(), "Removed.")
        self.assertEqual(self.budget.rules(), [])


if __name__ == "__main__":
    unittest.main()
