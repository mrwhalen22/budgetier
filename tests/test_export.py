"""Exporting what the Transactions tab lists as a CSV file."""
import csv
import io
import unittest
from pathlib import Path

from budgetier import export, views
from tests.qt import QtCase


def tx(description="KROGER #123", cents=-4500, merchant="Kroger", category="Groceries", account="card"):
    return views.Tx(0, "2026-10-01", "2026-10", account, description, merchant, category, "expense", cents)


class TheFile(unittest.TestCase):
    def rows(self, txns):
        return list(csv.reader(io.StringIO(export.csv_text(txns, {"card": "Chase Card 0002"}))))

    def test_one_row_each_with_plain_amounts(self):
        rows = self.rows([tx(), tx("ACME PAYROLL", 312100, "Acme", "Income")])
        self.assertEqual(rows[0], export.HEADERS)
        self.assertEqual(rows[1], ["2026-10-01", "Kroger", "KROGER #123", "Groceries", "expense", "-45.00", "Chase Card 0002"])
        self.assertEqual(rows[2][5], "3121.00")

    def test_text_a_spreadsheet_would_run_is_kept_as_text(self):
        rows = self.rows([tx(description='=HYPERLINK("http://x")', merchant="+SHOP", category="@cat")])
        self.assertEqual(rows[1][1:4], ["'+SHOP", '\'=HYPERLINK("http://x")', "'@cat"])
        self.assertEqual(rows[1][5], "-45.00")  # a real number stays a number

    def test_written_so_excel_reads_accents(self):
        import tempfile
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "out.csv"
            export.write_csv(path, [tx(merchant="Café Olé")], {})
            self.assertTrue(path.read_bytes().startswith(b"\xef\xbb\xbf"))
            self.assertIn("Café Olé", path.read_text(encoding="utf-8-sig"))


class FromTheTab(QtCase):
    def tab(self, win):
        from budgetier.ui.tabs.transactions import Transactions
        win.show_tab("Transactions")
        [tab] = win.pages["Transactions"].widget().findChildren(Transactions)
        return tab

    def test_it_saves_everything_listed_with_the_filters(self):
        win = self.window()
        win.choose(views.Choice("all"))
        tab = self.tab(win)
        tab.query.setText("kroger")
        path = Path(self.dir) / "kroger.csv"
        win.ask_csv_path = lambda name: str(path)
        tab.export.click()
        rows = list(csv.reader(io.StringIO(path.read_text(encoding="utf-8-sig"))))
        self.assertEqual(len(rows) - 1, len(tab.found))
        self.assertTrue(all("KROGER" in r[2] for r in rows[1:]))
        self.assertEqual(win.toast.words, f"Saved {len(tab.found)} transactions to kroger.csv.")

    def test_more_than_are_shown_are_saved(self):
        from budgetier.ui.tabs import transactions
        win = self.window()
        win.choose(views.Choice("all"))
        tab = self.tab(win)
        tab._change(shown=5, keep_shown=True)
        path = Path(self.dir) / "all.csv"
        win.ask_csv_path = lambda name: str(path)
        tab.export.click()
        self.assertGreater(len(tab.found), 5)
        self.assertEqual(len(path.read_text(encoding="utf-8-sig").splitlines()) - 1, len(tab.found))
        self.assertTrue(transactions.FIRST)

    def test_choosing_nowhere_saves_nothing(self):
        win = self.window()
        tab = self.tab(win)
        win.ask_csv_path = lambda name: ""
        tab.export.click()
        self.assertFalse(win.toast.isVisible())

    def test_a_file_open_elsewhere_says_so(self):
        from unittest import mock
        win = self.window()
        tab = self.tab(win)
        win.ask_csv_path = lambda name: str(Path(self.dir) / "locked.csv")
        with mock.patch.object(export, "write_csv", side_effect=PermissionError()):
            tab.export.click()
        self.assertEqual(win.toast.words, "That file is open in another program. Close it and try again.")
