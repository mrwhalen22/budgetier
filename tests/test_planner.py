"""The budget guide: a rule of thumb's split of income beside yours, and budgets suggested
from what's really spent, trimmed only as far as the rule's savings share needs."""
from datetime import date
from pathlib import Path

from budgetier import analyze, sample, views
from budgetier.storage import BudgetError
from budgetier.ui import planner, settings
from tests.qt import QtCase
from tests.support import Tmp

TODAY = date(2026, 11, 9)


def made(home: Path, extra_shopping: int = 0):
    """The sample's year and a half, with more spent on shopping each month if asked."""
    budget = sample.build(home, TODAY)
    if extra_shopping:
        y, m = 2025, 5
        while (y, m) < (2026, 11):
            budget.ledger.rows.append({"date": date(y, m, 12), "account": sample.CARD, "description": "BIG BOX STORE",
                                       "amount": f"-{extra_shopping / 100:.2f}", "cents": -extra_shopping, "balance": None,
                                       "bank_category": "", "source": "made-up.csv", "sync_id": ""})
            y, m = (y + 1, 1) if m == 12 else (y, m + 1)
        budget.ledger.save()
        budget.save_rule(None, "BIG BOX STORE", "Shopping", "Big Box")
    return budget


class TheNumbers(Tmp):
    def test_the_rule_splits_income_and_sets_beside_what_is_spent(self):
        p = views.plan(views.from_budget(made(Path(self.dir) / "h")))
        self.assertEqual(p.rule, "50/30/20")
        self.assertGreater(p.income, 0)
        self.assertEqual([g.name for g in p.groups], ["Needs", "Wants", "Savings"])
        self.assertEqual([g.share for g in p.groups], [50, 30, 20])
        needs, wants, keep = p.groups
        self.assertAlmostEqual(needs.target + wants.target + keep.target, p.income, delta=2)
        self.assertEqual(keep.actual, p.income - needs.actual - wants.actual)
        for line in p.lines:
            self.assertNotIn(line.category, analyze.NOT_BUDGETED)
            self.assertEqual(line.need, line.category in views.NEEDS)
            self.assertEqual(line.suggested % 500, 0)  # a round number

    def test_keeping_enough_already_means_nothing_is_trimmed(self):
        p = views.plan(views.from_budget(made(Path(self.dir) / "h")))
        self.assertGreaterEqual(p.groups[2].actual, p.groups[2].target)  # the sample keeps about a third
        for line in p.lines:
            self.assertGreaterEqual(line.suggested, line.average, line.category)
        self.assertEqual(p.over, 0)

    def test_keeping_too_little_trims_wants_first_and_never_bills(self):
        s = views.from_budget(made(Path(self.dir) / "h", extra_shopping=160000))
        p = views.plan(s)
        self.assertLess(p.groups[2].actual, p.groups[2].target)
        lines = {line.category: line for line in p.lines}
        shopping, rent = lines["Shopping"], lines["Housing"]
        self.assertLess(shopping.suggested, shopping.average)
        self.assertGreaterEqual(shopping.suggested, shopping.average * (1 - views.MOST_CUT))  # a quarter at most
        self.assertEqual(rent.suggested, rent.average)  # rent is a regular bill, so it stays
        self.assertGreaterEqual(p.groups[2].planned, p.groups[2].actual)

    def test_a_tighter_rule_changes_the_split(self):
        s = views.from_budget(made(Path(self.dir) / "h"))
        self.assertEqual([g.share for g in views.plan(s, "70/20/10").groups], [70, 20, 10])
        self.assertEqual(views.plan(s, "made up").rule, views.DEFAULT_RULE)

    def test_without_income_there_is_nothing_to_split(self):
        from tests import fake
        budget = fake.build(Path(self.dir) / "cards", rows=[fake.row("card-0002", date(2026, 9, 3), "KROGER", -5000)])
        self.assertEqual(views.plan(views.from_budget(budget)).income, 0)


class SettingThem(Tmp):
    def test_several_at_once_and_undone_together(self):
        budget = made(Path(self.dir) / "h")
        budget.save_budget("Dining", "amount", "250", rollover=True, today=TODAY)
        budget.undoable(budget.save_budgets, {"Shopping": "320", "Dining": "100", "Transport": "130"})
        saved = budget.budgets()
        self.assertEqual(saved["Shopping"], {"mode": "amount", "value": 32000})
        self.assertTrue(saved["Dining"]["rollover"])  # it kept rolling over
        self.assertEqual(saved["Dining"]["value"], 10000)
        budget.undo()
        self.assertNotIn("Shopping", budget.budgets())
        self.assertEqual(budget.budgets()["Dining"]["value"], 25000)

    def test_one_wrong_amount_saves_none(self):
        budget = made(Path(self.dir) / "h")
        before = budget.budgets()
        with self.assertRaisesRegex(BudgetError, "Transport"):
            budget.save_budgets({"Shopping": "320", "Transport": "lots"})
        self.assertEqual(budget.budgets(), before)


class InTheWindow(QtCase):
    def page_words(self, win):
        from PySide6.QtWidgets import QLabel
        return [label.text() for label in win.pages["Budgets"].widget().findChildren(QLabel)]

    def test_suggested_budgets_are_set_in_one_step(self):
        budget = made(Path(self.dir) / "h")
        for category in list(budget.budgets()):
            budget.delete_budget(category)
        win = self.window(budget)
        win.show_tab("Budgets")
        words = self.page_words(win)
        self.assertIn("Budget guide", words)
        self.assertTrue(any("not financial advice" in w for w in words))
        dialog = planner.suggestions(win.context())
        ticked = [line.category for line, tick, _ in dialog.picks if tick.isChecked()]
        self.assertEqual(ticked, [line.category for line, _, _ in dialog.picks])  # none had a budget yet
        dialog.picks[0][2].setText("1700")
        self.assertEqual(dialog.main.text(), f"Set {len(ticked)} budgets")
        dialog.main.click()
        self.assertEqual(set(budget.budgets()), set(ticked))
        self.assertEqual(budget.budgets()[dialog.picks[0][0].category]["value"], 170000)
        self.assertEqual(win.toast.words, f"{len(ticked)} budgets set.")
        win.undo()
        self.assertEqual(budget.budgets(), {})

    def test_ones_with_a_budget_start_unticked_and_none_ticked_sets_nothing(self):
        win = self.window(made(Path(self.dir) / "h"))  # the sample budgets Dining and Groceries
        dialog = planner.suggestions(win.context())
        ticks = {line.category: tick for line, tick, _ in dialog.picks}
        self.assertFalse(ticks["Dining"].isChecked())
        self.assertTrue(ticks["Shopping"].isChecked())
        for tick in ticks.values():
            tick.setChecked(False)
        self.assertFalse(dialog.main.isEnabled())
        dialog.dismiss()

    def test_the_rule_chosen_is_kept(self):
        budget = made(Path(self.dir) / "h")
        win = self.window(budget)
        win.show_tab("Budgets")
        from budgetier.ui.popup import Dropdown
        [box] = [d for d in win.pages["Budgets"].widget().findChildren(Dropdown) if d.accessibleName() == "Rule"]
        box.setCurrentIndex(box.findData("60/30/10"))
        box.activated.emit(box.currentIndex())
        self.assertEqual(settings.load(budget.home)[planner.RULE], "60/30/10")
        self.assertIn("Needs, 60%", [c for row in self.cells(win) for c in row])

    def cells(self, win):
        from budgetier.ui.widgets import Table
        tables = win.pages["Budgets"].widget().findChildren(Table)
        guide = [t for t in tables if t.horizontalHeaderItem(1).text() == "The rule says"][0]
        return [[guide.item(r, c).text() for c in range(guide.columnCount())] for r in range(guide.rowCount())]
