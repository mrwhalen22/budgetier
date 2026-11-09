"""Loans and net worth: payments into a loan pay it down rather than counting as spending, its
interest is spending, and net worth adds up what you have less what you owe."""
import unittest
from datetime import date
from pathlib import Path

from budgetier import analyze, views
from budgetier.accounts import entered_balance, pin_balance
from budgetier.parse import _guess_type
from tests import fake
from tests.qt import QtCase
from tests.support import row

ACCOUNTS = {"chk": {"name": "Checking", "type": "checking", "bank": "Bank", "number": "0001"},
            "mtg": {"name": "Mortgage", "type": "loan", "bank": "Rocket Mortgage", "number": "0002"},
            "car": {"name": "Car loan", "type": "loan", "bank": "Toyota", "number": "0003"},
            "ira": {"name": "IRA", "type": "retirement", "bank": "Vanguard", "number": "0004"},
            "card": {"name": "Card", "type": "credit", "bank": "Chase", "number": "0005"}}


def classified(rows, accounts=ACCOUNTS):
    return analyze.classify(rows, accounts, [])


def snapshot(rows, accounts):
    out = classified(rows, accounts)
    return views.build(out, accounts, [], [], [], {"targets": [], "months": []}, [], [])


class InsideALoan(unittest.TestCase):
    def test_payments_pay_it_down_and_interest_is_spending(self):
        out = classified([row("mtg", 1, "PAYMENT RECEIVED", 210000), row("mtg", 1, "INTEREST CHARGED", -95000),
                          row("car", 2, "FINANCE CHARGE", -3100)])
        self.assertEqual([(r["category"], r["kind"]) for r in out],
                         [("Transfer", "transfer"), (analyze.INTEREST, "expense"), (analyze.INTEREST, "expense")])
        self.assertEqual(out[0]["merchant"], analyze.LOAN_PAYMENT)

    def test_the_payment_from_checking_pairs_and_isnt_spending_twice(self):
        out = classified([row("chk", 1, "ROCKET MORTGAGE PMT 8812", -210000), row("mtg", 2, "PAYMENT", 210000),
                          row("chk", 5, "TOYOTA FINANCIAL SVCS ACH", -41000), row("car", 5, "PAYMENT THANK YOU", 41000)])
        self.assertEqual([(r["kind"], r["matched"]) for r in out], [("transfer", True)] * 4)
        self.assertEqual(out[0]["category"], "Transfer")

    def test_without_the_loan_imported_a_mortgage_is_still_housing(self):
        only = {"chk": ACCOUNTS["chk"]}
        out = classified([row("chk", 1, "ROCKET MORTGAGE PMT 8812", -210000)], only)
        self.assertEqual((out[0]["category"], out[0]["kind"]), ("Housing", "expense"))

    def test_rent_the_same_size_isnt_taken_for_a_loan_payment(self):
        out = classified([row("chk", 1, "LAKESIDE APTS RENT", -41000), row("car", 1, "PAYMENT", 41000)])
        self.assertFalse(out[0]["matched"])
        self.assertEqual(out[0]["kind"], "expense")

    def test_a_payment_worded_with_the_lenders_name(self):
        accounts = {**ACCOUNTS, "car": {**ACCOUNTS["car"], "bank": "Ally"}}
        out = classified([row("chk", 1, "ALLY PAYMNT 2291", -41000), row("car", 2, "PAYMENT", 41000)], accounts)
        self.assertTrue(out[0]["matched"])

    def test_a_loan_isnt_flipped_for_looking_like_payments(self):
        from budgetier.accounts import purchases_look_positive
        from budgetier.parse import ParsedFile, RawRow
        rows = [RawRow(date(2026, 1, d), "PAYMENT", 41000) for d in range(1, 8)]
        self.assertFalse(purchases_look_positive(ParsedFile(Path("car.csv"), rows, account_type="loan"), rows))
        self.assertTrue(purchases_look_positive(ParsedFile(Path("card.csv"), rows, account_type="checking"), rows))


class Balances(unittest.TestCase):
    def test_entered_as_owed_and_counted_against_you(self):
        accounts = {k: dict(v) for k, v in ACCOUNTS.items() if k in ("chk", "mtg")}
        pin_balance(accounts["mtg"], 25000000, date(2026, 1, 31))
        pin_balance(accounts["chk"], 500000, date(2026, 1, 31))
        s = snapshot([row("mtg", 2, "PAYMENT", 210000), row("chk", 2, "PAYROLL", 100)], accounts)
        self.assertEqual(s.by_id["mtg"].balance, -25000000)

    def test_a_banks_balance_whichever_way_its_signed(self):
        self.assertEqual(entered_balance("loan", -25000000), 25000000)
        self.assertEqual(entered_balance("loan", 25000000), 25000000)
        self.assertEqual(entered_balance("credit", -50000), 50000)
        self.assertEqual(entered_balance("checking", -50000), -50000)

    def test_an_exported_balance_column_counts_as_owed(self):
        accounts = {"car": dict(ACCOUNTS["car"])}
        s = snapshot([row("car", 2, "PAYMENT", 41000, balance=1200000)], accounts)
        self.assertEqual(s.by_id["car"].balance, -1200000)

    def test_names_that_say_loan(self):
        for name in ("Rocket Mortgage", "Auto Loan 0003", "Home Equity HELOC", "Personal Line of Credit"):
            self.assertEqual(_guess_type(name), "loan", name)
        for name, kind in (("Student Checking", "checking"), ("Visa Signature Card", "credit")):
            self.assertEqual(_guess_type(name), kind, name)


class NetWorth(unittest.TestCase):
    def setUp(self):
        self.accounts = {k: dict(v) for k, v in ACCOUNTS.items() if k in ("chk", "mtg", "ira", "card")}
        pin_balance(self.accounts["chk"], 1000000, date(2026, 3, 31))
        pin_balance(self.accounts["mtg"], 20000000, date(2026, 3, 31))
        pin_balance(self.accounts["ira"], 5000000, date(2026, 3, 31))
        rows = [row("chk", 5, "PAYROLL", 500000, month=m) for m in (1, 2, 3)]
        rows += [row("chk", 6, "ROCKET MORTGAGE", -200000, month=m) for m in (1, 2, 3)]
        rows += [row("mtg", 7, "PAYMENT", 200000, month=m) for m in (1, 2, 3)]
        rows += [row("mtg", 7, "INTEREST", -90000, month=m) for m in (1, 2, 3)]
        rows += [row("card", 9, "SHOP", -4000, month=m) for m in (1, 2, 3)]
        rows += [row("ira", 10, "DIVIDEND", 100, month=3)]
        self.s = snapshot(rows, self.accounts)

    def test_what_you_have_less_what_you_owe(self):
        v = views.net_worth(self.s, views.Choice("all"))
        self.assertEqual(v.months, ["2026-01", "2026-02", "2026-03"])
        self.assertEqual(v.now, 1000000 + 5000000 - 20000000)
        self.assertEqual([h.account.id for h in v.have], ["ira", "chk"])
        self.assertEqual([h.account.id for h in v.owe], ["mtg"])
        self.assertEqual([a.id for a in v.missing], ["card"])  # no balance, so left out rather than guessed

    def test_it_changes_with_what_was_paid_down(self):
        v = views.net_worth(self.s, views.Choice("all"))
        # Checking keeps 300,000 a month after the payment, and the loan shrinks by 110,000 a month.
        self.assertEqual(v.net[1] - v.net[0], 300000 + 110000)
        self.assertEqual((v.loan_paid, v.loan_interest), (600000, -270000))
        self.assertEqual(next(h for h in v.owe if h.account.id == "mtg").change, 220000)
        # The IRA arrives in March: it's in net worth from then, but not counted as gained.
        self.assertEqual(v.net[2] - v.net[1], 300000 + 110000 + 5000000)
        self.assertEqual(v.change, 2 * (300000 + 110000))

    def test_interest_is_spending_but_principal_isnt(self):
        o = views.overview(self.s, views.Choice("all"))
        self.assertEqual(o.spending, 90000 + 4000)  # a month

    def test_the_accounts_chosen_at_the_top(self):
        v = views.net_worth(self.s, views.Choice("all", frozenset({"chk"})))
        self.assertEqual(v.now, 1000000)
        self.assertEqual(v.owe, [])


class TheTab(QtCase):
    def test_it_shows_net_worth_and_a_loan_type_can_be_chosen(self):
        from PySide6.QtWidgets import QLabel, QTableWidget
        budget = fake.build(Path(self.dir) / "home")
        budget.ledger.accounts["mtg-0004"] = {"name": "Rocket Mortgage", "bank": "Rocket Mortgage", "number": "0004",
                                              "type": "loan", "invert_sign": False}
        pin_balance(budget.ledger.accounts["mtg-0004"], 25000000, fake.LAST)
        budget.ledger.rows.append(fake.row("mtg-0004", date(2026, 10, 2), "PAYMENT", 200000))
        budget.ledger.save()
        win = self.window(budget)
        win.show_tab("Net worth")
        page = win.pages["Net worth"].widget()
        words = [label.text() for label in page.findChildren(QLabel)]
        self.assertIn("Net worth", words)
        cells = [table.item(r, c).text() for table in page.findChildren(QTableWidget)
                 for r in range(table.rowCount()) for c in range(table.columnCount()) if table.item(r, c)]
        self.assertIn("Rocket Mortgage", cells)
        self.assertIn("-$250,000.00", cells)
        from budgetier.ui.importing import type_box
        self.assertGreaterEqual(type_box("loan").findData("loan"), 0)
