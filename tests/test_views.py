"""What each tab shows, worked out in Python (budgetier/views.py)."""
import tempfile
import unittest
from datetime import date
from pathlib import Path

from budgetier import views
from tests.fake import FIRST, LAST, UNSORTED, build


class Made(unittest.TestCase):
    """The made-up data the page tests use: 15 months of checking, a card and savings."""

    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.folder.cleanup)
        cls.budget = build(Path(cls.folder.name) / "home")
        cls.s = views.from_budget(cls.budget)
        cls.all = views.Choice("all")

    def tx(self, merchant):
        return next(t for t in self.s.txns if t.merchant == merchant)


class Periods(Made):
    def test_months_run_from_the_first_transaction_to_the_last(self):
        self.assertEqual(self.s.months[0], FIRST.strftime("%Y-%m"))
        self.assertEqual(self.s.months[-1], LAST.strftime("%Y-%m"))
        self.assertEqual(len(self.s.months), 15)

    def test_recent_months(self):
        self.assertEqual(views.range_months(self.s, views.Choice("3")), self.s.months[-3:])
        self.assertEqual(views.range_months(self.s, views.Choice("12")), self.s.months[-12:])
        self.assertEqual(views.range_months(self.s, self.all), self.s.months)

    def test_a_year_is_that_year(self):
        """The page read a year as a count of recent months, so 2025 showed everything."""
        self.assertEqual(views.range_months(self.s, views.Choice("2025")), ["2025-08", "2025-09", "2025-10", "2025-11", "2025-12"])

    def test_a_month_is_that_month(self):
        self.assertEqual(views.range_months(self.s, views.Choice("2026-03")), ["2026-03"])

    def test_the_period_list_is_newest_first(self):
        options = views.range_options(self.s)
        self.assertEqual([v for g, v, _ in options if g == "Recent"], ["12", "6", "3", "all"])
        self.assertEqual([v for g, v, _ in options if g == "Year"], ["2026", "2025"])
        months = [v for g, v, _ in options if g == "Month"]
        self.assertEqual(months[0], "2026-10")
        self.assertEqual(views.range_label(self.s, views.Choice("2026-03")), "Mar 2026")

    def test_chosen_accounts_limit_the_transactions(self):
        card = views.Choice("all", frozenset({"card-0002"}))
        self.assertTrue(views.selected(self.s, card))
        self.assertEqual({t.account for t in views.selected(self.s, card)}, {"card-0002"})

    def test_without_checking_every_month_has_its_bills(self):
        card = views.Choice("all", frozenset({"card-0002"}))
        self.assertTrue(all(views.has_bills(self.s, card, m) for m in self.s.months))


class Monthly(unittest.TestCase):
    def tx(self, month, kind, cents, category="Dining"):
        return views.Tx(0, f"{month}-05", month, "a", "X", "X", category, kind, cents)

    def test_income_spending_and_refunds(self):
        [m] = views.monthly([self.tx("2026-01", "income", 500000), self.tx("2026-01", "expense", -3000),
                             self.tx("2026-01", "refund", 1000), self.tx("2026-01", "transfer", -9999)], ["2026-01"])
        self.assertEqual((m.income, m.spending, m.categories), (500000, 2000, {"Dining": 2000}))

    def test_months_outside_are_ignored_and_empty_months_kept(self):
        rows = views.monthly([self.tx("2025-12", "expense", -100)], ["2026-01", "2026-02"])
        self.assertEqual([(r.month, r.spending) for r in rows], [("2026-01", 0), ("2026-02", 0)])

    def test_category_totals_put_the_most_spent_first(self):
        rows = [views.Month("a", categories={"A": 5, "B": 9}), views.Month("b", categories={"A": 7, "C": -2})]
        self.assertEqual(views.category_totals(rows), [("A", 12), ("B", 9), ("C", -2)])


class ThisMonth(Made):
    def test_a_month_in_progress_says_so_and_compares(self):
        now = views.this_month(self.s, views.Choice())
        self.assertEqual((now.month, now.open, now.compared_with, now.day), ("2026-10", True, "2026-09", 15))
        self.assertIsNotNone(now.budget_left)

    def test_its_spending_is_the_months(self):
        now = views.this_month(self.s, views.Choice())
        self.assertEqual(now.spent, views.monthly(self.s.txns, ["2026-10"])[0].spending)

    def test_bills_still_to_come(self):
        now = views.this_month(self.s, views.Choice())
        self.assertGreater(now.due_count, 0)
        self.assertGreater(now.due, 0)

    def test_one_month_chosen_needs_no_summary(self):
        self.assertIsNone(views.this_month(self.s, views.Choice("2026-10")))

    def test_budgets_count_only_with_every_account(self):
        self.assertIsNone(views.this_month(self.s, views.Choice("12", frozenset({"card-0002"}))).budget_left)


class Overview(Made):
    def test_averages_leave_out_the_month_in_progress(self):
        o = views.overview(self.s, views.Choice("3"))
        rows = views.monthly(views.selected(self.s, views.Choice("3")), self.s.months[-3:])
        done = [r for r in rows if r.month != "2026-10"]
        self.assertEqual(o.income, round(sum(r.income for r in done) / len(done)))
        self.assertEqual(o.spending, round(sum(r.spending for r in done) / len(done)))
        self.assertEqual(o.period, views.Period(3, 2, 0))
        self.assertEqual(o.kept, o.income - o.spending)

    def test_where_it_went_is_eight_at_most_and_all_spending(self):
        o = views.overview(self.s, self.all)
        self.assertLessEqual(len(o.categories), 8)
        self.assertTrue(all(v > 0 for _, v in o.categories))
        self.assertEqual([v for _, v in o.categories], sorted((v for _, v in o.categories), reverse=True))

    def test_the_spark_is_relative_to_the_peak(self):
        o = views.overview(self.s, self.all)
        self.assertEqual(max(h for _, h, _ in o.spark), 1)
        self.assertFalse(next(done for m, _, done in o.spark if m == "2026-10"))

    def test_cards_owe_what_was_entered(self):
        o = views.overview(self.s, self.all)
        self.assertIsNone(o.owed)  # the made-up card has no balance


class Spending(Made):
    def test_the_chart_shows_spending_only_and_adds_up(self):
        s = views.spending(self.s, self.all)
        rows = views.monthly(views.selected(self.s, self.all), self.s.months)
        for i, r in enumerate(rows):
            self.assertEqual(sum(values[i] for _, values in s.series), sum(max(v, 0) for v in r.categories.values()))
        self.assertTrue(all(v >= 0 for _, values in s.series for v in values))

    def test_the_table_has_twelve_months_at_most(self):
        s = views.spending(self.s, self.all)
        self.assertEqual(s.heat_months, self.s.months[-12:])
        self.assertTrue(all(len(v) == 12 for v in s.heat.values()))


class Largest(Made):
    def test_rent_is_a_bill_and_a_one_off_isnt(self):
        self.assertTrue(views.is_bill(self.s, self.tx("Lakeside Apts Rent")))
        self.assertFalse(views.is_bill(self.s, self.tx("Best Buy")))

    def test_regular_bills_are_left_out_until_asked_for(self):
        plain = views.largest(self.s, self.all)
        self.assertFalse(any(views.is_bill(self.s, t) for t in plain.expenses))
        self.assertIn("Best Buy", [t.merchant for t in plain.expenses])
        self.assertGreater(plain.hidden, 0)
        everything = views.largest(self.s, self.all, include_bills=True)
        self.assertTrue(any(views.is_bill(self.s, t) for t in everything.expenses))
        self.assertEqual(everything.hidden, 0)

    def test_biggest_first(self):
        found = views.largest(self.s, self.all, include_bills=True)
        self.assertEqual([t.cents for t in found.expenses], sorted(t.cents for t in found.expenses))
        self.assertLessEqual(len(found.expenses), views.LARGEST)
        names = [t.merchant for t in found.expenses]
        self.assertEqual(len(names), len(set(names)))  # one from each merchant
        self.assertEqual([m[1] for m in found.merchants], sorted((m[1] for m in found.merchants), reverse=True))


class Savings(Made):
    def test_the_running_total_adds_up_what_was_kept(self):
        s = views.savings(self.s, self.all)
        self.assertEqual(s.running[-1], s.kept)
        self.assertEqual(s.running, [sum(s.nets[:i + 1]) for i in range(len(s.nets))])

    def test_the_savings_balance_is_the_one_entered(self):
        self.assertEqual(views.savings(self.s, self.all).balance, 500000)
        self.assertIsNone(views.savings(self.s, views.Choice("all", frozenset({"chk-0001"}))).balance)

    def test_money_moved_counts_saving_and_investing_net_of_withdrawals(self):
        def account(id, kind):
            return views.Account(id, id, "Bank", "0001", kind, 1, None, None, None, {}, None, False, False)

        def tx(account, category, kind, cents):
            return views.Tx(0, "2026-01-05", "2026-01", account, "X", "X", category, kind, cents)

        s = views.Snapshot(txns=[tx("chk", "Savings & Investing", "transfer", -10000),  # to a broker
                                 tx("sav", "Transfer", "transfer", 5000),  # into savings
                                 tx("sav", "Transfer", "transfer", -2000),  # back out
                                 tx("chk", "Transfer", "transfer", -3000)],  # the other half, not counted
                           accounts=[account("chk", "checking"), account("sav", "savings")], categories=[],
                           end="2026-01-20", partial_month=None, coverage_from="2026-01", recurring=[], checks=[],
                           imports=[], budget_targets=[], budget_months=[], rules=[], all_categories=[])
        self.assertEqual(views.savings(s, views.Choice("all")).moved, 13000)


class Accounts(Made):
    def test_cash_is_checking_and_savings_with_a_balance(self):
        a = views.accounts(self.s)
        known = [x for x in self.s.accounts if x.type != "credit" and x.balance is not None]
        self.assertEqual(a.cash, sum(x.balance for x in known))
        self.assertEqual(a.banked_accounts, 2)
        self.assertIsNone(a.net)  # no card balance to subtract


class Transactions(Made):
    def test_newest_first_by_default(self):
        found = views.transactions(self.s, self.all)
        self.assertEqual([t.date for t in found.txns], sorted((t.date for t in found.txns), reverse=True))
        self.assertEqual(found.net, sum(t.cents for t in found.txns))

    def test_search_reads_the_description_and_the_merchant_in_any_case(self):
        by_merchant = views.transactions(self.s, self.all, query="lakeside apts")
        by_text = views.transactions(self.s, self.all, query="ach debit")
        self.assertTrue(by_merchant.txns)
        self.assertEqual({t.merchant for t in by_text.txns}, {"Lakeside Apts Rent"})

    def test_filters_combine(self):
        found = views.transactions(self.s, self.all, category="Groceries", kind="expense")
        self.assertTrue(found.txns)
        self.assertTrue(all(t.category == "Groceries" and t.kind == "expense" for t in found.txns))

    def test_ties_keep_the_ledger_order_either_way(self):
        up = views.transactions(self.s, self.all, sort="category", descending=False).txns
        down = views.transactions(self.s, self.all, sort="category", descending=True).txns
        for found in (up, down):
            for a, b in zip(found, found[1:]):
                if a.category == b.category:
                    self.assertLess(a.i, b.i)

    def test_the_moves_come_first_in_the_category_list(self):
        self.assertEqual(views.category_filter(self.s)[:3], ["Transfer", "Savings & Investing", "Income"])


class Rules(Made):
    def test_unsorted_merchants_are_listed_most_money_first(self):
        found = views.uncategorized(self.s)
        self.assertEqual({u.description for u in found}, set(UNSORTED))
        self.assertEqual([u.total for u in found], sorted(u.total for u in found))


class Budgets(Made):
    def test_the_target_set_is_the_month_goal(self):
        b = views.budgets(self.s, "2026-09")
        [line] = b.lines
        self.assertEqual((line.category, line.goal), ("Dining", 30000))
        self.assertEqual(line.left, line.goal - line.spent)
        self.assertEqual(b.months[0], "2026-10")

    def test_the_newest_month_by_default(self):
        self.assertEqual(views.budgets(self.s).month.month, "2026-10")

    def test_dining_can_no_longer_be_chosen(self):
        choices = views.budget_choices(self.s)
        self.assertNotIn("Dining", choices)
        self.assertNotIn("Income", choices)
        self.assertIn("Groceries", choices)

    def test_the_preview_says_what_a_target_comes_to(self):
        percent = views.budget_preview(self.s, "Groceries", "percent", "10%")
        self.assertEqual(percent.amount, round(percent.income / 10))
        amount = views.budget_preview(self.s, "Groceries", "amount", "$500")
        self.assertAlmostEqual(amount.share, 50000 / amount.income)
        self.assertIsNone(views.budget_preview(self.s, "Groceries", "amount", "lots").share)


class Lines(unittest.TestCase):
    def month(self, spent, goal):
        return views.BudgetMonth("2026-01", False, 0, 0, {"A": spent}, {"A": goal})

    def test_near_over_and_fine(self):
        target = {"category": "A", "mode": "amount", "value": 1000}
        self.assertEqual(views._line(target, self.month(500, 1000)).state, "")
        self.assertEqual(views._line(target, self.month(950, 1000)).state, "near")
        self.assertEqual(views._line(target, self.month(1001, 1000)).state, "over")
        self.assertEqual(views._line(target, self.month(5, 0)).state, "over")


class Empty(unittest.TestCase):
    def test_no_transactions_still_answers(self):
        s = views.build([], {}, [], [], [], {"targets": [], "months": []}, [], [], today=date(2026, 5, 9))
        self.assertEqual(s.months, ["2026-05"])
        o = views.overview(s, views.Choice())
        self.assertEqual((o.income, o.spending, o.rate), (0, 0, None))
        self.assertEqual(views.budgets(s).lines, [])
        self.assertEqual(views.transactions(s, views.Choice()).txns, [])


if __name__ == "__main__":
    unittest.main()
