"""Investing and retirement accounts: what counts as paid in, balances kept from each sync,
growth beyond what was paid in, and the retirement estimate."""
import unittest
from datetime import date
from pathlib import Path

from budgetier import analyze, views
from budgetier.accounts import pin_balance, remember_balance
from budgetier.parse import _guess_type
from tests import fake
from tests.qt import QtCase
from tests.support import row

ACCOUNTS = {"chk": {"name": "Checking", "type": "checking", "bank": "Bank", "number": "0001"},
            "ira": {"name": "Roth IRA", "type": "retirement", "bank": "Vanguard", "number": "0002"},
            "brk": {"name": "Brokerage", "type": "investment", "bank": "Schwab", "number": "0003"}}


def classified(rows):
    return analyze.classify(rows, ACCOUNTS, [])


class WhatCountsAsPaidIn(unittest.TestCase):
    def test_money_in_out_and_the_rest(self):
        out = classified([row("ira", 1, "CONTRIBUTION 2026", 50000), row("ira", 2, "DIVIDEND DEPOSIT VTI", 1234),
                          row("ira", 3, "YOU BOUGHT VTI", -48000), row("brk", 4, "ACH WITHDRAWAL", -20000),
                          row("brk", 5, "SOMETHING ELSE", 900), row("ira", 6, "EMPLOYER MATCH", 25000)])
        self.assertEqual([r["category"] for r in out], [analyze.CONTRIBUTED, analyze.ACTIVITY, analyze.ACTIVITY,
                                                         analyze.WITHDRAWN, analyze.ACTIVITY, analyze.CONTRIBUTED])

    def test_none_of_it_is_income_or_spending(self):
        out = classified([row("ira", 1, "CONTRIBUTION", 50000), row("ira", 2, "DIVIDEND", 1234),
                          row("brk", 3, "MANAGEMENT FEE", -500), row("brk", 4, "PAYROLL DEPOSIT", 300000)])
        self.assertEqual({r["kind"] for r in out}, {"transfer"})

    def test_your_rules_still_come_first(self):
        import re
        out = analyze.classify([row("brk", 1, "SCHWAB MONEYLINK", 50000)], ACCOUNTS, [(re.compile("MONEYLINK"), "Gifts", None)])
        self.assertEqual(out[0]["category"], "Gifts")

    def test_a_transfer_from_checking_pairs_and_counts_once(self):
        rows = [row("chk", 3, "ONLINE TRANSFER TO BROKERAGE", -50000), row("brk", 3, "MONEYLINK TRANSFER", 50000),
                row("brk", 10, "DIVIDEND", 700), row("chk", 1, "PAYROLL ACME", 400000)]
        out = classified(rows)
        self.assertEqual((out[0]["category"], out[0]["matched"]), ("Transfer", True))
        self.assertEqual((out[1]["category"], out[1]["matched"]), (analyze.CONTRIBUTED, True))
        s = views.build(out, {**ACCOUNTS}, [], [], [], {"targets": [], "months": []}, [], [])
        self.assertEqual(views.savings(s, views.Choice("all")).moved, 50000)  # not the dividend, and not twice

    def test_a_dividend_never_pairs_with_a_transfer(self):
        out = classified([row("chk", 3, "ONLINE TRANSFER", -700), row("brk", 3, "DIVIDEND", 700)])
        self.assertFalse(out[1]["matched"])
        self.assertEqual(out[1]["category"], analyze.ACTIVITY)


class Guessing(unittest.TestCase):
    def test_names_from_a_bank_feed(self):
        names = {"Fidelity 401(k)": "retirement", "Vanguard Roth IRA": "retirement", "403b Plan": "retirement",
                 "Schwab Brokerage": "investment", "Individual - TOD": "investment", "Individual Checking": "checking",
                 "Ally Savings": "savings", "Statement balance $457.00": None}
        self.assertEqual({n: _guess_type(n) for n in names}, names)


class KeptBalances(unittest.TestCase):
    def test_each_set_balance_is_kept_one_a_day(self):
        info = {"type": "retirement"}
        pin_balance(info, 1000000, date(2026, 1, 5), live=True)
        pin_balance(info, 1010000, date(2026, 1, 5), live=True)
        pin_balance(info, 1100000, date(2026, 2, 5), live=True)
        self.assertEqual(info["balance_history"], [{"date": "2026-01-05", "amount": 10100.0},
                                                   {"date": "2026-02-05", "amount": 11000.0}])
        self.assertTrue(info["balance_anchor"]["live"])

    def test_other_accounts_keep_no_history(self):
        info = {"type": "checking"}
        pin_balance(info, 1000, date(2026, 1, 5))
        self.assertNotIn("balance_history", info)

    def test_a_damaged_history_is_skipped(self):
        info = {"type": "investment", "balance_history": [{"date": "nope", "amount": 1}, "junk", {"date": "2026-01-01"}]}
        remember_balance(info, 500, date(2026, 3, 1))
        self.assertEqual(analyze.balance_points([], info), [(date(2026, 3, 1), 500)])

    def test_months_show_the_last_balance_known_and_are_never_worked_back(self):
        info = {**ACCOUNTS["ira"], "balance_history": [{"date": "2026-01-20", "amount": 100.0},
                                                      {"date": "2026-03-02", "amount": 130.0}]}
        rows = [row("ira", 25, "CONTRIBUTION", 5000, month=4)]
        got = analyze.account_balances(rows, {"ira": info})["ira"]
        self.assertEqual(got["months"], {"2026-01": 10000, "2026-02": 10000, "2026-03": 13000, "2026-04": 13000})
        self.assertEqual((got["current"], got["as_of"], got["calculated"]), (13000, "2026-03-02", False))

    def test_without_any_balance_there_is_none(self):
        self.assertNotIn("ira", analyze.account_balances([row("ira", 1, "CONTRIBUTION", 500)], {"ira": ACCOUNTS["ira"]}))


def snapshot(history, rows):
    accounts = {**ACCOUNTS, "ira": {**ACCOUNTS["ira"], "balance_history": history}}
    out = analyze.classify(sorted(rows, key=lambda r: r["date"]), accounts, [])  # a ledger is in date order
    return views.build(out, accounts, [], [], [], {"targets": [], "months": []}, [], [])


class Growth(unittest.TestCase):
    HISTORY = [{"date": "2026-01-31", "amount": 10000.0}, {"date": "2026-02-28", "amount": 10600.0},
               {"date": "2026-03-31", "amount": 11500.0}]
    ROWS = [row("ira", 10, "CONTRIBUTION", 50000, month=2), row("ira", 10, "CONTRIBUTION", 50000, month=3),
            row("ira", 15, "DIVIDEND", 2000, month=3), row("chk", 1, "ACME PAYROLL", 400000, month=1)]

    def test_growth_is_what_the_balance_gained_beyond_what_was_paid_in(self):
        v = views.investments(snapshot(self.HISTORY, self.ROWS), views.Choice("all"))
        self.assertEqual((v.start, v.end, v.contributed), (1000000, 1150000, 100000))
        self.assertEqual(v.growth, 50000)
        self.assertAlmostEqual(v.growth_rate, 50000 / 1050000)
        self.assertEqual(v.balance, [1000000, 1060000, 1150000])
        self.assertEqual(v.paid_in, [1000000, 1050000, 1100000])
        self.assertEqual(v.tracked_from, "2026-01-31")

    def test_a_single_month_uses_the_month_before(self):
        v = views.investments(snapshot(self.HISTORY, self.ROWS), views.Choice("2026-03"))
        self.assertEqual((v.start, v.end, v.contributed, v.growth), (1060000, 1150000, 50000, 40000))

    def test_an_account_first_seen_later_is_brought_in_not_grown(self):
        s = snapshot(self.HISTORY, self.ROWS)
        brk = views.Account("brk", "Brokerage", "Schwab", "0003", "investment", 0, None, None, 500000,
                            {"2026-03": 500000}, "2026-03-20", False, True, (("2026-03-20", 500000),))
        s.accounts.append(brk)
        v = views.investments(s, views.Choice("all"))
        self.assertEqual(v.balance, [1000000, 1060000, 1650000])
        self.assertEqual(v.paid_in, [1000000, 1050000, 1600000])  # the gap is still the IRA's growth
        self.assertEqual(v.growth, 50000)  # one balance of the brokerage says nothing about its growth

    def test_one_balance_is_not_enough_to_see_growth(self):
        v = views.investments(snapshot(self.HISTORY[:1], self.ROWS), views.Choice("all"))
        self.assertIsNone(v.growth)
        self.assertEqual(v.total, 1000000)


class NotCash(unittest.TestCase):
    def test_investing_accounts_stay_out_of_cash(self):
        s = snapshot(Growth.HISTORY, Growth.ROWS)
        a = views.accounts(s)
        self.assertNotIn(1150000, (a.cash,))
        self.assertEqual(a.banked_accounts, 1)  # checking only


class Estimate(unittest.TestCase):
    def test_without_growth_it_adds_up(self):
        p = views.project(1000000, 50000, views.Plan(age=40, retire_at=42, growth=0, withdraw=4))
        self.assertEqual((p.years, p.at_retirement), (2, 1000000 + 24 * 50000))
        self.assertEqual(p.path, [1000000, 1600000, 2200000])
        self.assertEqual(p.paid, p.path)
        self.assertEqual(p.income, round(2200000 * 0.04 / 12))
        self.assertEqual(p.ages, ["40", "41", "42"])

    def test_growth_compounds_to_the_yearly_rate(self):
        p = views.project(1000000, 0, views.Plan(age=30, retire_at=40, growth=5))
        self.assertAlmostEqual(p.at_retirement, 1000000 * 1.05 ** 10, delta=2)

    def test_retired_already_shows_today(self):
        p = views.project(1000000, 50000, views.Plan(age=70, retire_at=65))
        self.assertEqual((p.years, p.at_retirement, p.path), (0, 1000000, [1000000]))

    def test_a_plan_that_cant_be_read_is_the_default(self):
        self.assertEqual(views.Plan.from_saved("junk"), views.Plan())
        self.assertEqual(views.Plan.from_saved({"age": "forty", "growth": 99, "monthly": -5}), views.Plan())
        plan = views.Plan(age=41, retire_at=60, monthly=70000, growth=4.5, withdraw=3.5, include_investing=True)
        self.assertEqual(views.Plan.from_saved(plan.saved()), plan)

    def test_only_retirement_accounts_count_unless_asked(self):
        s = snapshot(Growth.HISTORY, Growth.ROWS + [row("brk", 2, "DIVIDEND", 100, month=3)])
        accounts = {a.id: a for a in s.accounts}
        brk = accounts.get("brk")
        self.assertIsNone(brk.balance if brk else None)  # no balance known yet: it can't count
        p = views.retirement(s, views.Plan(age=40, retire_at=41))
        self.assertEqual(p.balance, 1150000)
        self.assertEqual(p.monthly, round(50000 / 2))  # January and February: March is still in progress


def with_investments(home: Path):
    budget = fake.build(home)
    ledger = budget.ledger
    ledger.accounts["ret-0004"] = {"name": "Fidelity 401(k)", "bank": "Fidelity", "number": "0004", "type": "retirement",
                                   "invert_sign": False}
    ledger.accounts["brk-0005"] = {"name": "Schwab Brokerage", "bank": "Schwab", "number": "0005", "type": "investment",
                                   "invert_sign": False}
    balance, history = 4_000_000, []
    year, month = 2025, 8
    while (year, month) <= (2026, 10):
        day = date(year, month, 15)
        ledger.rows.append(fake.row("ret-0004", day, "EMPLOYER CONTRIBUTION", 60000))
        ledger.rows.append(fake.row("ret-0004", day, "DIVIDEND REINVEST", 3000))
        balance += 60000 + 3000 + (month % 4 - 1) * 25000
        history.append({"date": day.isoformat(), "amount": balance / 100})
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    ledger.accounts["ret-0004"]["balance_history"] = history
    pin_balance(ledger.accounts["brk-0005"], 1_250_000, date(2026, 10, 1), live=True)
    ledger.save()
    ledger.save_accounts()
    return budget


class Tab(QtCase):
    def setUp(self):
        super().setUp()
        self.budget = with_investments(Path(self.dir) / "invested")
        self.win = self.window(self.budget)
        self.win.show_tab("Investments")

    def page(self):
        return self.win.pages["Investments"].widget()

    def labels(self):
        from PySide6.QtWidgets import QLabel
        return [label.text() for label in self.page().findChildren(QLabel)]

    def test_it_shows_balances_growth_and_an_estimate(self):
        from budgetier.ui.charts import Chart
        labels = self.labels()
        for words in ("Invested now", "Growth this period", "Balance and what was paid in", "Retirement estimate",
                      "At 65", "A month after that"):
            self.assertIn(words, labels)
        self.assertEqual(len(self.page().findChildren(Chart)), 3)  # balance, each account, the estimate

    def test_typing_a_number_redraws_the_estimate_and_keeps_it(self):
        from budgetier.ui import settings
        from budgetier.ui.tabs.investments import Estimate
        [estimate] = self.page().findChildren(Estimate)
        estimate.retire_at.setText("60")
        self.assertIn("At 60", self.labels())
        self.assertEqual(settings.load(self.budget.home)["retirement"]["retire_at"], 60)
        estimate.retire_at.setText("")  # half typed: nothing changes
        self.assertIn("At 60", self.labels())
        self.win.show_tab("Overview")
        self.win.show_tab("Investments")
        [estimate] = self.page().findChildren(Estimate)
        self.assertEqual(estimate.retire_at.text(), "60")

    def test_counting_investing_accounts_adds_them(self):
        from budgetier.ui.tabs.investments import Estimate
        [estimate] = self.page().findChildren(Estimate)
        before = estimate.plan
        estimate.include.setChecked(True)
        self.assertTrue(estimate.plan.include_investing)
        today = views.retirement(self.win.snapshot, estimate.plan).balance
        self.assertEqual(today - views.retirement(self.win.snapshot, before).balance, 1_250_000)

    def test_without_investing_accounts_the_tab_waits(self):
        win = self.window(fake.build(Path(self.dir) / "plain"))
        self.assertFalse(win.tab_buttons["Investments"].isVisibleTo(win))
        win.show_tab("Investments")
        self.assertEqual(win.tab, "Overview")

    def test_without_investing_accounts_it_says_how_to_mark_one(self):
        from budgetier.ui import tabs
        from budgetier.ui.context import Context
        win = self.window(fake.build(Path(self.dir) / "plain"))
        from PySide6.QtWidgets import QLabel, QPushButton
        ctx: Context = win.context()
        page = tabs.investments.build(ctx)
        self.assertIn("No investing or retirement accounts yet", [label.text() for label in page.findChildren(QLabel)])
        [go] = [b for b in page.findChildren(QPushButton) if b.text() == "Open Accounts"]
        go.click()
        self.assertEqual(win.tab, "Accounts")

    def test_an_account_can_be_marked_as_retirement(self):
        self.budget.update_account("sav-0003", "Bank Savings 0003", "retirement", "5000", "2026-10-10")
        self.win.reload()
        account = self.win.snapshot.by_id["sav-0003"]
        self.assertEqual(account.type, "retirement")
        self.assertIn(("2026-10-10", 500000), account.points)


class ShortAmounts(unittest.TestCase):
    def test_millions(self):
        from budgetier.ui import fmt
        self.assertEqual([fmt.short(v) for v in (99_940_000, 124_757_014, -250_000_000)], ["$999.4k", "$1.2M", "-$2.5M"])


if __name__ == "__main__":
    unittest.main()
