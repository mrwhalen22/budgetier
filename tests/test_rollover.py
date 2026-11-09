"""Budgets that roll over: what's left carries into next month, and going over takes from it."""
import json
from datetime import date
from pathlib import Path

from budgetier import views
from tests import fake
from tests.qt import QtCase
from tests.support import Tmp


def dining(budget, month):
    s = views.from_budget(budget)
    return next(line for line in views.budgets(s, month).lines if line.category == "Dining")


class Carrying(Tmp):
    def setUp(self):
        super().setUp()
        self.budget = fake.build(Path(self.dir) / "home")  # Dining: $300 a month, about $15 spent each month

    def test_whats_left_carries_into_the_next_month(self):
        self.budget.save_budget("Dining", "amount", "300", True, date(2026, 9, 10))  # rolls over from August
        aug, sep, oct = (dining(self.budget, m) for m in ("2026-08", "2026-09", "2026-10"))
        self.assertEqual((aug.carried, aug.goal), (0, 30000))
        self.assertEqual(sep.carried, aug.left)
        self.assertEqual(sep.goal, 30000 + aug.left)
        self.assertEqual(oct.carried, sep.left)
        self.assertTrue(oct.rollover)
        before = dining(self.budget, "2026-07")
        self.assertEqual((before.carried, before.goal), (0, 30000))  # nothing before it started

    def test_going_over_takes_from_next_month(self):
        self.budget.save_budget("Dining", "amount", "10", True, date(2026, 9, 10))
        aug, sep = dining(self.budget, "2026-08"), dining(self.budget, "2026-09")
        self.assertLess(aug.left, 0)
        self.assertEqual(sep.goal, 1000 + aug.left)
        self.assertLess(sep.carried, 0)

    def test_without_it_each_month_starts_fresh(self):
        line = dining(self.budget, "2026-09")
        self.assertEqual((line.carried, line.goal, line.rollover), (0, 30000, False))

    def test_editing_keeps_when_it_started_and_turning_it_off_forgets(self):
        self.budget.save_budget("Dining", "amount", "300", True, date(2026, 9, 10))
        self.budget.save_budget("Dining", "amount", "350", True, date(2026, 11, 10))
        self.assertEqual(self.budget.budgets()["Dining"]["since"], "2026-08")
        self.budget.save_budget("Dining", "amount", "350", False)
        self.assertNotIn("since", self.budget.budgets()["Dining"])
        self.budget.save_budget("Dining", "amount", "350", True, date(2027, 1, 3))
        self.assertEqual(self.budget.budgets()["Dining"]["since"], "2026-12")

    def test_the_overview_counts_whats_carried(self):
        self.budget.save_budget("Dining", "amount", "300", True, date(2026, 9, 10))
        s = views.from_budget(self.budget)
        month = views.this_month(s, views.Choice("12"))
        oct = dining(self.budget, "2026-10")
        self.assertEqual(month.budget_left, oct.left)

    def test_an_unreadable_rollover_is_set_aside(self):
        self.budget.budgets_path.write_text(json.dumps({"Dining": {"mode": "amount", "value": 30000, "rollover": "yes"}}),
                                            encoding="utf-8")
        self.assertEqual(self.budget.budgets(), {})


class TheForm(QtCase):
    def test_turned_on_from_the_edit_form(self):
        from budgetier.ui.tabs.budgets import budget_form
        win = self.window()
        win.show_tab("Budgets")
        line = dining(self.budget, None)
        dialog = budget_form(win.context(), line)
        self.assertFalse(dialog.rollover.isChecked())
        dialog.rollover.setChecked(True)
        dialog.main.click()
        self.assertTrue(self.budget.budgets()["Dining"]["rollover"])
        from PySide6.QtWidgets import QLabel
        words = " ".join(label.text() for label in win.pages["Budgets"].widget().findChildren(QLabel))
        self.assertIn("$300 a month, rolls over", words)  # from last month, so nothing's carried into it yet
