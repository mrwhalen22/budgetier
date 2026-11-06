import io
import itertools
import unittest
from datetime import date
from unittest import mock

from budgetier import analyze, cli
from budgetier.ledger import Ledger
from tests.support import Tmp


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


if __name__ == "__main__":
    unittest.main()
