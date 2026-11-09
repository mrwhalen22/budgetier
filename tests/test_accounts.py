"""The Qt window's Accounts tab, adding files, and bank sync.

These save through the real Budget into made-up data folders. Bank sync talks to the fake
SimpleFIN server from tests/test_sync.py, over real HTTPS on this machine.
"""
import datetime as dt
import unittest
from datetime import timedelta
from pathlib import Path
from unittest import mock

from budgetier import credentials
from tests.qt import QtCase
from tests.test_sync import FakeKeyring, Server, tx


class Window(QtCase):
    def setUp(self):
        super().setUp()
        self.win = self.window()

    def toast(self) -> str:
        return self.win.toast.words if self.win.toast.isVisible() else ""

    def open_dialog(self):
        from budgetier.ui.dialogs import Dialog
        found = [d for d in self.win.findChildren(Dialog) if d.isVisible()]
        self.assertEqual(len(found), 1, [d.windowTitle() for d in found])
        return found[0]

    def labels(self, widget) -> str:
        from PySide6.QtWidgets import QLabel
        return " ".join(label.text() for label in widget.findChildren(QLabel))

    def accounts_tab(self):
        self.win.show_tab("Accounts")
        return self.win.pages["Accounts"].widget()

    def field(self, dialog, name):
        from PySide6.QtWidgets import QLineEdit
        return next(f for f in dialog.findChildren(QLineEdit) if f.accessibleName() == name)

    def button(self, widget, text):
        from PySide6.QtWidgets import QPushButton
        return next(b for b in widget.findChildren(QPushButton) if b.text() == text)


class AccountsTab(Window):
    def test_balances_accounts_and_files(self):
        from budgetier.ui import fmt
        page = self.accounts_tab()
        words = self.labels(page)
        self.assertIn("Cash and savings", words)
        self.assertIn(fmt.money(500000), words)  # the savings balance entered
        self.assertNotIn("Owed on cards", words)  # the card has none yet
        self.assertIn("No files imported yet.", words)
        from budgetier.ui.widgets import Table
        accounts = page.findChildren(Table)[0]
        self.assertEqual([accounts.item(r, 0).text() for r in range(accounts.rowCount())],
                         ["Bank Checking 0001", "Bank Savings 0003", "Chase Card 0002"])

    def test_editing_an_account(self):
        from budgetier.ui.tabs import accounts
        savings = next(a for a in self.win.snapshot.accounts if a.type == "savings")
        dialog = accounts.edit_account(self.win, savings)
        self.assertEqual(self.field(dialog, "Balance").text(), "5000.00")
        self.field(dialog, "Name").setText("Rainy Day")
        dialog.main.click()
        self.assertEqual(self.toast(), "Account saved.")
        self.assertIn("Rainy Day", [a.name for a in self.win.snapshot.accounts])

    def test_entering_what_a_card_owes(self):
        from budgetier.ui.tabs import accounts
        card = next(a for a in self.win.snapshot.accounts if a.type == "credit")
        dialog = accounts.edit_account(self.win, card)
        self.field(dialog, "Amount owed").setText("250")
        dialog.main.click()
        self.assertIn("Owed on cards", self.labels(self.accounts_tab()))
        self.assertEqual(next(a for a in self.win.snapshot.accounts if a.type == "credit").balance, -25000)

    def test_a_bad_balance_says_so(self):
        from budgetier.ui.tabs import accounts
        card = next(a for a in self.win.snapshot.accounts if a.type == "credit")
        dialog = accounts.edit_account(self.win, card)
        self.field(dialog, "Amount owed").setText("lots")
        dialog.main.click()
        self.assertEqual(dialog.error.text(), "That balance doesn't look like an amount.")

    def test_removing_an_account_asks_first(self):
        from budgetier.ui.tabs import accounts
        card = next(a for a in self.win.snapshot.accounts if a.type == "credit")
        ask = accounts.remove_account(self.win, card)
        self.assertIn("This deletes its", self.labels(ask))
        ask.buttons[-1].click()
        self.assertEqual(self.toast(), "Removed.")
        self.assertNotIn("card-0002", [a.id for a in self.win.snapshot.accounts])

    def test_export(self):
        target = self.dir / "out.xlsx"
        self.win.ask_save_path = lambda: str(target)
        self.button(self.accounts_tab(), "Export workbook").click()
        self.assertTrue(target.exists())
        self.assertEqual(self.toast(), f"Saved {target}")

    def test_export_cancelled_does_nothing(self):
        self.win.ask_save_path = lambda: ""
        self.button(self.accounts_tab(), "Export workbook").click()
        self.assertEqual(self.toast(), "")

    def test_the_data_folder_opens(self):
        with mock.patch("budgetier.ui.tabs.accounts.QDesktopServices.openUrl") as opened:
            self.button(self.accounts_tab(), "Open data folder").click()
        self.assertEqual(Path(opened.call_args[0][0].toLocalFile()), self.budget.home)


class AddingFiles(Window):
    def csv(self, name, rows, header="Date,Description,Amount"):
        path = self.dir / name
        path.write_text(header + "\n" + "\n".join(rows) + "\n", encoding="utf-8")
        return str(path)

    def add(self, *paths):
        self.win.ask_files = lambda: list(paths)
        self.win.add_button.click()
        self.assertFalse(self.win.centralWidget().isEnabled())  # held still while it reads
        self.assertTrue(self.win.runner.wait())
        self.assertTrue(self.win.centralWidget().isEnabled())
        return self.open_dialog()

    def test_a_file_is_reviewed_then_added(self):
        before = len(self.win.snapshot.txns)
        review = self.add(self.csv("Newbank_4321.csv", ["01/05/2026,LIBRARY CAFE,-4.50", "01/06/2026,BOOKSHOP,-12.00"]))
        self.assertEqual(review.windowTitle(), "Review files")
        [panel] = self.win.importing.panels
        self.assertEqual((panel.bank.text(), panel.number.text()), ("Newbank", "4321"))
        review.main.click()
        added = self.open_dialog()
        self.assertEqual(added.windowTitle(), "Files added")
        self.assertIn("2 new, 0 already here", self.labels(added))
        added.main.click()
        self.assertEqual(len(self.win.snapshot.txns), before + 2)

    def test_files_added_before_still_show_after_reopening(self):
        """Counts come back from imports.csv as text; the Accounts tab must still draw them."""
        from budgetier.service import Budget
        review = self.add(self.csv("Newbank_4321.csv", ["01/05/2026,LIBRARY CAFE,-4.50", "01/06/2026,BOOKSHOP,-12.00"]))
        review.main.click()
        self.open_dialog().main.click()
        win = self.window(Budget(self.budget.home))
        win.show_tab("Accounts")
        from budgetier.ui.widgets import Table
        imports = win.pages["Accounts"].widget().findChildren(Table)[1]
        self.assertEqual((imports.item(0, 0).text(), imports.item(0, 3).text()), ("Newbank_4321.csv", "2"))

    def test_what_is_missing_is_asked_for(self):
        review = self.add(self.csv("export.csv", ["01/05/2026,LIBRARY CAFE,-4.50"]))
        [panel] = self.win.importing.panels
        panel.bank.setText("")
        review.main.click()
        self.assertIn("Enter the bank", review.error.text())

    def test_cancel_lets_go_of_the_files(self):
        review = self.add(self.csv("Newbank_4321.csv", ["01/05/2026,LIBRARY CAFE,-4.50"]))
        review.buttons[0].click()
        self.assertFalse(review.isVisible())
        self.assertEqual(self.budget._pending, {})

    def test_a_file_that_cant_be_read_says_why(self):
        path = self.dir / "notes.txt"
        path.write_text("hello", encoding="utf-8")
        review = self.add(str(path))
        self.assertIn("notes.txt", self.labels(review))
        self.assertIn("only CSV and PDF files can be imported", self.labels(review))
        self.assertEqual([b.text() for b in review.buttons], ["Close"])

    def test_choosing_no_files_does_nothing(self):
        self.win.ask_files = lambda: []
        self.win.add_button.click()
        self.assertFalse(self.win.runner.busy)


class BankSync(Server, Window):
    def setUp(self):
        super().setUp()
        self.keyring = FakeKeyring()
        patcher = mock.patch.object(credentials, "keyring", self.keyring)
        patcher.start()
        self.addCleanup(patcher.stop)
        today = dt.date.today()
        self.bridge.feed = {"chk": {"name": "Everyday Checking ...0001", "balance": "1000.00", "transactions": [
                                tx("t1", today - timedelta(days=3), "-30.00", "GROCERY")]},
                            "card": {"name": "Rewards Card 0002", "balance": "-250.00", "transactions": [
                                tx("t2", today - timedelta(days=2), "-20.00", "SHOES")]}}

    def connect(self):
        self.assertEqual(self.win.bank_button.text(), "Connect SimpleFIN")
        self.win.bank_button.click()
        dialog = self.open_dialog()
        self.win.banking.token.setText(self.bridge.token())
        dialog.main.click()
        self.assertTrue(self.win.runner.wait())
        return self.open_dialog()

    def test_connect_choose_and_save(self):
        review = self.connect()
        self.assertEqual(review.windowTitle(), "Choose accounts")
        self.assertEqual(len(self.win.banking.panels), 2)
        review.main.click()
        saved = self.open_dialog()
        self.assertEqual(saved.windowTitle(), "Accounts saved")
        saved.main.click()
        self.assertEqual(len(self.budget.sync.status()["linked"]), 2)
        self.assertEqual(self.win.bank_button.text(), "Sync now")

    def test_a_bad_token_says_so_and_can_be_tried_again(self):
        self.win.bank_button.click()
        dialog = self.open_dialog()
        self.win.banking.token.setText("rubbish")
        dialog.main.click()
        self.assertTrue(self.win.runner.wait())
        self.assertTrue(dialog.isVisible())
        self.assertTrue(dialog.error.text())
        self.assertTrue(dialog.main.isEnabled())

    def test_sync_now_brings_in_whats_new(self):
        review = self.connect()
        review.main.click()
        self.open_dialog().main.click()
        self.bridge.feed["chk"]["transactions"].append(tx("t3", dt.date.today(), "-7.00", "LUNCH"))
        self.budget.sync.state["last_sync"] = (dt.datetime.now() - timedelta(hours=1)).isoformat(timespec="seconds")
        self.win.bank_button.click()
        self.assertTrue(self.win.runner.wait())
        self.assertEqual(self.toast(), "Synced: 1 new transaction.")
        self.win.bank_button.click()
        self.assertTrue(self.win.runner.wait())
        self.assertEqual(self.toast(), "Synced a moment ago, so there's nothing new yet.")

    def test_the_accounts_tab_shows_the_connection_and_disconnects(self):
        review = self.connect()
        review.main.click()
        self.open_dialog().main.click()
        page = self.accounts_tab()
        self.assertIn("Connected through SimpleFIN", self.labels(page))
        self.button(page, "Disconnect").click()
        ask = self.open_dialog()
        ask.buttons[-1].click()
        self.assertEqual(self.toast(), "Disconnected.")
        self.assertFalse(self.budget.sync.status()["connected"])
        self.assertEqual(self.win.bank_button.text(), "Connect SimpleFIN")


class Welcome(Window):
    def test_with_no_data_it_offers_both_ways_in(self):
        from tests.fake import build
        self.win = self.window(build(Path(self.dir) / "empty", rows=[]))
        page = self.win.pages["Overview"].widget()
        self.assertIn("Welcome to Budgetier", self.labels(page))
        for words in ("Connect SimpleFIN", "Add files", "See which banks work"):
            self.button(page, words)
        self.button(page, "See which banks work").click()
        self.assertEqual(self.win.tab, "Help")


if __name__ == "__main__":
    unittest.main()
