import importlib.util
import io
import itertools
import subprocess
import sys
import tempfile
import time
import zipfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

from budgetier import analyze, cli, pdf2csv, service
from budgetier.ledger import Ledger
from budgetier.parse import ParseError, RawRow, parse_file, parse_money, _from_filename


class Tmp(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.dir = Path(self._dir.name)

    def csv(self, name, text, encoding="utf-8"):
        path = self.dir / name
        path.write_bytes(text.encode(encoding))
        return parse_file(path)


class Money(unittest.TestCase):
    def test_forms(self):
        for text, cents in [("12.34", 1234), ("-12.34", -1234), ("$1,234.50", 123450),
                            ("(12.34)", -1234), ("12.34-", -1234), ("12.34 CR", 1234),
                            ("12.34 DR", -1234), ("−12.00", -1200), ("", None), ("n/a", None)]:
            self.assertEqual(parse_money(text), cents, text)


class Formats(Tmp):
    def test_chase_checking_newest_first_keeps_balance_and_chronology(self):
        p = self.csv("Chase8123_Activity.CSV",
                     "Details,Posting Date,Description,Amount,Type,Balance,Check or Slip #\n"
                     "DEBIT,01/03/2026,COFFEE,-5.00,DEBIT_CARD,95.00,\n"
                     "CREDIT,01/02/2026,PAYCHECK,100.00,ACH_CREDIT,100.00,\n")
        self.assertEqual((p.bank, p.account, p.account_type), ("Chase", "8123", "checking"))
        self.assertEqual([r.description for r in p.rows], ["PAYCHECK", "COFFEE"])
        self.assertEqual(p.rows[1].balance, 9500)
        self.assertFalse(p.invert)

    def test_capital_one_card_debit_credit_columns(self):
        p = self.csv("export.csv",
                     "Transaction Date,Posted Date,Card No.,Description,Category,Debit,Credit\n"
                     "2026-01-02,2026-01-03,7890,SHOP,Merchandise,20.00,\n"
                     "2026-01-05,2026-01-06,7890,PAYMENT,Payment,,20.00\n")
        self.assertEqual([r.cents for r in p.rows], [-2000, 2000])
        self.assertEqual(p.rows[0].account, "7890")
        self.assertEqual((p.bank, p.account_type), ("Capital One", "credit"))

    def test_capital_one_360_unsigned_amount_with_type(self):
        p = self.csv("360.csv",
                     "Account Number,Transaction Description,Transaction Date,Transaction Type,"
                     "Transaction Amount,Balance\n"
                     "123456789,Deposit,01/02/26,Credit,50.00,150.00\n"
                     "123456789,Withdrawal,01/03/26,Debit,20.00,130.00\n")
        self.assertEqual([r.cents for r in p.rows], [5000, -2000])
        self.assertEqual(p.rows[0].account, "6789")
        self.assertEqual(p.rows[0].date, date(2026, 1, 2))

    def test_discover_marked_inverted(self):
        p = self.csv("Discover-Last12.csv", "Trans. Date,Post Date,Description,Amount,Category\n"
                                            "01/02/2026,01/02/2026,SHOP,20.00,Merchandise\n")
        self.assertTrue(p.invert)
        self.assertEqual(p.bank, "Discover")

    def test_amex_by_filename(self):
        p = self.csv("amex_activity_3007.csv", "Date,Description,Amount\n01/02/2026,SHOP,20.00\n")
        self.assertEqual((p.bank, p.account, p.invert, p.account_type),
                         ("American Express", "3007", True, "credit"))

    def test_bank_of_america_preamble(self):
        p = self.csv("stmt.csv",
                     "Description,,Summary Amt.\nBeginning balance as of 01/01/2026,,\"1,000.00\"\n"
                     "Total credits,,\"500.00\"\n\n"
                     "Date,Description,Amount,Running Bal.\n"
                     "01/01/2026,Beginning balance as of 01/01/2026,,\"1,000.00\"\n"
                     "01/02/2026,\"GROCER\",\"-25.00\",\"975.00\"\n")
        self.assertEqual(p.bank, "Bank of America")
        self.assertEqual(len(p.rows), 1)
        self.assertEqual(p.rows[0].balance, 97500)

    def test_wells_fargo_headerless(self):
        p = self.csv("WellsFargo_Checking_4455.csv",
                     '"01/02/2026","-25.00","*","","GROCERY STORE AUSTIN TX"\n'
                     '"01/03/2026","100.00","*","","DEPOSIT"\n')
        self.assertEqual((p.bank, p.account, p.account_type), ("Wells Fargo", "4455", "checking"))
        self.assertEqual(p.rows[0].description, "GROCERY STORE AUSTIN TX")

    def test_fifth_third_blocks_sorted_by_date(self):
        p = self.csv("fifth_third_export.CSV",
                     'Date,Description,"Check Number",Amount\n'
                     '06/04/2026,"EARLY PAY: ACME PAYROLL XXXXX4006 060426",,100.00\n'
                     '06/01/2026,"VENMO CASHOUT XXXXX4353 060126",,20.00\n'
                     '05/30/2026,"INTERNATIONAL TRANS FEE",,-0.24\n'
                     '07/06/2026,"WEB INITIATED PAYMENT AT VENMO PAYMENT XXX3472 070626",,-20.00\n'
                     '07/02/2026,"MOBILE DEPOSIT",,5.00\n')
        self.assertEqual((p.bank, p.account, p.account_type), ("Fifth Third", None, "checking"))
        self.assertEqual([(r.date.month, r.date.day) for r in p.rows],
                         [(5, 30), (6, 1), (6, 4), (7, 2), (7, 6)])
        self.assertTrue(p.sign_known)

    def test_usaa_layout_leaves_sign_and_type_open(self):
        p = self.csv("Usaa_4002.csv",
                     "Date,Description,Original Description,Category,Amount,Status\n"
                     "2026-10-26,Spectrum,Spectrum 855-707-7328 MO,Bills & Utilities,65.00,Posted\n"
                     "2026-10-31,Walmart,Walmart200015272,Category Pending,63.47,Pending\n")
        self.assertEqual(p.bank, "USAA")
        self.assertFalse(p.sign_known)
        self.assertEqual(len(p.rows), 1)

    def test_pending_rows_skipped(self):
        p = self.csv("citi_1111.csv", "Status,Date,Description,Debit,Credit\n"
                                      "Pending,01/05/2026,HOLD,10.00,\n"
                                      "Cleared,01/02/2026,SHOP,20.00,\n")
        self.assertEqual(len(p.rows), 1)
        self.assertTrue(p.warnings)

    def test_footer_and_bom_and_cp1252(self):
        p = self.csv("x.csv", "﻿Date,Description,Amount\n01/02/2026,CAFÉ,-3.00\nTotal,,-3.00\n")
        self.assertEqual(len(p.rows), 1)
        self.assertEqual(p.rows[0].description, "CAFÉ")
        p = self.csv("y.csv", "Date,Description,Amount\n01/02/2026,CAFÉ,-3.00\n", "cp1252")
        self.assertEqual(p.rows[0].description, "CAFÉ")

    def test_day_first_dates_detected_from_data(self):
        p = self.csv("z.csv", "Date,Description,Amount\n25/01/2026,A,-3.00\n03/02/2026,B,-3.00\n")
        self.assertEqual(p.rows[1].date, date(2026, 2, 3))

    def test_not_a_statement(self):
        with self.assertRaises(ParseError):
            self.csv("notes.csv", "name,age\nbob,3\n")

    def test_filename_hints(self):
        self.assertEqual(_from_filename("Chase1234_Activity20260101_20260201_20260215"), ("Chase", "1234"))
        self.assertEqual(_from_filename("MyCreditUnion_5678_jan"), ("MyCreditUnion", "5678"))
        self.assertEqual(_from_filename("HillCountryCU_Savings_4410"), ("HillCountryCU", "4410"))
        self.assertEqual(_from_filename("fifth_third_export"), ("Fifth Third", None))
        self.assertEqual(_from_filename("discover_card_2026-01"), ("Discover", None))
        self.assertEqual(_from_filename("transactions_2026"), (None, None))


def raw(day, text, cents, balance=None):
    return RawRow(date=date(2026, 1, day), description=text, cents=cents, balance=balance)


class Merge(Tmp):
    def test_overlap_adds_only_new_rows(self):
        led = Ledger(self.dir)
        first = [raw(1, "A", -100), raw(2, "B", -200)]
        second = [raw(2, "B", -200), raw(3, "C", -300)]
        led.merge("x", first, "1.csv")
        result = led.merge("x", second, "2.csv")
        self.assertEqual((result["added"], result["duplicates"]), (1, 1))
        self.assertEqual(len(led.rows), 3)

    def test_identical_rows_in_one_file_are_kept(self):
        led = Ledger(self.dir)
        coffee = [raw(1, "COFFEE", -500), raw(1, "COFFEE", -500)]
        led.merge("x", coffee, "1.csv")
        self.assertEqual(len(led.rows), 2)

    def test_reimport_is_a_no_op(self):
        led = Ledger(self.dir)
        rows = [raw(1, "COFFEE", -500), raw(1, "COFFEE", -500), raw(2, "B", -1)]
        led.merge("x", rows, "1.csv")
        self.assertEqual(led.merge("x", rows, "copy.csv")["added"], 0)

    def test_second_export_reveals_one_more_repeat(self):
        led = Ledger(self.dir)
        led.merge("x", [raw(1, "COFFEE", -500)], "1.csv")
        led.merge("x", [raw(1, "COFFEE", -500), raw(1, "COFFEE", -500)], "2.csv")
        self.assertEqual(len(led.rows), 2)

    def test_description_spacing_and_case_ignored(self):
        led = Ledger(self.dir)
        led.merge("x", [raw(1, "Coffee  Shop", -500)], "1.csv")
        self.assertEqual(led.merge("x", [raw(1, "COFFEE SHOP", -500)], "2.csv")["added"], 0)

    def test_same_row_on_another_account_is_separate(self):
        led = Ledger(self.dir)
        led.merge("x", [raw(1, "A", -100)], "1.csv")
        led.merge("y", [raw(1, "A", -100)], "2.csv")
        self.assertEqual(len(led.rows), 2)

    def test_round_trip_through_disk(self):
        led = Ledger(self.dir)
        led.accounts["x"] = {"name": "X", "bank": "B", "number": "1", "type": "checking"}
        led.merge("x", [raw(1, "A", -5), raw(2, "B", 123456, balance=-99)], "1.csv")
        led.save()
        again = Ledger(self.dir)
        self.assertEqual([r["cents"] for r in again.rows], [-5, 123456])
        self.assertEqual(again.rows[1]["balance"], -99)
        self.assertEqual(again.merge("x", [raw(1, "A", -5)], "2.csv")["added"], 0)


ACCOUNTS = {"chk": {"name": "Checking", "type": "checking"}, "card": {"name": "Card", "type": "credit"},
            "sav": {"name": "Savings", "type": "savings"}}


def row(account, day, text, cents, month=1, year=2026, balance=None):
    return {"date": date(year, month, day), "account": account, "description": text, "cents": cents,
            "balance": balance, "bank_category": ""}


class Classify(unittest.TestCase):
    def kinds(self, rows, rules=()):
        return [(r["kind"], r["category"]) for r in analyze.classify(rows, ACCOUNTS, list(rules))]

    def test_card_payment_is_transfer_both_sides(self):
        out = self.kinds([row("chk", 3, "CHASE CREDIT CRD AUTOPAY", -50000),
                          row("card", 4, "PAYMENT THANK YOU", 50000)])
        self.assertEqual(out, [("transfer", "Transfer")] * 2)

    def test_counterpart_is_pulled_in_by_amount_and_date(self):
        out = self.kinds([row("chk", 3, "ONLINE TRANSFER TO SAV", -40000),
                          row("sav", 3, "DEPOSIT FROM MOBILE", 40000)])
        self.assertEqual(out[1][0], "transfer")

    def test_unrelated_opposite_amounts_are_not_paired(self):
        out = self.kinds([row("chk", 3, "SOME SHOP", -2000), row("card", 4, "SOME SHOP REFUND", 2000)])
        self.assertEqual([k for k, _ in out], ["expense", "refund"])

    def test_mortgage_and_utility_autopay_stay_expenses(self):
        out = self.kinds([row("chk", 1, "WELLS FARGO HOME MTG PAYMENT", -150000),
                          row("card", 1, "COMCAST AUTOPAY", -8000)])
        self.assertEqual([k for k, _ in out], ["expense", "expense"])
        self.assertEqual(out[0][1], "Housing")

    def test_card_payment_known_only_from_bank_category(self):
        rows = [row("card", 8, "USAA Credit Card", 77726), row("chk", 11, "USAA FSB CC CC PAYMENT", -77726)]
        rows[0]["bank_category"] = "Credit Card Payment"
        out = analyze.classify(rows, ACCOUNTS, [])
        self.assertEqual([r["kind"] for r in out], ["transfer", "transfer"])
        self.assertTrue(all(r["matched"] for r in out))

    def test_bank_categories_for_pets_and_coffee(self):
        rows = [row("card", 1, "SOME PLACE", -100), row("card", 1, "OTHER PLACE", -100)]
        rows[0]["bank_category"] = "Pet Food & Supplies"
        rows[1]["bank_category"] = "Coffee Shops"
        self.assertEqual([c for _, c in self.kinds(rows)], ["Pets", "Dining"])

    def test_zelle_is_not_a_transfer(self):
        self.assertEqual(self.kinds([row("chk", 1, "ZELLE TRANSFER TO BOB", -2000)])[0],
                         ("expense", "Person to Person"))

    def test_fifth_third_descriptions(self):
        out = self.kinds([row("chk", 1, "WEB INITIATED PAYMENT AT CHASE CREDIT CRD EPAY 1000000001 060426", -5000),
                          row("chk", 1, "WEB INITIATED PAYMENT AT USAA FSB CC CC PAYMENT XXXXX4007 052826", -5000),
                          row("chk", 1, "WEB INITIATED PAYMENT AT USAA CREDIT CARD PAYMENT XXXXX4008 101326", -5000),
                          row("chk", 1, "WEB INITIATED PAYMENT AT SYNCHRONY BANK TRANSFER XXX 060426", -5000),
                          row("chk", 1, "WEB INITIATED PAYMENT AT USAA P&C PAYMENT 060426", -5000),
                          row("chk", 1, "WEB INITIATED PAYMENT AT CENTURY 21 REALTY WEB PMTS AB12CD 052926", -5000)])
        self.assertEqual(out[:3], [("estimate", analyze.ESTIMATED)] * 3)
        self.assertEqual(out[3], ("transfer", "Savings & Investing"))
        self.assertEqual(out[4:], [("expense", "Insurance"), ("expense", "Housing")])

    def test_issuer_names_need_whole_words(self):
        # PURCHASE contains CHASE.
        out = self.kinds([row("chk", 1, "DEBIT CARD PURCHASE AT ACME GAMES, BELLEVUE, WA ON 053026 "
                                        "FROM CARD#: XXXX4005", -500)])
        self.assertEqual(out[0][0], "expense")

    def test_money_back_from_online_savings_is_not_income(self):
        out = self.kinds([row("chk", 1, "WEB INITIATED PAYMENT AT SYNCHRONY BANK P2P NAME XXX 060426", 500000)])
        self.assertEqual(out[0], ("transfer", "Savings & Investing"))

    def test_store_card_payment_is_a_plain_transfer(self):
        out = self.kinds([row("chk", 1, "SYNCHRONY BANK PAYMENT 060426", -5000)])
        self.assertEqual(out[0], ("estimate", analyze.ESTIMATED))

    def test_card_payment_with_no_purchases_is_estimated_spending(self):
        out = analyze.classify([row("chk", 3, "CHASE CREDIT CRD EPAY", -130000)], ACCOUNTS, [])
        self.assertEqual(analyze.monthly_summary(out)[0]["spending"], 130000)
        self.assertEqual(analyze.find_recurring(out), [])

    def test_estimate_stops_once_the_card_is_imported(self):
        out = analyze.classify([row("chk", 3, "CHASE CREDIT CRD EPAY", -130000),
                                row("card", 3, "SHOP", -130000),
                                row("card", 4, "PAYMENT THANK YOU", 130000)], ACCOUNTS, [])
        self.assertEqual(analyze.monthly_summary(out)[0]["spending"], 130000)  # the purchase only
        self.assertEqual(out[0]["kind"], "transfer")

    def test_own_transfer_out_is_not_estimated_spending(self):
        out = self.kinds([row("chk", 3, "ONLINE TRANSFER TO SAV 4410", -40000)])
        self.assertEqual(out[0], ("transfer", "Transfer"))

    def test_user_rule_can_rule_out_an_estimate(self):
        import re
        rule = (re.compile("EPAY", re.I), "Transfer", None)
        self.assertEqual(self.kinds([row("chk", 3, "CHASE CREDIT CRD EPAY", -5000)], [rule])[0][0], "transfer")

    def test_card_payment_cannot_swallow_rent_of_the_same_size(self):
        out = analyze.classify([row("chk", 1, "CENTURY 21 WEB PMTS", -145000),
                                row("card", 3, "PAYMENT THANK YOU", 145000)], ACCOUNTS, [])
        self.assertEqual((out[0]["kind"], out[0]["category"]), ("expense", "Housing"))

    def test_transfer_cannot_swallow_income_of_the_same_size(self):
        out = analyze.classify([row("chk", 1, "VENMO CASHOUT", 50000),
                                row("sav", 2, "ONLINE TRANSFER TO CHECKING", -50000)], ACCOUNTS, [])
        self.assertEqual(out[0]["kind"], "income")

    def test_slow_payment_still_pairs(self):
        out = analyze.classify([row("card", 1, "PAYMENT THANK YOU", 50000),
                                row("chk", 8, "CHASE CREDIT CRD EPAY", -50000)], ACCOUNTS, [])
        self.assertTrue(all(r["matched"] for r in out))

    def test_income_words_never_apply_to_money_out(self):
        out = self.kinds([row("chk", 1, "GUSTO BISTRO", -3000)])
        self.assertNotEqual(out[0][1], "Income")

    def test_word_boundaries_in_rules(self):
        cases = {"KEENELAND HOSPITALITY": "Uncategorized", "PARENT TEACHER GROUP": "Uncategorized",
                 "RINALDI TAILOR": "Uncategorized", "HAIRS AND MORE": "Uncategorized",
                 "ENTERPRISE RENT-A-CAR": "Transport", "KROGER FUEL 123": "Transport",
                 "COSTCO GAS 44": "Transport", "SQ *THE BOOK NOOK": "Uncategorized",
                 "KROGER 123": "Groceries", "WALGREENS": "Health", "CITY HOSPITAL": "Health"}
        for text, want in cases.items():
            self.assertEqual(self.kinds([row("card", 1, text, -1000)])[0][1], want, text)

    def test_transfer_fee_is_not_a_transfer(self):
        self.assertEqual(self.kinds([row("chk", 1, "WIRE TRANSFER FEE", -2500)])[0][0], "expense")

    def test_merchant_spellings_merge(self):
        self.assertEqual(analyze.clean_merchant("Raising Cane's"), analyze.clean_merchant("RAISING CANES"))
        self.assertEqual(analyze.clean_merchant("Hiko-A-Mon"), analyze.clean_merchant("HIKO A MON"))

    def test_source_file_survives_classifying(self):
        rows = [{**row("chk", 1, "SHOP", -100), "source": "a.csv"}]
        self.assertEqual(analyze.classify(rows, ACCOUNTS, [])[0]["source"], "a.csv")

    def test_coverage_starts_with_checking(self):
        out = analyze.classify([row("card", 1, "SHOP", -500, month=1), row("sav", 1, "INT PMT", 5, month=1),
                                row("chk", 1, "ACME PAYROLL", 100000, month=5)], ACCOUNTS, [])
        self.assertEqual(analyze.coverage_start(out, ACCOUNTS), "2026-05")

    def test_money_to_investments_is_saved_not_spent(self):
        out = self.kinds([row("chk", 1, "WEB INITIATED PAYMENT AT ROBINHOOD DEBITS XXX 060426", -450000)])
        self.assertEqual(out[0], ("transfer", "Savings & Investing"))

    def test_deposits_and_claims(self):
        out = self.kinds([row("chk", 1, "5/3 ATM DEPOSIT - AB1234 100 MAIN ST ANYTOWN KY", 25000),
                          row("chk", 1, "MOBILE DEPOSIT", 2100),
                          row("chk", 1, "STATE FARM CLAIM PYMT 060426", 165152)])
        self.assertEqual([k for k, _ in out], ["income", "income", "refund"])

    def test_deposit_is_income_card_credit_is_refund(self):
        out = self.kinds([row("chk", 1, "MYSTERY DEPOSIT", 1000), row("card", 1, "MYSTERY CREDIT", 1000)])
        self.assertEqual([k for k, _ in out], ["income", "refund"])

    def test_user_rule_wins(self):
        import re
        rule = (re.compile("ZELLE", re.I), "Transfer", "Me")
        self.assertEqual(self.kinds([row("chk", 1, "ZELLE TO SELF", -2000)], [rule])[0], ("transfer", "Transfer"))

    def test_merchant_cleaning(self):
        for text, want in [("TST* FUEGO TACOS AUSTIN TX", "Fuego Tacos Austin"),
                           ("PURCHASE AUTHORIZED ON 01/02 SQ *BLUE BOTTLE", "Blue Bottle"),
                           ("PAYPAL *SOMESHOP", "Someshop"),
                           ("JANE DOE P2P JANE DOE", "Jane Doe"),
                           ("EARLY PAY: ACME CORP WIDGETS PAYROLL XXXXXXXXXXX4006 050826", "Acme Corp Widgets"),
                           ("DEBIT CARD PURCHASE AT ACME GAMES.COM 425, BELLEVUE, WA ON 053026 FROM CARD#: XXXX4005", "Acme Games")]:
            self.assertEqual(analyze.clean_merchant(text), want)


class Recurring(unittest.TestCase):
    def find(self, rows):
        return analyze.find_recurring(analyze.classify(rows, ACCOUNTS, []))

    def monthly(self, text, cents, day=3, months=6):
        return [row("card", day, text, cents, month=m) for m in range(1, months + 1)]

    def test_monthly_subscription_and_price_change(self):
        rows = self.monthly("NETFLIX.COM", -1549, months=5) + [row("card", 3, "NETFLIX.COM", -1799, month=6)]
        found = self.find(rows)
        self.assertEqual(len(found), 1)
        self.assertEqual((found[0]["merchant"], found[0]["cadence"]), ("Netflix", "Monthly"))
        self.assertAlmostEqual(found[0]["price_change"], 2.50)

    def test_variable_bill(self):
        rows = [row("chk", 9, "DUKE ENERGY", -c, month=i + 1) for i, c in enumerate([7000, 16000, 9000, 12000])]
        found = self.find(rows)
        self.assertTrue(found and found[0]["variable"])

    def test_irregular_shopping_is_not_recurring(self):
        rows = [row("card", d, "CORNER SHOP", -c) for d, c in [(1, 500), (2, 2000), (9, 700), (21, 4000)]]
        self.assertEqual(self.find(rows), [])

    def test_subscription_hidden_among_purchases(self):
        rows = self.monthly("AMZN PRIME", -1499, day=2)
        rows += [row("card", d, "AMZN MKTP", -c, month=m) for m, d, c in
                 [(1, 9, 8123), (1, 20, 2210), (2, 5, 4410), (3, 17, 1277), (4, 8, 9934)]]
        found = self.find(rows)
        self.assertEqual([round(f["amount"], 2) for f in found], [14.99])

    def test_similar_purchases_a_year_apart_are_not_a_bill(self):
        rows = [row("card", 5, "AMZN MKTP", -2000, month=2, year=2025),
                row("card", 7, "AMZN MKTP", -2045, month=2, year=2026),
                row("card", 9, "AMZN MKTP", -8000, month=3, year=2026),
                row("card", 20, "AMZN MKTP", -500, month=3, year=2026)]
        self.assertEqual(self.find(rows), [])

    def test_annual_fee_is_found(self):
        rows = [row("card", 5, "ACME CLUB DUES", -9900, month=2, year=y) for y in (2024, 2025, 2026)]
        self.assertEqual(self.find(rows)[0]["cadence"], "Annual")

    def test_biweekly_pay(self):
        rows = [row("chk", 1 + 14 * i if i < 2 else 1 + 14 * (i - 2), "ACME PAYROLL", 300000,
                    month=1 if i < 2 else 2) for i in range(4)]
        found = self.find(rows)
        self.assertEqual((found[0]["cadence"], found[0]["kind"]), ("Biweekly", "income"))

    def test_bill_that_moved_to_another_card_stays_active(self):
        rows = self.monthly("ABC GYM DUES", -2655, day=17, months=4)
        rows += [row("card", 28, "ANYTHING ELSE", -100, month=11),
                 row("chk", 1, "ABC GYM DUES", -5194, month=11), row("chk", 2, "OTHER", -100, month=11)]
        found = next(e for e in self.find(rows) if e["amount"] == 26.55)
        self.assertTrue(found["active"])
        self.assertEqual(found["account"], "chk")
        self.assertEqual(found["per_month"], 26.55)

    def test_bill_that_really_stopped_stays_stopped(self):
        rows = self.monthly("ABC GYM DUES", -2655, day=17, months=4)
        rows += [row("card", 28, "ANYTHING ELSE", -100, month=11), row("chk", 2, "OTHER", -100, month=11)]
        self.assertFalse(self.find(rows)[0]["active"])

    def test_stopped_payment(self):
        rows = self.monthly("SPOTIFY", -1199, months=3) + [row("chk", 28, "ANYTHING", -100, month=12)]
        rows[-1]["account"] = "card"
        self.assertFalse(self.find(rows)[0]["active"])


class AccountPrompt(Tmp):
    FILE = 'Date,Description,"Check Number",Amount\n05/06/2026,"ACME PAYROLL",,100.00\n'

    def run_cli(self, answers):
        inbox = self.dir / "inbox"
        inbox.mkdir(exist_ok=True)
        (inbox / "fifth_third_export.CSV").write_text(self.FILE)
        with mock.patch("sys.stdin.isatty", return_value=True), \
                mock.patch("builtins.input", side_effect=itertools.chain(answers, itertools.repeat(""))), \
                mock.patch("sys.stdout", io.StringIO()):
            return cli.main(["--home", str(self.dir)])

    def test_asks_once_then_offers_the_last_answer(self):
        self.assertEqual(self.run_cli(["1234", ""]), 0)  # number, then Enter accepts checking
        self.assertEqual(self.run_cli([""]), 0)  # Enter accepts [1234]; type isn't asked again
        led = Ledger(self.dir)
        self.assertEqual(list(led.accounts), ["fifth-third-1234"])
        self.assertEqual(len(led.rows), 1)
        self.assertEqual(len(list((self.dir / "imported").iterdir())), 2)

    def test_answered_type_is_used(self):
        self.assertEqual(self.run_cli(["1234", "2"]), 0)
        info = Ledger(self.dir).accounts["fifth-third-1234"]
        self.assertEqual((info["type"], info["name"]), ("savings", "Fifth Third Savings 1234"))

    def test_bad_answer_is_asked_again(self):
        self.assertEqual(self.run_cli(["1234", "visa", "3"]), 0)
        self.assertEqual(Ledger(self.dir).accounts["fifth-third-1234"]["type"], "credit")

    def test_unanswered_file_stays_in_inbox(self):
        self.assertEqual(self.run_cli([""]), 1)
        self.assertTrue((self.dir / "inbox" / "fifth_third_export.CSV").exists())


class CardSigns(Tmp):
    def importing(self, name, text):
        inbox = self.dir / "inbox"
        inbox.mkdir(exist_ok=True)
        (inbox / name).write_text(text)
        with mock.patch("sys.stdout", io.StringIO()):
            cli.main(["--home", str(self.dir)])
        return Ledger(self.dir)

    USAA = "Date,Description,Original Description,Category,Amount,Status\n"

    def test_usaa_card_purchases_become_spending(self):
        body = "".join(f"2026-10-{d:02d},Kroger,KROGER 123,Groceries,20.00,Posted\n" for d in range(1, 9))
        body += "2026-10-10,USAA Credit Card,USAA CREDIT CARD PAYMENT,Credit Card Payment,-100.00,Posted\n"
        led = self.importing("Usaa_4002.csv", self.USAA + body)
        info = led.accounts["usaa-4002"]
        self.assertEqual((info["type"], info["invert_sign"], info["name"]), ("credit", True, "USAA Card 4002"))
        out = analyze.classify(led.rows, led.accounts, [])
        self.assertEqual(sum(r["cents"] for r in out if r["kind"] == "expense"), -16000)
        self.assertEqual([r["kind"] for r in out if r["cents"] > 0], ["transfer"])

    def ask(self, answers, amounts):
        body = "".join(f"2026-10-{i + 1:02d},Kroger,KROGER 123,Groceries,{a},Posted\n"
                       for i, a in enumerate(amounts))
        inbox = self.dir / "inbox"
        inbox.mkdir(exist_ok=True)
        (inbox / "Usaa_4002.csv").write_text(self.USAA + body)
        with mock.patch("sys.stdin.isatty", return_value=True), \
                mock.patch("builtins.input", side_effect=itertools.chain(answers, itertools.repeat(""))), \
                mock.patch("sys.stdout", io.StringIO()):
            cli.main(["--home", str(self.dir)])
        return Ledger(self.dir)

    def test_person_confirms_positive_purchases(self):
        led = self.ask(["3", "y"], ["20.00"] * 6 + ["-5.00"])
        info = led.accounts["usaa-4002"]
        self.assertEqual((info["type"], info["invert_sign"]), ("credit", True))
        self.assertNotIn("sign_guessed", info)
        self.assertEqual(led.rows[0]["cents"], -2000)

    def test_person_overrides_a_wrong_guess(self):
        # Mostly deposits, which looks like a card until someone says otherwise.
        led = self.ask(["1", "n"], ["20.00"] * 6 + ["-5.00"])
        info = led.accounts["usaa-4002"]
        self.assertEqual((info["type"], info["invert_sign"]), ("checking", False))
        self.assertEqual(led.rows[0]["cents"], 2000)

    def test_enter_accepts_both_guesses(self):
        info = self.ask(["", ""], ["20.00"] * 6).accounts["usaa-4002"]
        self.assertEqual((info["type"], info["invert_sign"]), ("credit", True))

    def test_negative_sample_answered_yes_keeps_signs(self):
        info = self.ask(["3", "y"], ["-20.00"] * 6 + ["5.00"]).accounts["usaa-4002"]
        self.assertEqual(info["invert_sign"], False)

    def test_usaa_checking_keeps_its_signs(self):
        body = "".join(f"2026-10-{d:02d},Kroger,KROGER 123,Groceries,-20.00,Posted\n" for d in range(1, 9))
        body += "2026-10-10,Payroll,ACME PAYROLL,Paychecks,900.00,Posted\n"
        info = self.importing("Usaa_1111.csv", self.USAA + body).accounts["usaa-1111"]
        self.assertEqual((info["type"], info["invert_sign"]), ("checking", False))

    def test_a_later_small_file_cannot_flip_an_account(self):
        body = "".join(f"2026-10-{d:02d},Kroger,KROGER 123,Groceries,20.00,Posted\n" for d in range(1, 9))
        self.importing("Usaa_4002.csv", self.USAA + body)
        led = self.importing("Usaa_4002_b.csv", self.USAA + "2026-11-01,Kroger,KROGER 123,Groceries,5.00,Posted\n")
        self.assertEqual(led.rows[-1]["cents"], -500)


class EstimateDoubleCounting(unittest.TestCase):
    ACCOUNTS = {"chk": {"name": "Checking", "type": "checking", "bank": "Fifth Third"},
                "card": {"name": "Chase Card", "type": "credit", "bank": "Chase"},
                "amex": {"name": "Amex", "type": "credit", "bank": "American Express"}}

    def kind(self, rows):
        return analyze.classify(rows, self.ACCOUNTS, [])[0]["kind"]

    def test_payment_soon_after_history_starts_pays_older_purchases(self):
        self.assertEqual(self.kind([row("chk", 26, "CHASE CREDIT CRD EPAY", -100000, month=10),
                                    row("card", 22, "SHOP", -500, month=10)]), "estimate")

    def test_payment_deep_in_history_is_not_spending_again(self):
        rows = [row("chk", 26, "CHASE CREDIT CRD EPAY", -100000, month=10),
                row("card", 1, "SHOP", -100000, month=8)]
        self.assertEqual(self.kind(rows), "transfer")
        out = analyze.classify(rows, self.ACCOUNTS, [])
        self.assertEqual(sum(m["spending"] for m in analyze.monthly_summary(out)), 100000)
        titles = [c["title"] for c in analyze.checks(out, self.ACCOUNTS, [])]
        self.assertIn("Card payments not found on the card", titles)

    def test_issuer_nicknames_find_the_card(self):
        self.assertEqual(analyze.paid_cards("AMEX EPAYMENT ACH PMT", self.ACCOUNTS), ["amex"])
        self.assertEqual(analyze.paid_cards("CITI CARD PAYMENT", self.ACCOUNTS), [])


class DuplicateWarnings(unittest.TestCase):
    ACCOUNTS = {"a": {"name": "Card 1111", "type": "credit", "bank": "Chase"},
                "b": {"name": "Card 2222", "type": "credit", "bank": "Chase"}}

    def titles(self, rows):
        rows = [{**row(a, d, t, c), "source": s} for a, d, t, c, s in rows]
        out = analyze.classify(rows, self.ACCOUNTS, [])
        return [c["title"] for c in analyze.checks(out, self.ACCOUNTS, [])]

    def test_one_account_imported_under_two_numbers(self):
        rows = [(a, d, f"SHOP {d}", -1000 - d, "x.csv") for a in "ab" for d in range(1, 7)]
        self.assertIn("Same transactions on two accounts", self.titles(rows))

    def test_reworded_row_in_a_later_export(self):
        rows = [("a", 3, "SQ *PENDING CAFE", -2500, "old.csv"), ("a", 5, "BLUE CAFE AUSTIN", -2500, "new.csv")]
        self.assertIn("Possible duplicates between exports", self.titles(rows))

    def test_repeat_purchases_in_one_export_are_fine(self):
        rows = [("a", 3, "WORK CAFE", -859, "x.csv"), ("a", 5, "WORK CAFE", -859, "x.csv")]
        self.assertNotIn("Possible duplicates between exports", self.titles(rows))


class Balances(unittest.TestCase):
    ACCOUNTS = {"card": {"name": "Card", "type": "credit", "number": "1111"},
                "chk": {"name": "Checking", "type": "checking", "number": "2222"}}

    def card(self, on="2026-03-10", owed=1000.0):
        return {**self.ACCOUNTS, "card": {**self.ACCOUNTS["card"],
                                          "balance_anchor": {"date": on, "amount": owed}}}

    def rows(self):
        return [row("card", 5, "SHOP", -20000, month=2), row("card", 20, "SHOP", -30000, month=2),
                row("card", 8, "PAYMENT THANK YOU", 50000, month=3), row("card", 15, "SHOP", -10000, month=3),
                row("card", 2, "SHOP", -4000, month=4)]

    def test_rolls_forward_from_the_entered_amount(self):
        got = analyze.account_balances(self.rows(), self.card())["card"]
        self.assertEqual(got["current"], -114000)  # owed $1,000, then $100 and $40 of purchases
        self.assertTrue(got["calculated"])
        self.assertEqual(got["as_of"], "2026-04-02")

    def test_month_ends_walk_backward_and_forward(self):
        months = analyze.account_balances(self.rows(), self.card())["card"]["months"]
        self.assertEqual(months, {"2026-02": -150000, "2026-03": -110000, "2026-04": -114000})

    def test_older_history_does_not_change_today(self):
        rows = [row("card", 1, "OLD SHOP", -77700, month=1)] + self.rows()
        got = analyze.account_balances(rows, self.card())["card"]
        self.assertEqual(got["current"], -114000)
        self.assertEqual(got["months"]["2026-01"], -100000)  # Feb's $500 and Mar's payment cancel

    def test_row_on_the_entered_day_is_already_in_it(self):
        rows = [row("card", 10, "SHOP", -5000, month=3)]
        self.assertEqual(analyze.account_balances(rows, self.card())["card"]["current"], -100000)

    def test_payment_more_than_owed_leaves_a_credit(self):
        got = analyze.account_balances([row("card", 20, "PAYMENT THANK YOU", 150000, month=3)], self.card())
        self.assertEqual(got["card"]["current"], 50000)

    def test_checking_balance_is_not_flipped(self):
        accounts = {**self.ACCOUNTS, "chk": {**self.ACCOUNTS["chk"],
                                             "balance_anchor": {"date": "2026-03-01", "amount": 500.0}}}
        got = analyze.account_balances([row("chk", 2, "SHOP", -5000, month=3)], accounts)
        self.assertEqual(got["chk"]["current"], 45000)

    def test_export_balance_beats_an_entered_one(self):
        rows = [row("card", 12, "SHOP", -5000, month=3, balance=-2000)]
        got = analyze.account_balances(rows, self.card())["card"]
        self.assertEqual((got["current"], got["calculated"]), (-2000, False))

    def test_no_balance_is_flagged_for_cards_only(self):
        rows = analyze.classify([row("card", 1, "SHOP", -500), row("chk", 1, "SHOP", -500)], self.ACCOUNTS, [])
        titles = [c["title"] for c in analyze.checks(rows, self.ACCOUNTS, [])]
        self.assertEqual([t for t in titles if t.startswith("No balance")], ["No balance yet: Card"])


class BalanceCommands(Tmp):
    CSV = 'Date,Description,"Check Number",Amount\n05/06/2026,"ACME PAYROLL",,100.00\n'

    def setUp(self):
        super().setUp()
        (self.dir / "inbox").mkdir()
        (self.dir / "inbox" / "FifthThird_4003.csv").write_text(self.CSV)

    def run_cli(self, argv, answers=(), tty=True):
        with mock.patch("sys.stdin.isatty", return_value=tty), \
                mock.patch("builtins.input", side_effect=answers), \
                mock.patch("sys.stdout", io.StringIO()) as out:
            code = cli.main(["--home", str(self.dir), *argv])
        return code, out.getvalue()

    def anchor(self):
        return Ledger(self.dir).accounts["fifth-third-4003"].get("balance_anchor")

    def test_prompt_stores_the_answer_with_todays_date(self):
        self.run_cli([], ["", "$1,234.56"])  # type, then balance
        self.assertEqual(self.anchor(), {"date": date.today().isoformat(), "amount": 1234.56})

    def test_bad_answer_is_asked_again(self):
        self.run_cli([], ["", "lots", "10"])
        self.assertEqual(self.anchor()["amount"], 10.0)

    def test_enter_skips_and_is_not_asked_again(self):
        self.run_cli([], ["", ""])
        self.assertTrue(Ledger(self.dir).accounts["fifth-third-4003"]["balance_skipped"])
        self.run_cli([], [])  # any further question would raise StopIteration

    def test_no_answer_available_is_not_a_skip(self):
        self.run_cli([], ["", EOFError()])
        self.assertNotIn("balance_skipped", Ledger(self.dir).accounts["fifth-third-4003"])

    def test_set_balance_command_with_date(self):
        self.run_cli(["--set-balance", "4003", "250.00", "--as-of", "2026-05-01"], tty=False)
        self.assertEqual(self.anchor(), {"date": "2026-05-01", "amount": 250.0})

    def test_set_balance_replaces_a_skip(self):
        self.run_cli([], ["", ""])
        self.run_cli(["--set-balance", "4003", "9"], tty=False)
        info = Ledger(self.dir).accounts["fifth-third-4003"]
        self.assertNotIn("balance_skipped", info)

    def test_set_balance_rejects_unknown_account_and_amount(self):
        self.run_cli([], ["", ""])
        self.assertEqual(self.run_cli(["--set-balance", "9999", "5"], tty=False)[0], 2)
        self.assertEqual(self.run_cli(["--set-balance", "4003", "lots"], tty=False)[0], 2)

    def test_balance_shows_in_both_reports(self):
        self.run_cli(["--set-balance", "4003", "250.00"], tty=False)
        html = (self.dir / "output" / "budget.html").read_text(encoding="utf-8")
        self.assertIn('"calculated":true', html)
        from openpyxl import load_workbook
        ws = load_workbook(self.dir / "output" / "budget.xlsx")["Accounts"]
        self.assertEqual((ws["H5"].value, ws["I5"].value), (250, "Calculated"))


class AppCase(Tmp):
    CHASE = "Transaction Date,Post Date,Description,Category,Type,Amount,Memo\n"
    USAA = "Date,Description,Original Description,Category,Amount,Status\n"

    def setUp(self):
        super().setUp()
        self.src = self.dir / "picked"
        self.src.mkdir()
        self.budget = service.Budget(self.dir / "home")
        self.addCleanup(self.budget.cancel)

    def file(self, name, header, rows):
        path = self.src / name
        path.write_text(header + "".join(rows))
        return str(path)

    def chase(self, name, days):
        return self.file(name, self.CHASE, [f"10/{d:02d}/2026,10/{d:02d}/2026,SHOP {d},Shopping,Sale,-{d}.00,\n" for d in days])

    def add(self, *paths, **over):
        plan = self.budget.inspect(list(paths))
        answers = [{"id": i["id"], "bank": i["bank"], "number": i["number"] or "4001", "type": i["type"],
                    "spent": i["spent"] if i["askSign"] else None, "balance": "", **over} for i in plan["items"]]
        return self.budget.commit(answers)

    def rows(self):
        return sorted(r["description"] for r in self.budget.ledger.rows)


class AppImports(AppCase):
    def test_inspect_changes_nothing(self):
        plan = self.budget.inspect([self.chase("Chase_4001.csv", [1, 2])])
        item = plan["items"][0]
        self.assertEqual((item["bank"], item["number"], item["type"], item["known"], item["count"]),
                         ("Chase", "4001", "credit", False, 2))
        self.assertEqual(self.budget.ledger.rows, [])
        self.assertFalse(self.budget.ledger.accounts)

    def test_commit_saves_rows_account_and_a_copy_without_moving_the_original(self):
        path = self.chase("Chase_4001.csv", [1, 2])
        self.assertEqual(self.add(path)[0]["added"], 2)
        self.assertTrue(Path(path).exists())
        self.assertTrue((self.budget.imported / "Chase_4001.csv").exists())
        self.assertEqual(len(Ledger(self.budget.home).rows), 2)
        self.assertIn("Chase Card 4001", self.budget.html_path.read_text(encoding="utf-8"))

    def test_second_look_at_a_known_account_counts_new_rows(self):
        self.add(self.chase("a_4001.csv", [1, 2]))
        item = self.budget.inspect([self.chase("Chase_4001.csv", [2, 3, 4])])["items"][0]
        self.assertTrue(item["known"])
        self.assertEqual(item["new"], 2)

    def test_file_with_nothing_new_is_not_listed(self):
        path = self.chase("Chase_4001.csv", [1])
        self.add(path)
        self.assertEqual(self.add(path)[0], {"account": "Chase Card 4001", "added": 0, "duplicates": 1})
        self.assertEqual(len(self.budget.ledger.imports), 1)

    def test_person_answers_sign_and_balance(self):
        body = [f"2026-10-{d:02d},Kroger,KROGER,Groceries,20.00,Posted\n" for d in range(1, 8)]
        plan = self.budget.inspect([self.file("Usaa_4002.csv", self.USAA, body)])
        item = plan["items"][0]
        self.assertEqual((item["askSign"], item["type"], item["spent"]), (True, "credit", True))
        self.budget.commit([{"id": item["id"], "bank": "USAA", "number": "4002", "type": "credit",
                             "spent": True, "balance": "1,200.50"}])
        info = self.budget.ledger.accounts["usaa-4002"]
        self.assertTrue(info["invert_sign"])
        self.assertEqual(info["balance_anchor"]["amount"], 1200.5)
        self.assertEqual(self.budget.ledger.rows[0]["cents"], -2000)

    def test_answering_no_keeps_signs(self):
        body = [f"2026-10-{d:02d},Kroger,KROGER,Groceries,20.00,Posted\n" for d in range(1, 8)]
        item = self.budget.inspect([self.file("Usaa_4002.csv", self.USAA, body)])["items"][0]
        self.budget.commit([{"id": item["id"], "bank": "USAA", "number": "4002", "type": "savings",
                             "spent": False, "balance": ""}])
        self.assertEqual(self.budget.ledger.rows[0]["cents"], 2000)

    def test_missing_number_stops_everything(self):
        item = self.budget.inspect([self.file("chase.csv", self.CHASE, ["10/01/2026,10/01/2026,SHOP,Shopping,Sale,-1.00,\n"])])["items"][0]
        self.assertEqual(item["number"], "")
        with self.assertRaisesRegex(service.BudgetError, "last 4"):
            self.budget.commit([{"id": item["id"], "bank": "Chase", "number": "", "type": "credit"}])
        self.assertEqual(self.budget.ledger.rows, [])

    def test_bad_file_is_reported_and_good_one_still_offered(self):
        junk = self.src / "notes.csv"
        junk.write_text("name,age\nbob,3\n")
        other = self.src / "photo.png"
        other.write_text("x")
        plan = self.budget.inspect([str(junk), str(other), self.chase("Chase_4001.csv", [1])])
        self.assertEqual(len(plan["items"]), 1)
        self.assertEqual({e["file"] for e in plan["errors"]}, {"notes.csv", "photo.png"})

    def test_expired_review_is_refused(self):
        with self.assertRaisesRegex(service.BudgetError, "expired"):
            self.budget.commit([{"id": "0", "bank": "Chase", "number": "4001", "type": "credit"}])

    def test_removing_a_file_keeps_rows_another_file_covers(self):
        self.add(self.chase("a_4001.csv", [1, 2, 3]))
        self.add(self.chase("b_4001.csv", [3, 4]))
        result = self.budget.remove_import(self.budget.ledger.imports[0]["stored"])
        self.assertEqual(self.rows(), ["SHOP 3", "SHOP 4"])
        self.assertEqual(result["removed"], 2)
        self.assertEqual([p.name for p in self.budget.imported.iterdir()], ["b_4001.csv"])
        self.assertEqual(self.budget.ledger.imports[0]["added"], 2)
        self.assertEqual(len(Ledger(self.budget.home).rows), 2)

    def test_removing_the_later_file_also_works(self):
        self.add(self.chase("a_4001.csv", [1, 2, 3]))
        self.add(self.chase("b_4001.csv", [3, 4]))
        self.budget.remove_import(self.budget.ledger.imports[1]["stored"])
        self.assertEqual(self.rows(), ["SHOP 1", "SHOP 2", "SHOP 3"])

    def test_same_filename_twice_is_stored_separately_and_removable(self):
        self.add(self.chase("Chase_4001.csv", [1]))
        self.add(self.chase("Chase_4001.csv", [2]))
        stored = [i["stored"] for i in self.budget.ledger.imports]
        self.assertEqual(len(set(stored)), 2)
        self.budget.remove_import(stored[1])
        self.assertEqual(self.rows(), ["SHOP 1"])

    def test_removing_the_last_file_removes_the_account(self):
        self.add(self.chase("Chase_4001.csv", [1]))
        self.budget.remove_import(self.budget.ledger.imports[0]["stored"])
        self.assertFalse(self.budget.ledger.accounts)
        self.assertEqual(list(self.budget.imported.iterdir()), [])
        self.assertIn('"txns":[]', self.budget.html_path.read_text(encoding="utf-8"))

    def test_older_imports_without_a_stored_name_still_remove(self):
        self.add(self.chase("a_4001.csv", [1, 2]))
        self.add(self.chase("b_4001.csv", [3]))
        self.budget.ledger.imports[1]["stored"] = ""
        self.budget.remove_import("b_4001.csv")
        self.assertEqual(self.rows(), ["SHOP 1", "SHOP 2"])

    def test_lost_saved_copy_changes_nothing(self):
        self.add(self.chase("a_4001.csv", [1, 2]))
        self.add(self.chase("b_4001.csv", [3]))
        (self.budget.imported / "a_4001.csv").unlink()
        with self.assertRaisesRegex(service.BudgetError, "missing"):
            self.budget.remove_import("b_4001.csv")
        self.assertEqual(self.rows(), ["SHOP 1", "SHOP 2", "SHOP 3"])
        self.assertEqual(len(self.budget.ledger.imports), 2)
        self.assertTrue((self.budget.imported / "b_4001.csv").exists())

    def test_removing_an_account_leaves_others(self):
        self.add(self.chase("Chase_4001.csv", [1]))
        self.add(self.chase("Chase_2222.csv", [2]))
        self.budget.remove_account("chase-4001")
        self.assertEqual(list(self.budget.ledger.accounts), ["chase-2222"])
        self.assertEqual(self.rows(), ["SHOP 2"])
        self.assertEqual([p.name for p in self.budget.imported.iterdir()], ["Chase_2222.csv"])

    def test_rebuild_keeps_flipped_signs(self):
        body = [f"2026-10-{d:02d},Kroger {d},KROGER,Groceries,20.00,Posted\n" for d in range(1, 8)]
        one = self.file("Usaa_4002.csv", self.USAA, body)
        self.add(one)
        self.add(self.file("Usaa_4002_b.csv", self.USAA, ["2026-11-01,Later,LATER,Groceries,5.00,Posted\n"]))
        self.budget.remove_import(self.budget.ledger.imports[1]["stored"])
        self.assertTrue(all(r["cents"] == -2000 for r in self.budget.ledger.rows))

    def test_edit_account(self):
        self.add(self.chase("Chase_4001.csv", [1]))
        self.budget.update_account("chase-4001", "Sapphire", "credit", "$50.00", "2026-10-02")
        info = Ledger(self.budget.home).accounts["chase-4001"]
        self.assertEqual((info["name"], info["balance_anchor"]), ("Sapphire", {"date": "2026-10-02", "amount": 50.0}))
        with self.assertRaises(service.BudgetError):
            self.budget.update_account("chase-4001", "x", "credit", "lots", "")

    def test_export_workbook(self):
        with self.assertRaises(service.BudgetError):
            self.budget.export_workbook(self.dir / "x.xlsx")
        self.add(self.chase("Chase_4001.csv", [1]))
        self.budget.export_workbook(self.dir / "x.xlsx")
        self.assertTrue((self.dir / "x.xlsx").exists())

    def test_empty_app_has_a_page(self):
        self.assertTrue(self.budget.refresh().exists())

    def test_pdf_goes_through_conversion_and_both_files_are_kept(self):
        pdf = self.src / "Synchrony.pdf"
        pdf.write_bytes(b"%PDF")
        statement = pdf2csv.parse_pages(SynchronyPdf.PAGES)
        with mock.patch("budgetier.pdf2csv.read_pdf", return_value=statement):
            plan = self.budget.inspect([str(pdf)])
        item = plan["items"][0]
        self.assertEqual((item["bank"], item["number"], item["type"], item["hasBalance"]), ("Synchrony", "4004", "savings", True))
        self.budget.commit([{"id": item["id"], "bank": "Synchrony", "number": "4004", "type": "savings"}])
        self.assertEqual(sorted(p.name for p in self.budget.imported.iterdir()), ["Synchrony.pdf", "Synchrony_Savings_4004.csv"])
        self.assertEqual(self.budget.ledger.imports[0]["stored"], "Synchrony_Savings_4004.csv")

    def test_data_folder(self):
        with mock.patch.dict("os.environ", {"LOCALAPPDATA": "C:/x"}, clear=False):
            import os
            os.environ.pop("BUDGETIER_HOME", None)
            self.assertEqual(service.app_home(), Path("C:/x/Budgetier"))
        with mock.patch.dict("os.environ", {"BUDGETIER_HOME": "D:/y"}):
            self.assertEqual(service.app_home(), Path("D:/y"))


_spec = importlib.util.spec_from_file_location(
    "setup_main", Path(__file__).resolve().parents[1] / "packaging" / "setup_main.py")
setup_main = importlib.util.module_from_spec(_spec)
sys.modules["setup_main"] = setup_main
_spec.loader.exec_module(setup_main)


class Rules(AppCase):
    def setUp(self):
        super().setUp()
        self.add(self.file("Chase_4001.csv", self.CHASE, [
            "10/01/2026,10/01/2026,ZZYZX HARDWARE #12,,Sale,-40.00,\n",
            "10/02/2026,10/02/2026,ZZYZX HARDWARE #99,,Sale,-10.00,\n",
            "10/03/2026,10/03/2026,KROGER 123,Groceries,Sale,-5.00,\n"]))

    def categories(self):
        rows = analyze.classify(self.budget.ledger.rows, self.budget.ledger.accounts,
                                analyze.load_rules(self.budget.rules_path))
        return {r["description"]: (r["category"], r["merchant"]) for r in rows}

    def test_preview_counts_without_saving(self):
        p = self.budget.preview_rule("zzyzx hardware")
        self.assertEqual((p["count"], p["total"]), (2, -50))
        self.assertEqual(self.budget.rules(), [])

    def test_save_applies_across_history_and_reports(self):
        self.budget.save_rule(None, "ZZYZX HARDWARE", "Home", "Zzyzx")
        self.assertEqual(self.categories()["ZZYZX HARDWARE #12"], ("Home", "Zzyzx"))
        rule = self.budget.rules()[0]
        self.assertEqual((rule["text"], rule["advanced"], rule["count"]), ("ZZYZX HARDWARE", False, 2))
        self.assertIn('"rules":[{', self.budget.html_path.read_text(encoding="utf-8"))

    def test_text_is_literal_not_a_pattern(self):
        self.budget.save_rule(None, "A.B (C)*", "Home", "")
        rule = self.budget.rules()[0]
        self.assertEqual((rule["text"], rule["advanced"]), ("A.B (C)*", False))
        self.assertEqual(rule["count"], 0)

    def test_commas_and_quotes_survive(self):
        self.budget.save_rule(None, "KROGER", "Food, Etc", 'Joe "K" Mart')
        rule = self.budget.rules()[0]
        self.assertEqual((rule["category"], rule["merchant"]), ("Food, Etc", 'Joe "K" Mart'))
        self.assertEqual(self.categories()["KROGER 123"][0], "Food, Etc")

    def test_new_rule_beats_older_rule_and_keeps_comments(self):
        self.budget.save_rule(None, "ZZYZX", "Home", "")
        self.budget.save_rule(None, "ZZYZX HARDWARE #12", "Shopping", "")
        self.assertEqual(self.categories()["ZZYZX HARDWARE #12"][0], "Shopping")
        self.assertEqual(self.categories()["ZZYZX HARDWARE #99"][0], "Home")
        self.assertIn("# Your own categorization rules", self.budget.rules_path.read_text(encoding="utf-8"))

    def test_same_text_replaces_instead_of_duplicating(self):
        self.budget.save_rule(None, "ZZYZX", "Home", "")
        self.budget.save_rule(None, "zzyzx", "Shopping", "")
        self.assertEqual([r["category"] for r in self.budget.rules()], ["Shopping"])

    def test_edit_keeps_position(self):
        self.budget.save_rule(None, "ZZYZX", "Home", "")
        self.budget.save_rule(None, "KROGER", "Groceries", "")
        older = self.budget.rules()[1]
        self.budget.save_rule(older["line"], "ZZYZX HARD", "Shopping", "New Name")
        self.assertEqual([r["text"] for r in self.budget.rules()], ["KROGER", "ZZYZX HARD"])

    def test_delete_restores_automatic_category(self):
        self.budget.save_rule(None, "KROGER", "Home", "")
        self.budget.delete_rule(self.budget.rules()[0]["line"])
        self.assertEqual(self.categories()["KROGER 123"][0], "Groceries")

    def test_bad_input_is_refused(self):
        for args in (("ab", "Home", ""), ("ZZYZX", "", "")):
            with self.assertRaises(service.BudgetError):
                self.budget.save_rule(None, *args)
        with self.assertRaisesRegex(service.BudgetError, "valid"):
            self.budget.save_rule(None, "(unclosed", "Home", "", True)
        self.assertEqual(self.budget.rules(), [])

    def test_hand_written_pattern_is_shown_and_works(self):
        self.budget.save_rule(None, r"^ZZYZX\b.*#12", "Home", "", True)
        rule = self.budget.rules()[0]
        self.assertEqual((rule["advanced"], rule["count"]), (True, 1))

    def test_broken_hand_edit_does_not_stop_the_app(self):
        with self.budget.rules_path.open("a", encoding="utf-8") as f:
            f.write("(unclosed,Home,\nno category here\n")
        self.budget.refresh()
        self.assertEqual(self.budget.rules()[0]["broken"], True)
        self.assertEqual(self.categories()["KROGER 123"][0], "Groceries")

    def test_rules_file_without_a_header_still_gets_one(self):
        self.budget.rules_path.write_text("", encoding="utf-8")
        self.budget.save_rule(None, "KROGER", "Home", "")
        self.assertEqual(self.budget.rules()[0]["text"], "KROGER")

    def test_rules_appear_in_the_category_list(self):
        self.budget.save_rule(None, "KROGER", "Hobbies", "")
        self.assertIn('"allCategories":', self.budget.html_path.read_text(encoding="utf-8"))
        self.assertIn("Hobbies", self.budget.html_path.read_text(encoding="utf-8"))


class Budgets(Tmp):
    ACCOUNTS = {"bank-4001": {"name": "Checking", "type": "checking"}, "card-4002": {"name": "Card", "type": "credit"}}

    def row(self, day, cents, category="Groceries", kind="expense", account="bank-4001"):
        return {"date": date.fromisoformat(day), "cents": cents, "category": category, "kind": kind, "account": account}

    def report(self, rows, budgets):
        return analyze.budget_report(rows, self.ACCOUNTS, budgets)

    def test_amount_target_stays_the_same_each_month(self):
        rows = [self.row("2026-01-05", -10000), self.row("2026-02-27", -30000)]
        months = self.report(rows, {"Groceries": {"mode": "amount", "value": 25000}})["months"]
        self.assertEqual([m["targets"]["Groceries"] for m in months], [250, 250])
        self.assertEqual([m["spent"]["Groceries"] for m in months], [100, 300])

    def test_percent_target_follows_that_months_income(self):
        rows = [self.row("2026-01-01", 400000, "Income", "income"), self.row("2026-02-27", 600000, "Income", "income")]
        months = self.report(rows, {"Groceries": {"mode": "percent", "value": 10}})["months"]
        self.assertEqual([m["targets"]["Groceries"] for m in months], [400, 600])

    def test_month_in_progress_uses_recent_income(self):
        rows = [self.row(f"2026-0{m}-15", m * 100000, "Income", "income") for m in range(1, 6)]
        rows.append(self.row("2026-06-03", -500))
        last = self.report(rows, {"Groceries": {"mode": "percent", "value": 10}})["months"][-1]
        self.assertTrue(last["partial"])
        self.assertEqual((last["income"], last["base"], last["targets"]["Groceries"]), (0, 4000, 400))

    def test_first_month_in_progress_has_only_its_own_income(self):
        rows = [self.row("2026-01-02", 100000, "Income", "income")]
        month = self.report(rows, {"Groceries": {"mode": "percent", "value": 25}})["months"][0]
        self.assertEqual(month["targets"]["Groceries"], 250)

    def test_refunds_net_against_the_category(self):
        rows = [self.row("2026-01-02", -5000), self.row("2026-01-03", 2000, kind="refund")]
        self.assertEqual(self.report(rows, {})["months"][0]["spent"]["Groceries"], 30)

    def test_transfers_are_not_spending(self):
        rows = [self.row("2026-01-02", -5000, "Transfer", "transfer")]
        self.assertEqual(self.report(rows, {})["months"][0]["spent"], {})

    def test_months_before_checking_history_are_left_out(self):
        rows = [self.row("2026-01-02", -5000, account="card-4002"), self.row("2026-02-02", -5000)]
        self.assertEqual([m["month"] for m in self.report(rows, {})["months"]], ["2026-02"])

    def test_a_month_with_nothing_in_it_still_appears(self):
        rows = [self.row("2026-01-02", -5000), self.row("2026-03-02", -5000)]
        months = self.report(rows, {"Groceries": {"mode": "amount", "value": 100}})["months"]
        self.assertEqual([m["month"] for m in months], ["2026-01", "2026-02", "2026-03"])
        self.assertEqual(months[1]["spent"], {})

    def test_no_transactions_keeps_the_targets(self):
        report = self.report([], {"Groceries": {"mode": "amount", "value": 12345}})
        self.assertEqual(report, {"targets": [{"category": "Groceries", "mode": "amount", "value": 123.45}], "months": []})


class SavingBudgets(Tmp):
    def setUp(self):
        super().setUp()
        self.budget = service.Budget(self.dir / "home")
        self.addCleanup(self.budget.cancel)

    def test_amount_is_saved_in_cents(self):
        self.budget.save_budget("Groceries", "amount", "$1,200.50")
        self.assertEqual(self.budget.budgets(), {"Groceries": {"mode": "amount", "value": 120050}})

    def test_percent_accepts_a_percent_sign(self):
        self.budget.save_budget("Groceries", "percent", "12.5%")
        self.assertEqual(self.budget.budgets(), {"Groceries": {"mode": "percent", "value": 12.5}})

    def test_saving_again_replaces_the_target(self):
        self.budget.save_budget("Groceries", "amount", "100")
        self.budget.save_budget("Groceries", "percent", "10")
        self.assertEqual(self.budget.budgets(), {"Groceries": {"mode": "percent", "value": 10.0}})

    def test_budgets_survive_a_restart(self):
        self.budget.save_budget("Groceries", "amount", "100")
        self.assertEqual(service.Budget(self.dir / "home").budgets(), self.budget.budgets())

    def test_bad_targets_are_refused_and_nothing_is_saved(self):
        for category, mode, value in (("", "amount", "100"), ("Groceries", "amount", "0"), ("Groceries", "amount", "-5"),
                                      ("Groceries", "amount", "lots"), ("Groceries", "percent", "0"),
                                      ("Groceries", "percent", "101"), ("Groceries", "percent", "nan"),
                                      ("Groceries", "percent", "ten"), ("Groceries", "share", "10"),
                                      ("Income", "amount", "100"), ("Transfer", "percent", "10")):
            with self.assertRaises(service.BudgetError, msg=(category, mode, value)):
                self.budget.save_budget(category, mode, value)
        self.assertEqual(self.budget.budgets(), {})

    def test_delete(self):
        self.budget.save_budget("Groceries", "amount", "100")
        self.budget.delete_budget("Groceries")
        self.assertEqual(self.budget.budgets(), {})
        with self.assertRaises(service.BudgetError):
            self.budget.delete_budget("Groceries")

    def test_saved_budget_reaches_the_page(self):
        self.budget.save_budget("Groceries", "amount", "100")
        self.assertIn('"category":"Groceries"', self.budget.html_path.read_text(encoding="utf-8"))


_bump = importlib.util.spec_from_file_location(
    "bump_version", Path(__file__).resolve().parents[1] / "packaging" / "bump_version.py")
bump_version = importlib.util.module_from_spec(_bump)
_bump.loader.exec_module(bump_version)


class Versioning(Tmp):
    def test_each_part_raises_and_resets_what_follows(self):
        for part, want in (("patch", "1.2.4"), ("minor", "1.3.0"), ("major", "2.0.0")):
            self.assertEqual(bump_version.bump("1.2.3", part), want)

    def test_numbers_are_not_compared_as_text(self):
        self.assertEqual(bump_version.bump("1.9.9", "patch"), "1.9.10")

    def test_bad_input_is_refused(self):
        for version, part in (("1.2", "patch"), ("v1.2.3", "patch"), ("1.2.3", "huge")):
            with self.assertRaises(ValueError):
                bump_version.bump(version, part)

    def test_file_is_rewritten_with_only_the_new_number(self):
        version = self.dir / "VERSION"
        version.write_bytes(b"\xef\xbb\xbf1.2.3\r\n")
        with mock.patch.object(bump_version, "VERSION_FILE", version), \
                mock.patch.object(sys, "argv", ["bump_version.py", "minor"]), \
                mock.patch("sys.stdout", io.StringIO()) as out:
            self.assertEqual(bump_version.main(), 0)
        self.assertEqual(version.read_bytes(), b"1.3.0\n")
        self.assertEqual(out.getvalue().strip(), "1.3.0")


class Installer(Tmp):
    def payload(self, files, name="payload.zip"):
        path = self.dir / name
        with zipfile.ZipFile(path, "w") as z:
            for file, text in files.items():
                z.writestr(file, text)
        return path

    def setUp(self):
        super().setUp()
        self.target = self.dir / "Programs" / "Budgetier"

    def test_version_comes_from_the_version_file(self):
        root = Path(setup_main.__file__).resolve().parents[1]
        self.assertEqual(setup_main.VERSION, (root / "VERSION").read_text(encoding="utf-8").strip())
        self.assertRegex(setup_main.VERSION, r"^\d+\.\d+\.\d+$")

    def test_version_file_saved_by_notepad_still_reads(self):
        (self.dir / "VERSION").write_bytes(b"\xef\xbb\xbf2.3.4\r\n")
        with mock.patch.object(setup_main.sys, "_MEIPASS", str(self.dir), create=True):
            self.assertEqual(setup_main.read_version(), "2.3.4")

    def test_fresh_install_unpacks_nested_files(self):
        shares = []
        setup_main.unpack(self.payload({"Budgetier.exe": "x", "_internal/a.dll": "y"}), self.target, shares.append)
        self.assertEqual((self.target / "_internal" / "a.dll").read_text(), "y")
        self.assertEqual(shares[-1], 1)

    def test_update_replaces_old_files_and_leaves_no_leftovers(self):
        setup_main.unpack(self.payload({"Budgetier.exe": "old", "gone.dll": "x"}), self.target)
        setup_main.unpack(self.payload({"Budgetier.exe": "new"}), self.target)
        self.assertEqual((self.target / "Budgetier.exe").read_text(), "new")
        self.assertFalse((self.target / "gone.dll").exists())
        self.assertEqual([p.name for p in self.target.parent.iterdir()], ["Budgetier"])

    def test_damaged_payload_keeps_the_working_install(self):
        setup_main.unpack(self.payload({"Budgetier.exe": "old"}), self.target)
        bad = self.dir / "bad.zip"
        bad.write_bytes(b"not a zip")
        with self.assertRaisesRegex(setup_main.SetupError, "damaged"):
            setup_main.unpack(bad, self.target)
        self.assertEqual((self.target / "Budgetier.exe").read_text(), "old")

    def test_payload_without_the_app_keeps_the_working_install(self):
        setup_main.unpack(self.payload({"Budgetier.exe": "old"}), self.target)
        with self.assertRaisesRegex(setup_main.SetupError, "damaged"):
            setup_main.unpack(self.payload({"readme.txt": "x"}), self.target)
        self.assertEqual((self.target / "Budgetier.exe").read_text(), "old")
        self.assertEqual([p.name for p in self.target.parent.iterdir()], ["Budgetier"])

    def test_interrupted_earlier_update_is_cleaned_up(self):
        (self.target.parent / "Budgetier.new").mkdir(parents=True)
        (self.target.parent / "Budgetier.old").mkdir()
        setup_main.unpack(self.payload({"Budgetier.exe": "x"}), self.target)
        self.assertEqual([p.name for p in self.target.parent.iterdir()], ["Budgetier"])

    def test_refuses_while_the_app_is_open(self):
        with mock.patch.object(setup_main, "app_is_running", return_value=True), \
                mock.patch.object(setup_main, "unpack") as unpack:
            with self.assertRaisesRegex(setup_main.SetupError, "Close it"):
                setup_main.install(setup_main.Options(self.target))
        unpack.assert_not_called()

    def test_a_plain_folder_gets_its_own_budgetier_subfolder(self):
        docs = self.dir / "Documents"
        docs.mkdir()
        (docs / "taxes.pdf").write_text("mine")
        self.assertEqual(setup_main.resolve_target(docs), docs / "Budgetier")

    def test_folder_named_budgetier_is_used_as_is(self):
        self.assertEqual(setup_main.resolve_target(self.target), self.target)

    def test_refuses_a_budgetier_folder_holding_other_files(self):
        self.target.mkdir(parents=True)
        (self.target / "mine.txt").write_text("x")
        with self.assertRaisesRegex(setup_main.SetupError, "other files"):
            setup_main.resolve_target(self.target)

    def test_existing_install_is_allowed(self):
        self.target.mkdir(parents=True)
        (self.target / "Budgetier.exe").write_text("x")
        self.assertEqual(setup_main.resolve_target(self.target), self.target)

    def test_blank_and_relative_locations_are_refused(self):
        for bad in ("", "  ", "apps\\here"):
            with self.assertRaises(setup_main.SetupError):
                setup_main.resolve_target(bad)

    def test_moved_install_clears_the_old_copy_only_if_ours(self):
        old = self.dir / "old"
        old.mkdir()
        (old / "keep.txt").write_text("x")
        setup_main.remove_moved_install(old, self.target)
        self.assertTrue(old.exists())
        (old / "Budgetier.exe").write_text("x")
        setup_main.remove_moved_install(old, self.target)
        self.assertFalse(old.exists())
        self.target.mkdir(parents=True)
        (self.target / "Budgetier.exe").write_text("x")
        setup_main.remove_moved_install(self.target, self.target)
        self.assertTrue(self.target.exists())

    def test_writable_check_finds_nearest_existing_parent(self):
        setup_main.check_writable(self.dir / "a" / "b" / "Budgetier")

    def test_folder_that_refuses_writes_gets_a_clear_message(self):
        with mock.patch.object(Path, "touch", side_effect=PermissionError):
            with self.assertRaisesRegex(setup_main.SetupError, "can.t write"):
                setup_main.check_writable(self.dir / "Budgetier")

    def test_default_location_is_program_files(self):
        with mock.patch.dict("os.environ", {"ProgramW6432": "C:\\Program Files"}):
            self.assertEqual(setup_main.default_target(), Path("C:\\Program Files\\Budgetier"))

    def test_entry_is_registered_for_the_whole_pc_with_the_uninstaller(self):
        self.target.mkdir(parents=True)
        (self.target / "Budgetier.exe").write_text("x")
        written = {}
        key = mock.MagicMock()
        key.__enter__.return_value = key
        with mock.patch.object(setup_main.winreg, "CreateKey", return_value=key) as create, \
                mock.patch.object(setup_main.winreg, "SetValueEx",
                                  side_effect=lambda k, name, _, kind, value: written.__setitem__(name, value)):
            setup_main.register(self.target)
        self.assertEqual(create.call_args[0][0], setup_main.winreg.HKEY_LOCAL_MACHINE)
        self.assertEqual(written["DisplayName"], "Budgetier")
        self.assertEqual(written["UninstallString"], f'"{self.target / "uninstall.exe"}"')
        self.assertTrue(written["QuietUninstallString"].endswith("--silent"))

    def test_uninstall_refuses_a_folder_that_is_not_budgetier(self):
        (self.dir / "mine.txt").write_text("x")
        with mock.patch.object(setup_main.subprocess, "Popen") as popen:
            with self.assertRaisesRegex(setup_main.SetupError, "nothing was removed"):
                setup_main.uninstall(self.dir)
        popen.assert_not_called()
        self.assertTrue((self.dir / "mine.txt").exists())

    def test_uninstall_refuses_while_the_app_is_open(self):
        (self.dir / "Budgetier.exe").write_text("x")
        with mock.patch.object(setup_main, "app_is_running", return_value=True), \
                mock.patch.object(setup_main.subprocess, "Popen") as popen:
            with self.assertRaisesRegex(setup_main.SetupError, "Close it"):
                setup_main.uninstall(self.dir)
        popen.assert_not_called()

    def fake_install(self):
        self.target.mkdir(parents=True)
        (self.target / "_internal").mkdir()
        (self.target / "_internal" / "lib.dll").write_text("x")
        (self.target / "Budgetier.exe").write_text("x")
        (self.target / "uninstall.exe").write_text("x")

    def test_uninstall_clears_shortcuts_entries_and_program_at_once(self):
        self.fake_install()
        links = self.dir / "links"
        links.mkdir()
        (links / "Budgetier.lnk").write_text("x")
        with mock.patch.object(setup_main, "app_is_running", return_value=False), \
                mock.patch.object(setup_main, "_shell_folders", return_value=(links,)), \
                mock.patch.object(setup_main.winreg, "DeleteKey") as delete, \
                mock.patch.object(setup_main, "finish_removal") as finish:
            setup_main.uninstall(self.target)
        self.assertFalse((links / "Budgetier.lnk").exists())
        self.assertEqual({c.args[0] for c in delete.call_args_list},
                         {setup_main.winreg.HKEY_LOCAL_MACHINE, setup_main.winreg.HKEY_CURRENT_USER})
        self.assertEqual([p.name for p in self.target.iterdir()], ["uninstall.exe"])
        finish.assert_called_once()

    def test_reinstall_works_over_what_an_uninstall_leaves(self):
        self.fake_install()
        setup_main.remove_program(self.target)
        self.assertEqual(setup_main.resolve_target(self.target), self.target)
        setup_main.unpack(self.payload({"Budgetier.exe": "new"}), self.target)
        self.assertEqual((self.target / "Budgetier.exe").read_text(), "new")

    def test_half_removed_program_folder_counts_as_ours(self):
        self.fake_install()
        (self.target / "Budgetier.exe").unlink()
        self.assertEqual(setup_main.resolve_target(self.target), self.target)

    def test_final_cleanup_waits_for_the_uninstaller_then_removes_the_folder(self):
        self.target.mkdir(parents=True)
        (self.target / "uninstall.exe").write_text("x")
        running = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
        self.addCleanup(running.kill)
        cleanup = setup_main.finish_removal(self.target, [running.pid])
        time.sleep(1.5)
        self.assertTrue(self.target.exists())
        running.kill()
        running.wait()
        cleanup.wait(timeout=20)
        self.assertFalse(self.target.exists())

    def test_cleanup_copes_with_an_apostrophe_in_the_path(self):
        odd = self.dir / "Mat's Apps" / "Budgetier"
        odd.mkdir(parents=True)
        setup_main.finish_removal(odd, [999999]).wait(timeout=20)
        self.assertFalse(odd.exists())

    def test_old_per_user_copy_is_found_even_with_the_new_entry_present(self):
        old = self.dir / "old"
        old.mkdir()
        (old / "Budgetier.exe").write_text("x")
        with mock.patch.object(setup_main, "app_is_running", return_value=False), \
                mock.patch.object(setup_main, "resolve_target", return_value=self.target), \
                mock.patch.object(setup_main, "check_writable"), \
                mock.patch.object(setup_main, "installed_location", return_value=self.target), \
                mock.patch.object(setup_main, "user_install_location", return_value=old), \
                mock.patch.object(setup_main, "unpack"), mock.patch.object(setup_main, "set_shortcuts"), \
                mock.patch.object(setup_main, "register"), \
                mock.patch.object(setup_main, "forget_user_registration") as forget:
            setup_main.install(setup_main.Options(self.target))
        self.assertFalse(old.exists())
        forget.assert_called_once()

    def test_app_is_started_as_the_signed_in_user_not_as_admin(self):
        with mock.patch.object(setup_main.subprocess, "Popen") as popen:
            setup_main.launch(self.target)
        self.assertEqual(popen.call_args[0][0], ["explorer.exe", str(self.target / "Budgetier.exe")])


class Warnings(unittest.TestCase):
    ACCOUNTS = {"chk": {"name": "Checking", "type": "checking", "bank": "Fifth Third"},
                "card": {"name": "Chase Card", "type": "credit", "bank": "Chase"},
                "sav": {"name": "Savings", "type": "savings", "bank": "Synchrony"}}

    def titles(self, rows):
        out = analyze.classify(rows, self.ACCOUNTS, [])
        return [c["title"] for c in analyze.checks(out, self.ACCOUNTS, [])]

    def test_payment_before_card_history_asks_for_more_history(self):
        titles = self.titles([row("chk", 1, "CHASE CREDIT CRD EPAY", -5000, month=5),
                              row("chk", 2, "ACME PAYROLL", 100000, month=5),
                              row("card", 22, "SOME SHOP", -500, month=10)])
        self.assertIn("Export more history: Chase Card", titles)
        self.assertNotIn("Transfers out with no matching account", titles)

    def test_card_that_was_never_imported_still_warns(self):
        titles = self.titles([row("chk", 1, "CITI CARD ONLINE PAYMENT", -5000, month=5),
                              row("card", 1, "SOME SHOP", -500, month=4)])
        self.assertIn("Transfers out with no matching account", titles)

    def test_savings_withdrawal_before_checking_history_is_not_a_mystery(self):
        titles = self.titles([row("sav", 1, "FIFTH THIRD BANK TRANSFER", -5000, month=1),
                              row("chk", 1, "ACME PAYROLL", 100000, month=5)])
        self.assertNotIn("Transfers out with no matching account", titles)

    def test_savings_history_does_not_stand_in_for_income(self):
        titles = self.titles([row("sav", 1, "INT PMT", 500, month=1), row("card", 1, "SOME SHOP", -500, month=1),
                              row("chk", 1, "ACME PAYROLL", 100000, month=5)])
        self.assertIn("Income history is shorter than card history", titles)

    def test_cards_reaching_back_past_income_are_flagged(self):
        titles = self.titles([row("card", 1, "SOME SHOP", -500, month=1),
                              row("chk", 1, "ACME PAYROLL", 100000, month=5)])
        self.assertIn("Income history is shorter than card history", titles)


def word(text, x0, top):
    return {"text": text, "x0": x0, "top": top}


def txn(top, day, description, amount, balance, *extra):
    words = [word(day, 21.6, top), word(description, 206.2, top), word(amount, 530, top),
             word(balance, 527, top + 19)]
    words += [word(text, 206.2, top + 19 * (i + 1)) for i, text in enumerate(extra)]
    return words


HEADER = [word("P.O. Box 669802, Dallas, TX 75266-0955", 20.7, 156), word("Nov 05, 2026", 513, 41),
          word("HIGH YIELD SAVINGS -", 20.7, 195), word("XXXXXXXX4004", 194, 195),
          word("Current Balance: $110.00", 453, 263), word("Pending Transactions", 20.7, 291),
          word("No pending transactions", 20.7, 326), word("Posted Transactions", 20.7, 374)]
FOOT = [word("https://securelogin.synchronybank.com/accountDetails/Savings/x", 21.3, 814),
        word("1/2", 559, 814)]


class SynchronyPdf(Tmp):
    PAGES = [HEADER + txn(406, "Sep 25, 2026", "INT PMT", "$10.00", "$110.00")
             + txn(457, "Sep 04, 2026", "NAME P2P", "$200.00", "$100.00", "NAME") + FOOT,
             [word("12345678901", 206.2, 27)]  # wrapped onto the next page
             + txn(58, "Aug 25, 2026", "FIFTH THIRD BANK TRANSFER", "-$300.00", "-$100.00") + FOOT]

    def test_rows_read_in_order_with_signs(self):
        s = pdf2csv.parse_pages(self.PAGES)
        self.assertEqual((s.account, s.is_savings, s.filename), ("4004", True, "Synchrony_Savings_4004.csv"))
        self.assertEqual([r.date.isoformat() for r in s.rows], ["2026-08-25", "2026-09-04", "2026-09-25"])
        self.assertEqual([r.cents for r in s.rows], [-30000, 20000, 1000])
        self.assertEqual(s.rows[-1].balance, 11000)

    def test_description_continues_across_a_page_break(self):
        self.assertEqual(pdf2csv.parse_pages(self.PAGES).rows[1].description, "NAME P2P NAME 12345678901")

    def test_wrong_balance_writes_nothing(self):
        pages = [HEADER + txn(406, "Sep 25, 2026", "INT PMT", "$99.00", "$110.00")
                 + txn(457, "Sep 04, 2026", "NAME P2P", "$200.00", "$100.00") + FOOT]
        with self.assertRaisesRegex(pdf2csv.ConvertError, "don't add up"):
            pdf2csv.parse_pages(pages)

    def test_missing_amount_is_refused(self):
        pages = [HEADER + txn(406, "Sep 25, 2026", "INT PMT", "$10.00", "$110.00")[:3] + FOOT]
        with self.assertRaisesRegex(pdf2csv.ConvertError, "one amount"):
            pdf2csv.parse_pages(pages)

    def test_other_pdfs_are_refused(self):
        with self.assertRaisesRegex(pdf2csv.ConvertError, "Synchrony"):
            pdf2csv.parse_pages([[word("Some resume", 20, 20)]])

    def test_pending_section_is_ignored(self):
        pending = txn(330, "Oct 30, 2026", "HOLD", "$5.00", "$115.00")
        s = pdf2csv.parse_pages([HEADER[:-1] + pending + HEADER[-1:]
                                 + txn(406, "Sep 25, 2026", "INT PMT", "$10.00", "$110.00") + FOOT])
        self.assertEqual(len(s.rows), 1)

    def test_written_csv_imports_as_savings_with_positive_deposits(self):
        csv_path = pdf2csv.write_csv(pdf2csv.parse_pages(self.PAGES), self.dir)
        p = parse_file(csv_path)
        self.assertEqual((p.bank, p.account, p.account_type), ("Synchrony", "4004", "savings"))
        self.assertEqual([r.cents for r in p.rows], [-30000, 20000, 1000])
        self.assertEqual(p.rows[-1].balance, 11000)

    def test_inbox_pdf_is_converted_imported_and_archived(self):
        inbox = self.dir / "inbox"
        inbox.mkdir()
        (inbox / "Synchrony.pdf").write_bytes(b"%PDF")
        statement = pdf2csv.parse_pages(self.PAGES)
        with mock.patch("budgetier.pdf2csv.read_pdf", return_value=statement), \
                mock.patch("sys.stdin.isatty", return_value=False), \
                mock.patch("sys.stdout", io.StringIO()):
            self.assertEqual(cli.main(["--home", str(self.dir)]), 0)
        self.assertEqual(sorted(p.name for p in (self.dir / "imported").iterdir()),
                         ["Synchrony.pdf", "Synchrony_Savings_4004.csv"])
        self.assertEqual(len(Ledger(self.dir).rows), 3)

    def test_unreadable_pdf_stays_in_inbox(self):
        inbox = self.dir / "inbox"
        inbox.mkdir()
        (inbox / "Scan.pdf").write_bytes(b"not a pdf")
        with mock.patch("sys.stdout", io.StringIO()):
            self.assertEqual(cli.main(["--home", str(self.dir)]), 1)
        self.assertTrue((inbox / "Scan.pdf").exists())


class SavingsTransfers(unittest.TestCase):
    def out(self, rows):
        return analyze.classify(rows, ACCOUNTS, [])

    def test_p2p_into_savings_is_a_transfer_not_income(self):
        self.assertEqual(self.out([row("sav", 4, "NAME P2P NAME", 450000)])[0]["kind"], "transfer")

    def test_interest_is_income(self):
        got = self.out([row("sav", 4, "INT PMT", 5613)])[0]
        self.assertEqual((got["kind"], got["merchant"]), ("income", "Interest"))

    def test_both_sides_imported_counts_once(self):
        got = self.out([row("chk", 2, "WEB INITIATED PAYMENT AT SYNCHRONY BANK TRANSFER XXX", -450000),
                        row("sav", 4, "NAME P2P NAME", 450000)])
        self.assertTrue(all(r["matched"] for r in got))
        self.assertEqual({r["category"] for r in got}, {"Transfer"})

    def test_one_side_imported_still_counts_as_saved(self):
        got = self.out([row("chk", 2, "WEB INITIATED PAYMENT AT SYNCHRONY BANK TRANSFER XXX", -450000)])
        self.assertEqual(got[0]["category"], "Savings & Investing")


class Gaps(unittest.TestCase):
    def test_gap_found_and_overlap_ignored(self):
        imports = [{"account": "a", "first": "2026-01-01", "last": "2026-02-28"},
                   {"account": "a", "first": "2026-02-01", "last": "2026-03-31"},
                   {"account": "a", "first": "2026-06-01", "last": "2026-06-30"}]
        self.assertEqual(analyze.coverage_gaps(imports)["a"], [(date(2026, 3, 31), date(2026, 6, 1))])


if __name__ == "__main__":
    unittest.main()
