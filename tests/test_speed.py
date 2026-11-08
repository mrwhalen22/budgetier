"""A long history stays quick: each description is matched once, balances take one pass,
and tabs that aren't showing are let go. Each check compares with the plain way of doing it."""
import random
import unittest
from datetime import date, timedelta
from unittest import mock

from budgetier import analyze
from tests.qt import QtCase
from tests.support import ACCOUNTS, row

MIXED = ["GUSTO PAYROLL", "GUSTO BISTRO", "KROGER #123", "PAYMENT THANK YOU", "ONLINE TRANSFER TO SAVINGS",
         "NETFLIX.COM", "CHASE CREDIT CRD EPAY", "SHELL OIL 5521", "Amazon Mktp", "AMAZON MKTP"]


def one_at_a_time(rows, rules):
    """What each row gets classified as on its own, with nothing to remember between rows."""
    return [analyze.classify([r], ACCOUNTS, rules)[0] for r in rows]


class MatchedOnce(unittest.TestCase):
    def rows(self):
        rng = random.Random(4)
        return [row(rng.choice(["card", "chk", "sav"]), rng.randint(1, 28), rng.choice(MIXED),
                    rng.choice([-1, 1]) * rng.randint(100, 90000)) for _ in range(300)]

    def test_remembering_a_match_changes_no_answer(self):
        rows = self.rows()
        together = analyze.classify(rows, ACCOUNTS, [])
        for alone, both in zip(one_at_a_time(rows, []), together):
            if both["kind"] in ("transfer", "estimate") or alone["kind"] in ("transfer", "estimate"):
                continue  # pairing transfers looks at other rows, so it can differ on purpose
            self.assertEqual((alone["category"], alone["merchant"], alone["kind"], alone["ruled"]),
                             (both["category"], both["merchant"], both["kind"], both["ruled"]), both["description"])

    def test_money_in_and_out_with_the_same_words_are_matched_apart(self):
        out = analyze.classify([row("chk", 1, "GUSTO PAYROLL", 300000), row("chk", 2, "GUSTO PAYROLL", -300000)], ACCOUNTS, [])
        self.assertEqual(out[0]["category"], "Income")
        self.assertNotEqual(out[1]["category"], "Income")

    def test_an_edit_still_wins_over_a_remembered_match(self):
        rows = [row("card", 1, "KROGER #123", -500), row("card", 2, "KROGER #123", -500)]
        key = analyze.edit_keys(rows)[1]
        out = analyze.classify(rows, ACCOUNTS, [], {key: {"category": "Gifts"}})
        self.assertEqual([r["category"] for r in out], ["Groceries", "Gifts"])

    def test_each_description_is_matched_once(self):
        rows = [row("card", 1 + i % 28, "KROGER #123", -500 - i) for i in range(200)]
        with mock.patch.object(analyze, "is_transfer", wraps=analyze.is_transfer) as checked:
            analyze.classify(rows, ACCOUNTS, [])
        self.assertEqual(checked.call_count, 1)


class OnePassBalances(unittest.TestCase):
    def test_month_ends_match_adding_everything_up(self):
        rng = random.Random(9)
        first = date(2020, 1, 1)
        rows = sorted(({"date": first + timedelta(days=rng.randint(0, 2000)), "account": "card", "cents": rng.randint(-9000, 9000)}
                       for _ in range(800)), key=lambda r: r["date"])
        rows.insert(10, {**rows[10]})  # two on one day
        for pinned in ("2019-06-01", "2022-07-15", rows[300]["date"].isoformat(), "2030-01-01"):
            info = {"type": "checking", "balance_anchor": {"date": pinned, "amount": 1234.56}}
            got = analyze._calculated(rows, info)
            at = date.fromisoformat(pinned)
            for month, end in analyze._month_ends(rows[0]["date"], max(at, rows[-1]["date"])):
                plain = (123456 + sum(r["cents"] for r in rows if at < r["date"] <= end)
                         - sum(r["cents"] for r in rows if end < r["date"] <= at))
                self.assertEqual(got["months"][month], plain, (pinned, month))

    def test_a_month_is_written_as_on_the_page(self):
        self.assertEqual(analyze.month_of(date(2026, 3, 9)), "2026-03")
        self.assertEqual(analyze.month_of(date(999, 12, 31)), "0999-12")


class TabsLetGo(QtCase):
    def test_a_tab_thats_not_showing_holds_no_widgets(self):
        from budgetier.ui.app import TABS
        win = self.window()
        for tab in TABS:
            win.show_tab(tab)
            self.app.processEvents()
        from PySide6.QtCore import QCoreApplication, QEvent
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        held = [tab for tab in TABS if win.pages[tab].widget() is not None]
        self.assertEqual(held, [TABS[-1]])

    def test_coming_back_draws_it_again(self):
        win = self.window()
        win.show_tab("Spending")
        win.show_tab("Overview")
        self.assertIsNone(win.pages["Spending"].widget())
        win.show_tab("Spending")
        self.assertIsNotNone(win.pages["Spending"].widget())


if __name__ == "__main__":
    unittest.main()
