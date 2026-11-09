"""Notes and tags on transactions: kept by the transaction's key, found by search, and added up
by tag across categories."""
import json
from pathlib import Path

from budgetier import analyze, export, views
from tests import fake
from tests.qt import QtCase
from tests.support import Tmp


class Tagging(Tmp):
    def setUp(self):
        super().setUp()
        self.budget = fake.build(Path(self.dir) / "home")

    def snapshot(self):
        return views.from_budget(self.budget)

    def tx(self, s, text, month="2026-03"):
        return next(t for t in s.txns if t.description == text and t.month == month)

    def note(self, text, note, tags, month="2026-03"):
        s = self.snapshot()
        self.budget.save_note(views.edit_target(s, self.tx(s, text, month)), note, tags)

    def test_a_note_and_tags_stay_with_their_transaction(self):
        self.note("DELTA AIR 0062", "  Flights for the trip ", "#Japan trip, japan TRIP, Travel ,")
        t = self.tx(self.snapshot(), "DELTA AIR 0062")
        self.assertEqual((t.note, t.tags), ("Flights for the trip", ("Japan trip", "Travel")))
        other = self.tx(self.snapshot(), "NETFLIX.COM")
        self.assertEqual((other.note, other.tags), ("", ()))

    def test_clearing_both_removes_it(self):
        self.note("DELTA AIR 0062", "x", "")
        self.note("DELTA AIR 0062", "  ", " , ")
        self.assertEqual(self.budget.notes(), {})

    def test_search_finds_notes_and_hash_finds_tags_only(self):
        self.note("DELTA AIR 0062", "flights", "Japan")
        self.note("KROGER #123", "snacks for japan", "", month="2026-03")
        s = self.snapshot()
        everything = views.Choice("all")
        self.assertEqual([t.description for t in views.transactions(s, everything, "#japan").txns], ["DELTA AIR 0062"])
        self.assertEqual(sorted(t.description for t in views.transactions(s, everything, "japan").txns),
                         ["KROGER #123"])
        self.assertEqual([t.description for t in views.transactions(s, everything, "flights").txns], ["DELTA AIR 0062"])

    def test_a_tag_adds_up_across_categories(self):
        self.note("DELTA AIR 0062", "", "Japan")
        self.note("KROGER #123", "", "JAPAN")  # the same tag, however it's typed
        [japan] = views.tags(self.snapshot(), views.Choice("all"))
        kroger = -self.tx(self.snapshot(), "KROGER #123").cents
        self.assertEqual((japan.tag.lower(), japan.count), ("japan", 2))
        self.assertEqual(japan.spent, 68430 + kroger)
        self.assertEqual([c for c, _ in japan.categories], ["Travel", "Groceries"])
        self.assertEqual(len(views.all_tags(self.snapshot())), 1)  # one spelling to pick from

    def test_a_split_keeps_its_note_on_every_part(self):
        s = self.snapshot()
        tx = next(t for t in s.txns if t.description == "BEST BUY 00123")
        self.budget.save_split(views.edit_target(s, tx), tx.whole,
                               [{"category": "Shopping", "amount": "1000"}, {"category": "Gifts & Donations", "amount": "299.99"}])
        s = self.snapshot()
        part = next(t for t in s.txns if t.description == "BEST BUY 00123")
        self.budget.save_note(views.edit_target(s, part), "TV and a gift", "Holidays")
        parts = [t for t in self.snapshot().txns if t.description == "BEST BUY 00123"]
        self.assertEqual([(t.note, t.tags) for t in parts], [("TV and a gift", ("Holidays",))] * 2)

    def test_undone_and_exported(self):
        s = self.snapshot()
        tx = self.tx(s, "DELTA AIR 0062")
        self.budget.undoable(self.budget.save_note, views.edit_target(s, tx), "flights", "=SUM(A1)")
        t = self.tx(self.snapshot(), "DELTA AIR 0062")
        text = export.csv_text([t], {})
        self.assertIn("flights", text)
        self.assertIn("'=SUM(A1)", text.replace('"', ""))  # a tag can't run as a formula either
        self.budget.undo()
        self.assertEqual(self.budget.notes(), {})

    def test_what_cant_be_read_is_set_aside(self):
        self.budget.notes_path.write_text(json.dumps({"k": {"note": 5}, "j": {"note": "", "tags": []}}), encoding="utf-8")
        self.assertEqual(self.budget.notes(), {})
        self.assertFalse(analyze.valid_note({"note": "x" * (analyze.NOTE_LONGEST + 1)}))


class OnScreen(QtCase):
    def test_adding_a_note_from_the_edit_dialog(self):
        from budgetier.ui.dialogs import Dialog
        from budgetier.ui.tabs.transactions import Transactions
        win = self.window()
        win.show_tab("Transactions")
        [tab] = win.pages["Transactions"].widget().findChildren(Transactions)
        tab.query.setText("delta")
        tab.table.cellClicked.emit(0, 1)
        [button] = [b for b in win.editing.dialog.buttons if b.text() == "Add note"]
        button.click()
        [dialog] = [d for d in win.findChildren(Dialog) if d.isVisible() and d.windowTitle() == "Note and tags"]
        dialog.note_fields["note"].setPlainText("Flights")
        dialog.note_fields["tags"].setText("Japan")
        dialog.main.click()
        self.assertEqual(win.toast.words, "Note saved.")
        [tab] = win.pages["Transactions"].widget().findChildren(Transactions)
        self.assertEqual(tab.table.item(0, 1).text(), "Delta Air  #Japan")
        self.assertIn("note", tab.table.item(0, 2).text())

    def test_the_spending_tab_lists_tags(self):
        from PySide6.QtWidgets import QLabel
        s = views.from_budget(self.budget)
        tx = next(t for t in s.txns if t.description == "DELTA AIR 0062")
        self.budget.save_note(views.edit_target(s, tx), "", "Japan")
        win = self.window()
        win.show_tab("Spending")
        words = [label.text() for label in win.pages["Spending"].widget().findChildren(QLabel)]
        self.assertIn("Tags", words)
