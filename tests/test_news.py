"""What's new since you last looked, on the Overview."""
from datetime import date
from pathlib import Path

from budgetier import service, views
from tests import fake
from tests.qt import QtCase
from tests.support import Tmp


def add(budget, *rows):
    budget.ledger.rows += [fake.row(*r) for r in rows]
    budget.ledger.save()


class WhatCounts(Tmp):
    def setUp(self):
        super().setUp()
        self.budget = fake.build(Path(self.dir) / "home")

    def snapshot(self):
        return views.from_budget(service.Budget(self.budget.home))

    def test_nothing_new_is_nothing_to_show(self):
        s = self.snapshot()
        self.assertIsNone(views.news(s, views.seen(s)))

    def test_new_transactions_with_money_in_and_out(self):
        last = views.seen(self.snapshot())
        add(self.budget, ("card-0002", date(2026, 10, 20), "KROGER #123", -4500),
            ("chk-0001", date(2026, 10, 21), "ACME INC PAYROLL", 312100))
        found = views.news(self.snapshot(), last)
        self.assertEqual((found.since, found.count, found.spent, found.received), ("2026-10-15", 2, 4500, 312100))

    def test_old_history_imported_later_isnt_news(self):
        last = views.seen(self.snapshot())
        add(self.budget, ("card-0002", date(2025, 3, 2), "OLD SHOP", -999))
        self.assertIsNone(views.news(self.snapshot(), last))

    def test_a_payment_newly_found_to_recur(self):
        last = views.seen(self.snapshot())
        last["recurring"].remove("Netflix")
        found = views.news(self.snapshot(), last)
        self.assertEqual([r.merchant for r in found.subscriptions], ["Netflix"])

    def test_a_price_change_since(self):
        last = views.seen(self.snapshot())
        add(self.budget, ("card-0002", date(2026, 11, 3), "NETFLIX.COM", -1799))
        found = views.news(self.snapshot(), last)
        self.assertEqual([(r.merchant, r.price_change) for r in found.prices], [("Netflix", 200)])

    def test_what_cant_be_read_is_no_news(self):
        s = self.snapshot()
        for junk in (None, "x", {"through": 5}, {}):
            self.assertIsNone(views.news(s, junk))


class OnTheOverview(QtCase):
    def card(self, win):
        from PySide6.QtWidgets import QFrame
        return win.pages["Overview"].widget().findChild(QFrame, "whatsNew")

    def test_the_first_time_nothing_is_news(self):
        from budgetier.ui import settings
        win = self.window()
        self.assertIsNone(self.card(win))
        self.assertEqual(settings.load(self.budget.home)["seen"]["through"], "2026-10-15")

    def test_new_ones_show_until_seen(self):
        from PySide6.QtWidgets import QLabel, QPushButton
        win = self.window()
        add(self.budget, ("card-0002", date(2026, 10, 20), "KROGER #123", -4500))
        win.changed()
        card = self.card(win)
        self.assertIsNotNone(card)
        self.assertIn("1 new transaction: $45 spent", [label.text() for label in card.findChildren(QLabel)])
        [done] = [b for b in card.findChildren(QPushButton) if b.text() == "Got it"]
        done.click()
        self.assertIsNone(self.card(win))
        from budgetier.ui import settings
        self.assertEqual(settings.load(self.budget.home)["seen"]["through"], "2026-10-20")

    def test_closing_after_looking_counts_as_seen(self):
        win = self.window()
        add(self.budget, ("card-0002", date(2026, 10, 20), "KROGER #123", -4500))
        win.changed()
        win.close()
        self.assertIsNone(self.card(self.window()))

    def test_closing_without_looking_keeps_it_for_next_time(self):
        from budgetier.ui import settings
        settings.save(self.budget.home, window={"tab": "Spending"})
        win = self.window()
        add(self.budget, ("card-0002", date(2026, 10, 20), "KROGER #123", -4500))
        win.changed()
        win.close()
        settings.save(self.budget.home, window={"tab": "Overview"})
        self.assertIsNotNone(self.card(self.window()))

    def test_see_transactions_opens_them(self):
        from PySide6.QtWidgets import QPushButton
        win = self.window()
        add(self.budget, ("card-0002", date(2026, 10, 20), "KROGER #123", -4500))
        win.changed()
        [see] = [b for b in self.card(win).findChildren(QPushButton) if b.text() == "See transactions"]
        see.click()
        self.assertEqual(win.tab, "Transactions")
