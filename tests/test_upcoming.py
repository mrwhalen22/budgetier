"""What's coming up: bills, income and card payments over the next 30 days, and what they'd
do to checking."""
from datetime import date
from pathlib import Path

from budgetier import views
from budgetier.accounts import pin_balance
from tests import fake
from tests.qt import QtCase
from tests.support import Tmp


def snapshot(home: Path, checking: int | None = 300000, rows=None):
    budget = fake.build(home, rows=rows)
    if checking is not None:
        pin_balance(budget.ledger.accounts["chk-0001"], checking, fake.LAST)
    budget.ledger.save()
    return budget, views.from_budget(budget)


class Forecasting(Tmp):
    def test_whats_due_keeps_its_day_of_the_month(self):
        _, s = snapshot(Path(self.dir) / "home")
        f = views.forecast(s, date(2026, 10, 20))
        due = [(u.day, u.merchant) for u in f.items]
        self.assertIn(("2026-11-01", "Lakeside Apts Rent"), due)  # the 1st, not 30 days after Oct 1
        self.assertIn(("2026-11-05", "Acme Payroll"), due)
        self.assertIn(("2026-10-20", "Comcast Cable"), due)
        self.assertEqual([d for d, m in due if m == "Comcast Cable"], ["2026-10-20"])  # Nov 20 is past the 30 days

    def test_card_payments_are_guessed_from_recent_ones(self):
        _, s = snapshot(Path(self.dir) / "home")
        f = views.forecast(s, date(2026, 10, 20))
        [card] = [u for u in f.items if u.estimated]
        self.assertEqual((card.day, card.cents, card.from_checking, card.category), ("2026-11-12", -60000, True, "Card payment"))

    def test_bills_on_a_card_dont_move_checking_until_its_paid(self):
        _, s = snapshot(Path(self.dir) / "home")
        f = views.forecast(s, date(2026, 10, 20))
        netflix = next(u for u in f.items if u.merchant == "Netflix")
        self.assertFalse(netflix.from_checking)
        # From $3,000 on Oct 15: Comcast on the 20th, rent on Nov 1, then pay on the 5th.
        self.assertEqual(f.path[0], 300000 - 7999)
        self.assertEqual(f.low, 300000 - 7999 - 185000)
        self.assertEqual(f.low_day, "2026-11-01")
        self.assertFalse(f.short)

    def test_running_short(self):
        _, s = snapshot(Path(self.dir) / "home", checking=100000)
        f = views.forecast(s, date(2026, 10, 20))
        self.assertTrue(f.short)
        self.assertEqual(f.low, 100000 - 7999 - 185000)

    def test_totals_count_from_today(self):
        _, s = snapshot(Path(self.dir) / "home")
        f = views.forecast(s, date(2026, 10, 20))
        self.assertEqual(f.income, 312100 + 500)  # pay, and savings interest
        self.assertLess(f.bills, -(185000 + 7999 + 60000))

    def test_without_a_checking_balance_theres_a_list_but_no_line(self):
        _, s = snapshot(Path(self.dir) / "home", checking=None)
        f = views.forecast(s, date(2026, 10, 20))
        self.assertTrue(f.items)
        self.assertEqual((f.path, f.low, f.start), ([], None, None))

    def test_a_loans_payment_counts_and_its_interest_isnt_counted_again(self):
        budget = fake.build(Path(self.dir) / "home")
        budget.ledger.accounts["mtg-0004"] = {"name": "Mortgage", "bank": "Rocket Mortgage", "number": "0004",
                                              "type": "loan", "invert_sign": False}
        pin_balance(budget.ledger.accounts["chk-0001"], 300000, fake.LAST)
        for m in range(6, 11):
            budget.ledger.rows += [fake.row("chk-0001", date(2026, m, 2), "ROCKET MORTGAGE PMT", -210000),
                                   fake.row("mtg-0004", date(2026, m, 3), "PAYMENT", 210000),
                                   fake.row("mtg-0004", date(2026, m, 3), "INTEREST", -130000)]
        budget.ledger.save()
        f = views.forecast(views.from_budget(budget), date(2026, 10, 20))
        self.assertIn(("2026-11-02", -210000, "Loan payment"), [(u.day, u.cents, u.category) for u in f.items])
        self.assertNotIn("Interest", [u.category for u in f.items if u.account == "Mortgage"])


class OnScreen(QtCase):
    def test_the_recurring_tab_lists_whats_due(self):
        from PySide6.QtWidgets import QLabel
        pin_balance(self.budget.ledger.accounts["chk-0001"], 300000, fake.LAST)
        self.budget.ledger.save()
        win = self.window()
        win.show_tab("Recurring")
        words = [label.text() for label in win.pages["Recurring"].widget().findChildren(QLabel)]
        self.assertIn(f"Next {views.AHEAD_DAYS} days", words)
        self.assertIn("Lowest point", words)

    def test_the_overview_warns_before_checking_runs_short(self):
        from unittest import mock

        from PySide6.QtWidgets import QLabel
        short = views.Forecast([], "2026-11-08", "2026-11-01", 5000, ["2026-11-08"], [-20000], -20000, "2026-11-08",
                               -25000, 0)
        with mock.patch.object(views, "forecast", return_value=short):
            win = self.window()
            words = [label.text() for label in win.pages["Overview"].widget().findChildren(QLabel)]
        self.assertIn("Checking could run short around Nov 8, 2026", words)
