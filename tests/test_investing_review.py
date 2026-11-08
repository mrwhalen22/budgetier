"""Checking which rows in investing accounts are paid in and which are growth."""
from datetime import date
from pathlib import Path

from budgetier import analyze, views
from tests import fake
from tests.qt import QtCase
from tests.test_investments import with_investments


def odd_wording(budget):
    """A 401(k) whose bank words its contributions in a way that reads as activity."""
    budget.ledger.rows += [fake.row("ret-0004", date(2026, m, 20), f"PLAN FUNDING CREDIT {m:02d}", 40000) for m in (8, 9, 10)]
    budget.ledger.rows += [fake.row("ret-0004", date(2026, m, 21), "DIV", 120) for m in (8, 9)]
    budget.ledger.save()


class Grouping(QtCase):
    def test_rows_are_grouped_by_name_under_each_category(self):
        budget = with_investments(Path(self.dir) / "home")
        odd_wording(budget)
        win = self.window(budget)
        groups = views.investing_rows(win.snapshot)
        categories = [g.category for g in groups]
        self.assertEqual(categories, sorted(categories, key=analyze.INVESTING_CATEGORIES.index))
        funding = next(g for g in groups if g.merchant == "Plan Funding Credit")
        self.assertEqual((funding.category, funding.count, funding.total), (analyze.ACTIVITY, 3, 120000))
        self.assertEqual(funding.descriptions[0], "PLAN FUNDING CREDIT 10")


class Reviewing(QtCase):
    def setUp(self):
        super().setUp()
        self.budget = with_investments(Path(self.dir) / "home")
        odd_wording(self.budget)
        self.win = self.window(self.budget)

    def open(self):
        from budgetier.ui import investing
        return investing.review(self.win)

    def set(self, dialog, merchant, category):
        [box] = [box for group, box in dialog.rows if group.merchant == merchant]
        box.setCurrentIndex(box.findData(category))

    def test_a_change_saves_a_rule_in_the_banks_wording(self):
        dialog = self.open()
        self.set(dialog, "Plan Funding Credit", analyze.CONTRIBUTED)
        dialog.main.click()
        self.assertIn("PLAN FUNDING CREDIT", [r["text"] for r in self.budget.rules()])
        moved = [t for t in self.win.snapshot.txns if t.description.startswith("PLAN FUNDING")]
        self.assertEqual({t.category for t in moved}, {analyze.CONTRIBUTED})
        self.assertEqual(self.win.toast.words, "Saved 1 change.")

    def test_short_wording_changes_only_those_rows(self):
        dialog = self.open()
        self.set(dialog, "Div", analyze.CONTRIBUTED)
        dialog.main.click()
        self.assertNotIn("DIV", [r["text"] for r in self.budget.rules()])  # it would catch DIVINE PIZZA in checking
        self.assertEqual(len(self.budget.edits()), 2)
        self.assertEqual({t.category for t in self.win.snapshot.txns if t.description == "DIV"}, {analyze.CONTRIBUTED})

    def test_it_can_all_be_undone(self):
        dialog = self.open()
        self.set(dialog, "Plan Funding Credit", analyze.CONTRIBUTED)
        self.set(dialog, "Div", analyze.WITHDRAWN)
        dialog.main.click()
        self.win.toast.act()
        self.assertEqual(self.budget.edits(), {})
        self.assertNotIn("PLAN FUNDING CREDIT", [r["text"] for r in self.budget.rules()])

    def test_saving_with_nothing_changed_just_closes(self):
        dialog = self.open()
        rules = self.budget.rules()
        dialog.main.click()
        self.assertFalse(dialog.isVisible())
        self.assertEqual(self.budget.rules(), rules)

    def test_the_investments_tab_offers_it(self):
        from PySide6.QtWidgets import QPushButton
        self.win.show_tab("Investments")
        [check] = [b for b in self.win.pages["Investments"].widget().findChildren(QPushButton)
                   if b.text() == "Check what counts as paid in"]
        check.click()
        from budgetier.ui.dialogs import Dialog
        shown = [d for d in self.win.findChildren(Dialog) if d.isVisible() and d.windowTitle() == "Check what counts as paid in"]
        self.assertEqual(len(shown), 1)


class AfterMarkingAnAccount(QtCase):
    def test_marking_an_account_as_investing_opens_it(self):
        from budgetier.ui.tabs import accounts
        budget = fake.build(Path(self.dir) / "home")
        win = self.window(budget)
        account = win.snapshot.by_id["sav-0003"]
        dialog = accounts.edit_account(win, account)
        [kind] = [w for w in dialog.findChildren(type(win.range_box)) if w.accessibleName() == "Type"]
        kind.setCurrentIndex(kind.findData("investment"))
        dialog.main.click()
        from budgetier.ui.dialogs import Dialog
        shown = [d for d in win.findChildren(Dialog) if d.isVisible() and d.windowTitle() == "Check what counts as paid in"]
        self.assertEqual(len(shown), 1)
        self.assertTrue(all(g.txns[0].account == "sav-0003" for g, _ in shown[0].rows))
