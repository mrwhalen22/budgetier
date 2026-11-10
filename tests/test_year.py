"""Year in review: a year at a glance, beside the months of the year before that both have, and
the rows worth gathering at tax time."""
import csv
from datetime import date
from pathlib import Path

from budgetier import analyze, views
from budgetier.accounts import pin_balance
from tests import fake
from tests.qt import QtCase
from tests.support import Tmp


class Reviewing(Tmp):
    def setUp(self):
        super().setUp()
        self.budget = fake.build(Path(self.dir) / "home")  # Aug 2025 to mid Oct 2026

    def review(self, year=None):
        return views.year_review(views.from_budget(self.budget), year)

    def test_the_newest_year_by_default_and_each_year_to_choose(self):
        y = self.review()
        self.assertEqual((y.year, y.years), ("2026", ["2026", "2025"]))
        self.assertEqual([m.month for m in y.months][:2], ["2026-01", "2026-02"])
        self.assertEqual(len(y.months), 10)
        self.assertFalse(y.complete)
        self.assertEqual(y.income, 10 * (312100 + 500))  # pay and savings interest

    def test_compared_only_over_months_both_years_have(self):
        y = self.review("2026")
        self.assertEqual(y.compared, 3)  # Aug to Oct: 2025 starts in August
        self.assertEqual(y.before[0], 3 * (312100 + 500))
        self.assertEqual(y.matched[0], 3 * (312100 + 500))
        self.assertEqual([c.category for c in y.down], ["Utilities"])  # Oct 2026's bill hadn't come by the 15th
        self.assertIsNone(self.review("2025").before)

    def test_where_it_went_and_who_got_it(self):
        y = self.review("2026")
        self.assertEqual(y.categories[0].category, "Housing")
        self.assertEqual(y.merchants[0], ("Lakeside Apts Rent", 10 * 185000, 10))
        self.assertEqual(y.largest[0].description, "ACH DEBIT LAKESIDE APTS RENT")
        self.assertEqual(y.busiest.month, "2026-06")  # the Best Buy month
        self.assertNotEqual(y.quietest.month, "2026-10")  # half of October is in: not a quiet month

    def test_tax_time_lines(self):
        a = self.budget.ledger.accounts
        a["ira-0005"] = {"name": "Roth IRA", "bank": "Vanguard", "number": "0005", "type": "retirement", "invert_sign": False}
        pin_balance(a["ira-0005"], 100000, fake.LAST)
        self.budget.ledger.rows += [fake.row("card-0002", date(2026, 4, 2), "RED CROSS DONATION", -10000),
                                    fake.row("chk-0001", date(2026, 4, 15), "IRS TAX PAYMENT", -50000),
                                    fake.row("ira-0005", date(2026, 5, 1), "CONTRIBUTION", 20000),
                                    fake.row("ira-0005", date(2026, 5, 2), "DIVIDEND", 300)]
        self.budget.ledger.save()
        self.budget.save_rule(None, "RED CROSS", "Gifts & Donations", "Red Cross")
        y = self.review("2026")
        lines = {line.label: (line.total, line.count) for line in y.tax}
        self.assertEqual(lines["Donations and gifts"], (10000, 1))
        self.assertEqual(lines["Taxes paid"], (50000, 1))
        self.assertEqual(lines["Paid into retirement"], (20000, 1))
        self.assertNotIn("Medical", lines)
        rows = views.tax_rows(views.from_budget(self.budget), "2026")
        self.assertEqual(sorted(t.category for t in rows), [analyze.CONTRIBUTED, "Gifts & Donations", "Taxes"])

    def test_a_year_with_nothing_in_it(self):
        s = views.from_budget(fake.build(Path(self.dir) / "empty", rows=[]))
        y = views.year_review(s)
        self.assertEqual((y.months, y.income, y.tax, y.busiest), ([], 0, [], None))


class TheTab(QtCase):
    def test_it_shows_the_year_and_exports_tax_rows(self):
        from unittest import mock

        from PySide6.QtWidgets import QLabel, QPushButton
        self.budget.ledger.rows.append(fake.row("chk-0001", date(2026, 4, 15), "IRS TAX PAYMENT", -50000))
        self.budget.ledger.save()
        win = self.window()
        win.show_tab("Year in review")
        page = win.pages["Year in review"].widget()
        words = [label.text() for label in page.findChildren(QLabel)]
        self.assertIn("For tax time", words)
        self.assertIn("Went up the most", words)
        out = Path(self.dir) / "tax.csv"
        [save] = [b for b in page.findChildren(QPushButton) if b.text() == "Export these rows"]
        with mock.patch.object(win, "ask_csv_path", return_value=str(out)):
            save.click()
        with out.open(encoding="utf-8-sig") as f:
            rows = list(csv.reader(f))
        self.assertEqual([r[2] for r in rows[1:]], ["IRS TAX PAYMENT"])

    def test_choosing_a_category_shows_that_years_transactions(self):
        win = self.window()
        win.show_tab("Year in review")
        from budgetier.ui.tabs.year import open_year
        open_year(win.context(), "2025", category="Housing")
        self.assertEqual(win.tab, "Transactions")
        self.assertEqual(win.choice.range, "2025")
