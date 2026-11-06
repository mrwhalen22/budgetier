import io
import unittest
from datetime import date
from unittest import mock

from budgetier import cli, pdf2csv
from budgetier.ledger import Ledger
from budgetier.parse import ParseError, _from_filename, parse_file, parse_money
from tests.support import Tmp


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


if __name__ == "__main__":
    unittest.main()
