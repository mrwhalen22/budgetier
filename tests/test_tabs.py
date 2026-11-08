"""The Qt window's read-only tabs: Overview, Spending, Recurring, Largest, Savings and Help."""
import unittest
from datetime import date
from pathlib import Path

from budgetier import views
from tests.browser import build
from tests.qt import QtCase

BUILT = ("Overview", "Spending", "Recurring", "Largest", "Savings", "Help")
CHOICES = (views.Choice("12"), views.Choice("all"), views.Choice("2025"), views.Choice("2026-03"),
           views.Choice("3", frozenset({"card-0002"})))


class Tabs(QtCase):
    def setUp(self):
        super().setUp()
        self.win = self.window()

    def labels(self) -> list[str]:
        from PySide6.QtWidgets import QLabel
        return [label.text() for label in self.win.pages[self.win.tab].widget().findChildren(QLabel)]

    def page_has(self, words: str) -> bool:
        return any(words in label for label in self.labels())

    def tables(self):
        from budgetier.ui.widgets import Table
        return self.win.pages[self.win.tab].widget().findChildren(Table)

    def asked(self) -> dict:
        """What the Transactions tab was asked to show."""
        return {k: self.win.options["transactions"][k] for k in ("category", "query")}

    def cells(self, table) -> list[list[str]]:
        return [[table.item(r, c).text() for c in range(table.columnCount())] for r in range(table.rowCount())]


class EveryTab(Tabs):
    def test_every_tab_draws_for_every_choice(self):
        for choice in CHOICES:
            self.win.choose(choice)
            for tab in BUILT:
                with self.subTest(tab=tab, range=choice.range, accounts=choice.accounts):
                    self.win.show_tab(tab)
                    self.app.processEvents()
                    self.assertFalse(self.win.grab().isNull())
                    self.assertEqual(self.win.title.text(), tab)

    def test_with_no_data_every_tab_still_opens(self):
        empty = self.window(build(Path(self.dir) / "empty", rows=[]))
        for tab in BUILT:
            empty.show_tab(tab)
            self.app.processEvents()
        empty.show_tab("Overview")
        self.assertFalse(empty.filters.isVisibleTo(empty))


class Filters(Tabs):
    def test_the_period_list_has_headings_that_cant_be_chosen(self):
        box = self.win.range_box
        headings = [i for i in range(box.count()) if box.itemText(i) in ("Recent", "Year", "Month")]
        self.assertEqual(len(headings), 3)
        self.assertTrue(all(not box.model().item(i).isEnabled() for i in headings))

    def test_choosing_a_period_shows_it(self):
        box = self.win.range_box
        box.activated.emit(box.findData("2025"))
        self.assertEqual(self.win.choice.range, "2025")
        self.assertEqual(self.win.subtitle.text(), "2025")

    def test_unticking_an_account_leaves_it_out(self):
        self.win.account_actions["card-0002"].trigger()
        self.assertEqual(self.win.choice.accounts, frozenset({"chk-0001", "sav-0003"}))
        self.assertEqual(self.win.accounts_button.text(), "2 of 3 accounts")
        self.win.account_actions["card-0002"].trigger()
        self.assertIsNone(self.win.choice.accounts)
        self.assertEqual(self.win.accounts_button.text(), "All accounts")

    def test_tabs_over_all_history_hide_the_filters(self):
        for tab, shown in (("Overview", True), ("Recurring", False), ("Help", False), ("Savings", True)):
            self.win.show_tab(tab)
            self.assertEqual(self.win.filters.isVisibleTo(self.win), shown, tab)
        self.win.show_tab("Recurring")
        self.assertEqual(self.win.subtitle.text(), "All history")


class Overview(Tabs):
    def test_the_numbers_are_views(self):
        o = views.overview(self.win.snapshot, self.win.choice)
        from budgetier.ui import fmt
        for words in (fmt.money(o.spending), fmt.money(o.income), f"{round(o.rate * 100)}%", "Average of 11 complete months."):
            self.assertTrue(self.page_has(words), words)

    def test_a_month_in_progress_says_so_and_compares(self):
        self.assertTrue(self.page_has("Oct 2026 so far"))
        self.assertTrue(self.page_has("Compared with Sep"))
        self.assertTrue(self.page_has("by day 15 of the month"))
        self.assertTrue(self.page_has("Left in budgets"))

    def test_see_this_month_chooses_it(self):
        from PySide6.QtWidgets import QPushButton
        see = next(b for b in self.win.pages["Overview"].widget().findChildren(QPushButton) if b.text() == "See this month")
        see.click()
        self.assertEqual(self.win.choice.range, "2026-10")
        self.assertFalse(self.page_has("so far"))

    def test_a_category_opens_its_transactions(self):
        from budgetier.ui.widgets import HBar
        housing = next(b for b in self.win.pages["Overview"].widget().findChildren(HBar) if "Housing" in b.accessibleName())
        housing.clicked.emit()
        self.assertEqual(self.win.tab, "Transactions")
        self.assertEqual(self.asked(), {"category": "Housing", "query": ""})

    def test_the_warnings_fold_into_one_line(self):
        from budgetier.ui.widgets import Notices
        [bar] = self.win.pages["Overview"].widget().findChildren(Notices)
        self.assertFalse(bar.list.isVisibleTo(bar))
        bar.toggle.click()
        self.assertTrue(bar.list.isVisibleTo(bar))


class Spending(Tabs):
    def test_the_table_has_each_category_and_opens_one(self):
        self.win.show_tab("Spending")
        [table] = self.tables()
        names = [row[0] for row in self.cells(table)]
        self.assertEqual(names, [c for c, _ in views.spending(self.win.snapshot, self.win.choice).categories])
        table.cellClicked.emit(names.index("Groceries"), 3)
        self.assertEqual(self.asked()["category"], "Groceries")


class Recurring(Tabs):
    def test_bills_list_and_a_row_opens_its_transactions(self):
        self.win.show_tab("Recurring")
        bills, income = self.tables()
        merchants = [row[0] for row in self.cells(bills)]
        self.assertIn("Lakeside Apts Rent", merchants)
        self.assertEqual([row[0] for row in self.cells(income)], ["Acme Payroll", "Interest"])
        bills.cellClicked.emit(merchants.index("Netflix"), 0)
        self.assertEqual(self.asked(), {"category": "", "query": "Netflix"})

    def test_including_stopped_payments_is_remembered(self):
        from PySide6.QtWidgets import QCheckBox
        self.win.show_tab("Recurring")
        [box] = self.win.pages["Recurring"].widget().findChildren(QCheckBox)
        box.click()
        self.assertTrue(self.win.options["recurring_all"])
        self.win.show_tab("Overview")
        self.win.show_tab("Recurring")
        [box] = self.win.pages["Recurring"].widget().findChildren(QCheckBox)
        self.assertTrue(box.isChecked())


class Largest(Tabs):
    def test_bills_are_left_out_until_asked_for(self):
        from PySide6.QtWidgets import QCheckBox
        self.win.choose(views.Choice("all"))
        self.win.show_tab("Largest")
        [table] = self.tables()
        self.assertNotIn("Lakeside Apts Rent", [row[0] for row in self.cells(table)])
        self.assertTrue(self.page_has("leaving out regular bills"))
        [box] = self.win.pages["Largest"].widget().findChildren(QCheckBox)
        box.click()
        [table] = self.tables()
        self.assertIn("Lakeside Apts Rent", [row[0] for row in self.cells(table)])


class Savings(Tabs):
    def test_kept_and_the_charts(self):
        from budgetier.ui import fmt
        from budgetier.ui.charts import Chart
        self.win.show_tab("Savings")
        v = views.savings(self.win.snapshot, self.win.choice)
        self.assertTrue(self.page_has(fmt.money(v.kept)))
        charts = self.win.pages["Savings"].widget().findChildren(Chart)
        self.assertEqual([c.kind for c in charts], ["bars", "lines", "lines"])


class Help(Tabs):
    def test_it_says_where_data_lives_and_the_version(self):
        self.win.show_tab("Help")
        self.assertTrue(self.page_has("Everything stays on this computer."))
        self.assertTrue(self.page_has("Budgetier makes no network requests."))
        self.assertIn("Fifth Third", [row[0] for row in self.cells(self.tables()[0])])


class Charts(Tabs):
    def chart(self, **options):
        from budgetier.ui import theme
        from budgetier.ui.charts import Chart, Series
        t = theme.tokens("light", "pine")
        chart = Chart(["2026-01", "2026-02"], [Series("<b>Food</b>", [1000, 2500], "#123456"), Series("Rent", [5000, 0], "#654321")],
                      t, **options)
        chart.resize(500, 260)
        self.addCleanup(chart.deleteLater)
        return chart

    def test_a_months_values_read_out(self):
        title, rows = self.chart().tip(0)
        self.assertEqual(title, "Jan 2026")
        self.assertEqual([(n, a) for n, a, _ in rows], [("Rent", "$50"), ("<b>Food</b>", "$10")])

    def test_stacked_months_add_a_total_and_skip_empties(self):
        _, rows = self.chart(stacked=True).tip(1)
        self.assertEqual([(n, a) for n, a, _ in rows], [("<b>Food</b>", "$25"), ("Total", "$25")])

    def test_names_in_a_tooltip_are_text(self):
        tip = self.chart().tip_html(0)
        self.assertIn("&lt;b&gt;Food&lt;/b&gt;", tip)
        self.assertNotIn("<b>Food</b>", tip)

    def test_the_arrow_keys_walk_the_months(self):
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        chart = self.chart()
        chart.show()
        QTest.keyClick(chart, Qt.Key_Right)
        self.assertEqual(chart.at, 0)
        QTest.keyClick(chart, Qt.Key_Right)
        QTest.keyClick(chart, Qt.Key_Right)
        self.assertEqual(chart.at, 1)
        self.assertIn("Feb 2026", chart.accessibleDescription())

    def test_the_scale_lands_on_round_numbers(self):
        from budgetier.ui.charts import nice_max
        self.assertEqual([nice_max(v) for v in (0, 90, 180, 240, 400, 900)], [1, 100, 200, 250, 500, 1000])


class BankText(Tabs):
    def test_hostile_merchants_show_as_text_everywhere(self):
        from budgetier.ui.widgets import HBar
        text = "<img src=x onerror=alert(1)> <b>SHOP</b>"
        rows = [{"date": date(2026, 1, d), "account": "chk-0001", "description": text, "amount": "-50.00", "cents": -5000,
                 "balance": None, "bank_category": "", "source": "x", "sync_id": ""} for d in (2, 3, 4, 5)]
        win = self.window(build(Path(self.dir) / "hostile", rows))
        win.choose(views.Choice("all"))
        win.show_tab("Largest")
        bars = win.pages["Largest"].widget().findChildren(HBar)
        self.assertTrue(bars)
        from budgetier.ui.widgets import Table
        [table] = win.pages["Largest"].widget().findChildren(Table)
        self.assertIn("&lt;img", table.item(0, 0).toolTip())
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QLabel
        for label in win.findChildren(QLabel):
            if "<img" in label.text():
                self.assertEqual(label.textFormat(), Qt.PlainText)


class Formats(unittest.TestCase):
    def test_amounts_round_half_up_as_on_the_page(self):
        from budgetier.ui import fmt
        self.assertEqual(fmt.money(250), "$3")
        self.assertEqual(fmt.money(123456, 2), "$1,234.56")
        self.assertEqual(fmt.money(-123456), "-$1,235")
        self.assertEqual(fmt.short(125000), "$1.3k")
        self.assertEqual(fmt.short(-95000), "-$950")
        self.assertEqual(fmt.short(100000), "$1k")
        self.assertEqual(fmt.plural(1, "budget"), "1 budget")
        self.assertEqual(fmt.plural(2, "budget"), "2 budgets")


if __name__ == "__main__":
    unittest.main()
