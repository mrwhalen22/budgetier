"""Accounts in another currency: turned into dollars at a rate you enter, as they come in."""
import datetime as dt
from datetime import date, timedelta
from unittest import mock

from budgetier import credentials, sync
from budgetier.service import Budget, BudgetError
from tests.qt import QtCase
from tests.test_sync import FakeKeyring, Server, tx


class Converting(Server):
    def setUp(self):
        super().setUp()
        patcher = mock.patch.object(credentials, "keyring", FakeKeyring())
        patcher.start()
        self.addCleanup(patcher.stop)
        self.budget = Budget(self.dir / "home")
        self.addCleanup(self.budget.cancel)
        self.today = date.today()
        self.bridge.feed = {"eur": {"name": "Girokonto 4321", "balance": "1000.00", "currency": "EUR", "transactions": [
            tx("e1", self.today - timedelta(days=5), "-12.50", "CAFE PARIS"),
            tx("e2", self.today - timedelta(days=3), "2000.00", "GEHALT")]}}

    def link(self, rate="1.10"):
        plan = self.budget.sync.connect(self.bridge.token())
        [a] = plan["accounts"]
        self.assertTrue(a["convertible"])
        return self.budget.sync.link([{**a, "bank": "Sparkasse", "number": "4321", "type": "checking", "rate": rate}])

    def test_rows_and_balance_come_in_as_dollars_and_keep_their_own_amount(self):
        done = self.link()
        self.assertEqual(done["added"], 2)
        rows = sorted(self.budget.ledger.rows, key=lambda r: r["date"])
        self.assertEqual([(r["cents"], r["description"]) for r in rows],
                         [(-1375, "CAFE PARIS (EUR -12.50)"), (220000, "GEHALT (EUR 2,000.00)")])
        info = self.budget.ledger.accounts["sparkasse-4321"]
        self.assertEqual(info["balance_anchor"]["amount"], 1100.0)
        self.assertEqual(self.budget.sync.status()["rates"], {"EUR": 1.1})

    def test_a_rate_is_needed(self):
        with self.assertRaises(BudgetError) as e:
            self.link(rate="")
        self.assertIn("1 EUR", str(e.exception))
        with self.assertRaises(BudgetError):
            self.link(rate="free")

    def test_a_new_rate_applies_to_what_comes_in_next(self):
        self.link()
        self.budget.sync.set_rate("EUR", "$1.20")
        self.bridge.feed["eur"]["transactions"].append(tx("e3", self.today, "-10.00", "BAECKEREI"))
        self.budget.sync.state["last_sync"] = (dt.datetime.now() - timedelta(hours=7)).isoformat(timespec="seconds")
        self.assertEqual(self.budget.sync.sync()["added"], 1)
        cents = {r["description"]: r["cents"] for r in self.budget.ledger.rows}
        self.assertEqual(cents["BAECKEREI (EUR -10.00)"], -1200)
        self.assertEqual(cents["CAFE PARIS (EUR -12.50)"], -1375)  # what's in keeps its rate

    def test_a_currency_with_no_rate_to_have_is_skipped(self):
        self.bridge.feed["pts"] = {"name": "Reward points", "balance": "5000", "currency": "https://points.example/pts",
                                   "transactions": []}
        plan = self.budget.sync.connect(self.bridge.token())
        points = next(a for a in plan["accounts"] if a["name"] == "Reward points")
        self.assertFalse(points["convertible"])
        euros = next(a for a in plan["accounts"] if a["name"] != "Reward points")
        self.budget.sync.link([{**points, "account": ""}, {**euros, "bank": "Sparkasse", "number": "4321",
                                                             "type": "checking", "rate": "1.1"}])
        self.assertEqual(len(self.budget.sync.links), 1)


class Rates(QtCase):
    def test_reading_rates(self):
        self.assertEqual(sync.read_rate(" $1.08 "), 1.08)
        for bad in ("", "0", "-1", "lots"):
            self.assertIsNone(sync.read_rate(bad), bad)
        self.assertTrue(sync.known_currency("JPY"))
        self.assertFalse(sync.known_currency("https://x"))

    def test_changed_from_the_accounts_tab(self):
        from PySide6.QtWidgets import QPushButton
        s = self.budget.sync
        s.state.update(connected=True, rates={"EUR": 1.1},
                       links={"c1/eur": {"account": "chk-0001", "since": None, "currency": "EUR"}})
        s._save()
        win = self.window()
        win.show_tab("Accounts")
        [change] = [b for b in win.pages["Accounts"].widget().findChildren(QPushButton) if b.text() == "Change"]
        change.click()
        from budgetier.ui.dialogs import Dialog
        [dialog] = [d for d in win.findChildren(Dialog) if d.isVisible() and d.windowTitle() == "Exchange rates"]
        dialog.rate_boxes["EUR"].setText("1.15")
        dialog.main.click()
        self.assertEqual(s.rates, {"EUR": 1.15})
        self.assertEqual(win.toast.words, "Exchange rates saved.")
