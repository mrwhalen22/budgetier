"""Alerts on the Overview: a budget nearly used up this month, and charges far from the usual."""
from datetime import date
from pathlib import Path

from budgetier import views
from tests import fake
from tests.qt import QtCase
from tests.support import Tmp


def budget_alerts(s, dismissed=None):
    return [a for a in views.alerts(s, dismissed) if a.key.startswith("budget")]


def with_rows(home: Path, *extra):
    budget = fake.build(home)
    budget.ledger.rows += list(extra)
    budget.ledger.save()
    return budget


class Budgets(Tmp):
    def test_most_of_a_budget_used_with_the_month_still_going(self):
        budget = with_rows(Path(self.dir) / "home", fake.row("card-0002", date(2026, 10, 10), "CHIPOTLE 2291", -24000))
        [a] = budget_alerts(views.from_budget(budget))
        self.assertEqual(a.level, "info")
        self.assertTrue(a.title.startswith("Dining has used 8"), a.title)
        self.assertIn("16 days left in Oct 2026", a.detail)
        self.assertEqual(a.category, "Dining")

    def test_over_budget(self):
        budget = with_rows(Path(self.dir) / "home", fake.row("card-0002", date(2026, 10, 10), "CHIPOTLE 2291", -40000))
        [a] = budget_alerts(views.from_budget(budget))
        self.assertEqual(a.level, "warning")
        self.assertIn("over budget", a.title)

    def test_dismissed_until_its_new_news(self):
        budget = with_rows(Path(self.dir) / "home", fake.row("card-0002", date(2026, 10, 10), "CHIPOTLE 2291", -24000))
        s = views.from_budget(budget)
        [a] = budget_alerts(s)
        self.assertEqual(budget_alerts(s, {a.key}), [])
        budget.ledger.rows.append(fake.row("card-0002", date(2026, 10, 11), "CHIPOTLE 2291", -10000))
        budget.ledger.save()
        [again] = budget_alerts(views.from_budget(budget), {a.key})  # going over is news again
        self.assertIn("over budget", again.title)

    def test_nothing_for_an_ordinary_month(self):
        self.assertEqual(views.alerts(views.from_budget(fake.build(Path(self.dir) / "home"))), [])


class Charges(Tmp):
    def test_far_more_than_a_merchant_usually_takes(self):
        budget = with_rows(Path(self.dir) / "home", fake.row("chk-0001", date(2026, 10, 14), "COMCAST CABLE 800", -45000))
        [a] = [x for x in views.alerts(views.from_budget(budget)) if x.key.startswith("charge")]
        self.assertEqual(a.title, "Comcast Cable charged $450")
        self.assertIn("usually about $80", a.detail)

    def test_a_big_first_charge(self):
        budget = with_rows(Path(self.dir) / "home", fake.row("card-0002", date(2026, 10, 12), "MYSTERY SHOP LLC", -31000))
        [a] = views.alerts(views.from_budget(budget))
        self.assertTrue(a.title.startswith("A first charge from Mystery Shop"))

    def test_old_or_small_charges_arent_news(self):
        budget = with_rows(Path(self.dir) / "home",
                           fake.row("chk-0001", date(2026, 9, 20), "COMCAST CABLE 800", -45000),  # weeks ago
                           fake.row("card-0002", date(2026, 10, 12), "NEW CAFE", -900))  # small
        self.assertEqual(views.alerts(views.from_budget(budget)), [])


class OnTheOverview(QtCase):
    def test_shown_and_dismissed(self):
        from PySide6.QtWidgets import QFrame, QPushButton
        self.budget.ledger.rows.append(fake.row("card-0002", date(2026, 10, 10), "CHIPOTLE 2291", -40000))
        self.budget.ledger.save()
        win = self.window()
        page = win.pages["Overview"].widget()
        frame = page.findChild(QFrame, "headsUp")
        self.assertIsNotNone(frame)
        [done] = [b for b in frame.findChildren(QPushButton) if b.text() == "Dismiss all"]
        done.click()
        self.assertIsNone(win.pages["Overview"].widget().findChild(QFrame, "headsUp"))
        from budgetier.ui import settings
        self.assertEqual(len(settings.load(self.budget.home)["dismissed"]), 2)  # the budget, and the charge itself
        again = self.window()
        self.assertIsNone(again.pages["Overview"].widget().findChild(QFrame, "headsUp"))
