"""Savings goals: a target, kept in an account or an amount you update, and what a month
gets it there by its date."""
import json
from datetime import date
from pathlib import Path

from budgetier import views
from budgetier.accounts import pin_balance
from budgetier.service import BudgetError
from tests import fake
from tests.qt import QtCase
from tests.support import Tmp

TODAY = date(2026, 10, 15)


class Saving(Tmp):
    def setUp(self):
        super().setUp()
        self.budget = fake.build(Path(self.dir) / "home")

    def goals(self, today=TODAY):
        return views.goals(views.from_budget(self.budget), today)

    def test_an_amount_you_keep_up_to_date(self):
        self.budget.save_goal(None, "  Trip   to Japan ", "6000", "2027-10-15", [], "1200", TODAY)
        [g] = self.goals()
        self.assertEqual((g.name, g.target, g.saved, g.left), ("Trip to Japan", 600000, 120000, 480000))
        self.assertEqual(g.monthly, 40000)  # 4,800 over 12 months
        self.assertEqual(g.state, "on track")
        self.assertEqual(g.held_in, "an amount you keep up to date")

    def test_falling_behind_and_catching_up(self):
        goal_id = self.budget.save_goal(None, "Car", "1200", "2027-10-15", [], "0", TODAY)
        [g] = self.goals(date(2027, 4, 15))  # half the time gone, nothing saved
        self.assertEqual(g.state, "behind")
        self.assertEqual(g.monthly, 20000)  # 1,200 over the 6 months left
        self.budget.save_goal(goal_id, "Car", "1200", "2027-10-15", [], "650", date(2027, 4, 15))
        [g] = self.goals(date(2027, 4, 15))
        self.assertEqual(g.state, "on track")
        self.assertEqual(g.since, TODAY.isoformat())  # still measured from when it was set

    def test_kept_in_a_savings_account(self):
        self.budget.save_goal(None, "Emergency fund", "10000", None, ["sav-0003"], "", TODAY)
        [g] = self.goals()
        self.assertEqual((g.saved, g.state, g.monthly), (500000, "no date", None))
        self.assertEqual(g.held_in, "Bank Savings 0003")
        self.assertEqual(g.share, 0.5)

    def test_reached(self):
        self.budget.save_goal(None, "Cushion", "1000", "2027-01-01", ["sav-0003"], "", TODAY)
        [g] = self.goals()
        self.assertEqual((g.state, g.left, g.monthly), ("reached", 0, None))

    def test_an_account_without_a_balance(self):
        self.budget.save_goal(None, "House", "50000", "2030-01-01", ["chk-0001"], "", TODAY)
        [g] = self.goals()
        self.assertEqual((g.saved, g.state), (None, "no balance"))

    def test_what_isnt_a_goal(self):
        for args in (("", "100", None, []), ("A", "0", None, []), ("A", "lots", None, []),
                     ("A", "100", "2026-01-01", []), ("A", "100", None, ["nope"])):
            with self.assertRaises(BudgetError, msg=args):
                self.budget.save_goal(None, *args, "", TODAY)
        with self.assertRaises(BudgetError):
            self.budget.save_goal(None, "A", "100", None, [], "-5", TODAY)

    def test_removed_and_undone(self):
        goal_id = self.budget.save_goal(None, "Trip", "100", None, [], "", TODAY)
        self.budget.undoable(self.budget.delete_goal, goal_id)
        self.assertEqual(self.budget.goals(), {})
        self.budget.undo()
        self.assertIn(goal_id, self.budget.goals())

    def test_a_damaged_goal_is_set_aside(self):
        self.budget.goals_path.write_text(json.dumps({"goal-1": {"name": "Trip", "target": 100, "accounts": [], "saved": 0},
                                                      "goal-2": {"name": "", "target": 5}}), encoding="utf-8")
        self.assertEqual(list(self.budget.goals()), ["goal-1"])
        self.assertTrue(any("savings goals" in n["title"] for n in self.budget.notices))


class OnTrackFromTheAccountsStart(Tmp):
    def test_measured_from_what_the_account_held_when_set(self):
        budget = fake.build(Path(self.dir) / "home")
        pin_balance(budget.ledger.accounts["sav-0003"], 300000, date(2026, 1, 31))  # grows by $5 interest a month
        budget.ledger.save()
        budget.save_goal(None, "Fund", "10000", "2027-02-15", ["sav-0003"], "", date(2026, 2, 15))
        [g] = views.goals(views.from_budget(budget), TODAY)
        self.assertEqual(g.state, "behind")  # $5 a month is nowhere near the pace needed
        self.assertGreater(g.expected, g.saved)


class TheCard(QtCase):
    def test_adding_a_goal_from_the_savings_tab(self):
        from PySide6.QtWidgets import QLabel, QPushButton
        win = self.window()
        win.show_tab("Savings")
        page = win.pages["Savings"].widget()
        [add] = [b for b in page.findChildren(QPushButton) if b.text() == "Add goal"]
        add.click()
        from budgetier.ui.dialogs import Dialog
        [dialog] = [d for d in win.findChildren(Dialog) if d.isVisible()]
        f = dialog.goal_fields
        f["name"].setText("Trip")
        f["target"].setText("3000")
        f["saved"].setText("500")
        dialog.main.click()
        self.assertEqual([g["name"] for g in self.budget.goals().values()], ["Trip"])
        self.assertEqual(win.toast.action[0], "Undo")
        page = win.pages["Savings"].widget()
        words = [label.text() for label in page.findChildren(QLabel)]
        self.assertIn("Trip", words)
        self.assertIn("$500 of $3,000", words)

    def test_kept_in_an_account_hides_the_amount(self):
        from budgetier.ui.tabs.budgets import goal_form
        win = self.window()
        win.show_tab("Budgets")
        dialog = goal_form(win.context())
        f = dialog.goal_fields
        f["held"].setCurrentIndex(f["held"].findData("sav-0003"))
        self.assertFalse(f["saved"].isVisibleTo(dialog))
        f["dated"].setChecked(False)
        self.assertFalse(f["by"].isEnabled())
        dialog.dismiss()
