"""Your data must survive bad files, crashes and impatient clicks."""
import json
import os
import threading
import unittest
from pathlib import Path
from unittest import mock

from budgetier import analyze, app, cli, service, storage
from budgetier.ledger import Ledger
from budgetier.parse import ParseError, parse_file, parse_money
from budgetier.service import Budget, BudgetError
from tests.support import Tmp

DAYS = range(1, 9)


class Case(Tmp):
    def setUp(self):
        super().setUp()
        self.budget = Budget(self.dir / "home")
        self.addCleanup(self.budget.cancel)

    def csv(self, name, rows, header="Date,Description,Amount"):
        path = self.dir / name
        path.write_text(header + "\n" + "\n".join(rows) + "\n", encoding="utf-8")
        return path

    def coffee(self, name="Testbank_1234.csv"):
        return self.csv(name, [f"01/{d:02d}/2026,COFFEE {d},-5.00" for d in DAYS])

    def bring_in(self, path, **changes):
        plan = self.budget.inspect([str(path)])
        return self.budget.commit([{"id": i["id"], "bank": i["bank"] or "Testbank", "number": i["number"] or "1234",
                                    "type": i["type"], "balance": "", "spent": True, **changes} for i in plan["items"]])

    def reopened(self):
        return Budget(self.budget.home)


class BadFiles(Case):
    def test_things_that_only_look_like_numbers_are_not_amounts(self):
        for text in ("NaN", "sNaN", "Infinity", "-inf"):
            self.assertIsNone(parse_money(text))

    def test_a_nan_balance_does_not_stop_the_file(self):
        path = self.csv("Testbank_1234.csv", ["01/02/2026,COFFEE,-5.00,NaN"], "Date,Description,Amount,Balance")
        self.assertIsNone(parse_file(path).rows[0].balance)

    def test_a_bad_file_does_not_stop_the_good_ones(self):
        huge = self.dir / "Testbank_2222.csv"
        huge.write_text('Date,Description,Amount\n01/02/2026,"' + "x" * 140000 + '",-5.00\n', encoding="utf-8")
        cut_off = self.dir / "Testbank_3333.csv"
        cut_off.write_bytes(b"\xff\xfeD\x00a\x00t")
        plan = self.budget.inspect([str(self.coffee()), str(huge), str(cut_off)])
        self.assertEqual(len(plan["items"]), 1)
        self.assertEqual({e["file"] for e in plan["errors"]}, {huge.name, cut_off.name})

    def test_a_crash_while_reading_one_file_is_reported_for_that_file(self):
        good = self.coffee()
        real = service.parse_file
        with mock.patch.object(service, "parse_file", side_effect=lambda p: real(p) if p == good else 1 / 0):
            with self.assertLogs("budgetier", "ERROR"):
                plan = self.budget.inspect([str(good), str(self.coffee("Testbank_5555.csv"))])
        self.assertEqual((len(plan["items"]), plan["errors"][0]["file"]), (1, "Testbank_5555.csv"))

    def test_broken_csv_is_a_parse_error(self):
        path = self.dir / "x.csv"
        path.write_text("a,b\n" + '"' + "y" * 140000, encoding="utf-8")
        with self.assertRaises(ParseError):
            parse_file(path)


class CorrectedNumbers(Case):
    def test_removing_a_file_keeps_rows_whose_number_was_corrected_in_review(self):
        header = "Date,Description,Amount,Account Number"
        self.bring_in(self.csv("a.csv", [f"01/{d:02d}/2026,COFFEE {d},-5.00,1111" for d in DAYS], header))
        self.bring_in(self.csv("b.csv", [f"02/{d:02d}/2026,TEA {d},-5.00,2222" for d in DAYS], header),
                      bank="Testbank", number="1111")
        first = next(i for i in self.budget.ledger.imports if i["file"] == "a.csv")
        self.assertEqual(self.budget.remove_import(first["stored"]), {"removed": 8})
        self.assertEqual({r["description"][:3] for r in self.reopened().ledger.rows}, {"TEA"})

    def test_an_older_import_with_a_corrected_number_still_rebuilds(self):
        header = "Date,Description,Amount,Account Number"
        self.bring_in(self.csv("a.csv", [f"01/{d:02d}/2026,COFFEE {d},-5.00,1111" for d in DAYS], header))
        self.bring_in(self.csv("b.csv", [f"02/{d:02d}/2026,TEA {d},-5.00,2222" for d in DAYS], header),
                      bank="Testbank", number="1111")
        for entry in self.budget.ledger.imports:
            entry["file_account"] = ""  # as saved by versions before this one
        first = next(i for i in self.budget.ledger.imports if i["file"] == "a.csv")
        self.budget.remove_import(first["stored"])
        self.assertEqual(len(self.budget.ledger.rows), 8)

    def test_a_file_that_no_longer_matches_changes_nothing(self):
        header = "Date,Description,Amount,Account Number"
        self.bring_in(self.csv("a.csv", [f"01/{d:02d}/2026,COFFEE {d},-5.00,1111" for d in DAYS], header))
        self.bring_in(self.csv("b.csv", [f"02/{d:02d}/2026,TEA {d},-5.00,2222" for d in DAYS], header),
                      bank="Testbank", number="1111")
        for entry in self.budget.ledger.imports:
            entry["file_account"] = "9999"
        first = next(i for i in self.budget.ledger.imports if i["file"] == "a.csv")
        with self.assertRaisesRegex(BudgetError, "Nothing was changed"):
            self.budget.remove_import(first["stored"])
        self.assertEqual(len(self.budget.ledger.rows), 16)


class BankTextInTheReport(Case):
    def test_a_description_cannot_change_how_the_page_reads_its_data(self):
        """A browser takes `<!-- <script>` as an escape that hides the closing tag, and the page stays blank."""
        texts = ["<!-- <script>", "</script><b>", "<!--"]
        self.bring_in(self.csv("Testbank_1234.csv", [f"01/0{i + 2}/2026,{t},-5.00" for i, t in enumerate(texts)]))
        page = self.budget.html_path.read_text(encoding="utf-8")
        data = page.split('<script id="data" type="application/json">')[1].split("</script>")[0]
        self.assertNotIn("<", data)
        self.assertCountEqual([t[2] for t in json.loads(data)["txns"]], texts)


class FailedChanges(Case):
    def test_a_file_moved_after_review_leaves_nothing_behind(self):
        path = self.coffee()
        plan = self.budget.inspect([str(path)])
        path.unlink()
        answer = {"id": plan["items"][0]["id"], "bank": "Testbank", "number": "1234", "type": "checking",
                  "balance": "100", "spent": True}
        with self.assertRaisesRegex(BudgetError, "choose it again"):
            self.budget.commit([answer])
        self.assertEqual((self.budget.ledger.rows, self.budget.ledger.imports, self.budget.ledger.accounts), ([], [], {}))
        self.assertEqual(list(self.budget.imported.iterdir()), [])

    def test_a_failed_save_during_import_can_be_retried(self):
        path = self.coffee()
        plan = self.budget.inspect([str(path)])
        answer = {"id": plan["items"][0]["id"], "bank": "Testbank", "number": "1234", "type": "checking",
                  "balance": "", "spent": True}
        with mock.patch.object(self.budget.ledger, "save", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                self.budget.commit([answer])
        self.assertEqual(list(self.budget.imported.iterdir()), [])
        self.assertEqual(self.budget.commit([answer])[0]["added"], 8)
        self.assertEqual(self.reopened().ledger.imports[0]["stored"], path.name)

    def test_an_unexpected_failure_during_removal_restores_everything(self):
        self.bring_in(self.coffee())
        key = self.budget.ledger.imports[0]["stored"]
        with mock.patch.object(self.budget, "_rebuild", side_effect=ValueError("surprise")):
            with self.assertRaises(ValueError):
                self.budget.remove_import(key)
        self.assertEqual(len(self.budget.ledger.rows), 8)
        self.assertEqual(len(self.budget.ledger.imports), 1)

    def test_a_rejected_account_edit_changes_nothing(self):
        self.bring_in(self.coffee())
        account = next(iter(self.budget.ledger.accounts))
        with self.assertRaises(BudgetError):
            self.budget.update_account(account, "Renamed", "savings", "abc", "")
        self.assertEqual(self.budget.ledger.accounts[account]["type"], "checking")
        self.assertNotEqual(self.budget.ledger.accounts[account]["name"], "Renamed")


class DamagedFiles(Case):
    def test_a_damaged_budgets_file_is_kept_and_the_app_still_opens(self):
        self.budget.budgets_path.write_text('{"Dining": {"mo', encoding="utf-8")
        again = self.reopened()
        again.refresh()
        self.assertEqual(again.budgets(), {})
        self.assertEqual((again.home / "budgets.damaged.json").read_text(encoding="utf-8"), '{"Dining": {"mo')
        self.assertIn("budgets couldn't be read", again.html_path.read_text(encoding="utf-8"))

    def test_good_budgets_survive_beside_a_bad_one(self):
        good = {"mode": "amount", "value": 5000}
        self.budget.budgets_path.write_text(json.dumps({"Dining": good, "Fun": 50}), encoding="utf-8")
        again = self.reopened()
        self.assertEqual(again.budgets(), {"Dining": good})
        self.assertEqual(json.loads(again.budgets_path.read_text(encoding="utf-8")), {"Dining": good})

    def test_healthy_budgets_are_left_alone(self):
        self.budget.save_budget("Dining", "percent", "10")
        self.budget.refresh()
        self.assertEqual(self.budget.notices, [])
        self.assertEqual(list(self.budget.home.glob("*.damaged.json")), [])

    def test_damaged_accounts_stop_with_directions(self):
        self.bring_in(self.coffee())
        self.budget.ledger.save()  # makes a backup to point at
        self.budget.ledger.accounts_path.write_text('{"x": {', encoding="utf-8")
        with self.assertRaisesRegex(storage.DataError, r"accounts\.json\.bak"):
            Ledger(self.budget.home)

    def test_with_no_backup_it_does_not_promise_one(self):
        self.budget.ledger.accounts_path.write_text('{"x": {', encoding="utf-8")
        with self.assertRaises(storage.DataError) as caught:
            Ledger(self.budget.home)
        self.assertNotIn(".bak", str(caught.exception))

    def test_a_damaged_ledger_stops_with_directions(self):
        self.bring_in(self.coffee())
        self.budget.ledger.path.write_text("date,account\nnot a date,x\n", encoding="utf-8")
        with self.assertRaisesRegex(storage.DataError, r"ledger\.csv"):
            Ledger(self.budget.home)

    def test_rows_with_no_account_are_kept_and_pointed_out(self):
        self.bring_in(self.coffee())
        self.budget.ledger.accounts_path.write_text("{}", encoding="utf-8")
        again = self.reopened()
        again.refresh()
        info = again.ledger.accounts["testbank-1234"]
        self.assertTrue(info["recovered"])
        self.assertIn("Check this account", again.html_path.read_text(encoding="utf-8"))
        again.update_account("testbank-1234", "Everyday", "checking", "", "")
        self.assertNotIn("recovered", again.ledger.accounts["testbank-1234"])

    def test_ledger_saved_by_excel_with_a_marker_still_loads(self):
        self.bring_in(self.coffee())
        path = self.budget.ledger.path
        path.write_bytes(b"\xef\xbb\xbf" + path.read_bytes())
        self.assertEqual(len(Ledger(self.budget.home).rows), 8)


class RulesFile(Case):
    def test_excels_old_encoding_does_not_stop_the_app(self):
        self.bring_in(self.csv("Testbank_1234.csv", [f"01/{d:02d}/2026,CAFÉ {d},-5.00" for d in DAYS]))
        self.budget.rules_path.write_bytes("match,category,merchant\nCAFÉ,Dining,Café\n".encode("cp1252"))
        again = self.reopened()
        again.refresh()
        self.assertEqual([(r["text"], r["count"]) for r in again.rules()], [("CAFÉ", 8)])

    def test_excels_utf8_marker_is_not_a_rule(self):
        self.budget.rules_path.write_bytes(b"\xef\xbb\xbfmatch,category,merchant\nCOFFEE,Dining,Coffee\n")
        self.assertEqual([r["text"] for r in self.budget.rules()], ["COFFEE"])

    def test_the_list_and_the_categorizer_agree_on_what_a_rule_is(self):
        self.budget.rules_path.write_text("match,category,merchant\n# COFFEE,Dining,\nNO CATEGORY,,\nTEA,Dining,\n",
                                          encoding="utf-8")
        self.assertEqual([r["text"] for r in self.budget.rules()], ["TEA"])
        self.assertEqual([p.pattern for p, _, _ in analyze.load_rules(self.budget.rules_path)], ["TEA"])


class Saving(Tmp):
    def test_files_saved_together_stay_as_they_were_if_one_fails(self):
        a, b = self.dir / "a.txt", self.dir / "b.txt"
        a.write_text("old a", encoding="utf-8")
        b.write_text("old b", encoding="utf-8")
        with mock.patch.object(storage.os, "fsync", side_effect=[None, OSError("disk full")]):
            with self.assertRaises(OSError):
                storage.write_files({a: "new a", b: "new b"})
        self.assertEqual((a.read_text(encoding="utf-8"), b.read_text(encoding="utf-8")), ("old a", "old b"))
        self.assertEqual(sorted(p.name for p in self.dir.iterdir()), ["a.txt", "b.txt"])

    def test_every_saved_file_keeps_a_backup(self):
        ledger = Ledger(self.dir)
        ledger.save()
        ledger.save()
        self.assertTrue(all((self.dir / "data" / n).exists() for n in ("ledger.csv.bak", "imports.csv.bak")))
        self.assertTrue((self.dir / "accounts.json.bak").exists())

    def test_a_new_name_is_found_for_a_taken_file(self):
        (self.dir / "a.csv").write_text("", encoding="utf-8")
        self.assertRegex(storage.unique_path(self.dir, "a.csv").name, r"^a\.\d{8}-\d{6}-\d{6}\.csv$")
        self.assertEqual(storage.unique_path(self.dir, "b.csv").name, "b.csv")


class TakingTurns(Case):
    def test_page_calls_never_overlap(self):
        api = app.Api(self.budget)
        replies = []
        threads = [threading.Thread(target=lambda c=c: replies.append(api.save_budget(c, "amount", "50")))
                   for c in (f"Category {i}" for i in range(12))]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertTrue(all(r["ok"] for r in replies), replies)
        self.assertEqual(len(self.budget.budgets()), 12)

    def test_an_unexpected_error_reaches_the_page_and_the_log(self):
        api = app.Api(self.budget)
        with mock.patch.object(self.budget, "delete_rule", side_effect=RuntimeError("surprise")):
            with self.assertLogs("budgetier", "ERROR"):
                reply = api.delete_rule("x")
        self.assertFalse(reply["ok"])
        self.assertIn("didn't finish", reply["error"])

    def test_an_expected_problem_shows_its_own_words(self):
        self.assertEqual(app.Api(self.budget).delete_budget("Dining"),
                         {"ok": False, "error": "That budget is already gone."})

    def test_a_failed_call_lets_the_next_one_run(self):
        api = app.Api(self.budget)
        api.delete_budget("Dining")
        self.assertTrue(api.save_budget("Dining", "amount", "50")["ok"])


class CommandLine(Tmp):
    def test_it_waits_for_the_app_to_close(self):
        lock = storage.hold_lock(self.dir)
        self.addCleanup(lock.close)
        with mock.patch("sys.stdout"):
            self.assertEqual(cli.main(["--home", str(self.dir)]), 2)
        self.assertFalse((self.dir / "inbox").exists())

    def test_it_explains_damaged_data(self):
        (self.dir / "accounts.json").write_text("{", encoding="utf-8")
        with mock.patch("builtins.print") as printed:
            self.assertEqual(cli.main(["--home", str(self.dir)]), 2)
        self.assertIn("accounts.json", str(printed.call_args))

    def test_it_releases_the_data_when_done(self):
        with mock.patch("sys.stdout"):
            cli.main(["--home", str(self.dir)])
        lock = storage.hold_lock(self.dir)
        self.addCleanup(lock.close)
        self.assertIsNotNone(lock)


class Startup(Tmp):
    def run_main(self):
        with mock.patch.object(app, "app_home", return_value=self.dir), \
                mock.patch.object(app, "_alert") as alert, \
                mock.patch.object(app.webview, "create_window") as self.window, mock.patch.object(app.webview, "start"), \
                mock.patch.object(app, "log"), mock.patch.object(app.logging, "basicConfig"), \
                mock.patch.object(app.logging.handlers, "RotatingFileHandler"):
            return app.main(), alert

    def test_the_whole_page_is_not_made_unselectable(self):
        """pywebview does that by default, and WebKit can carry it into text fields."""
        self.run_main()
        self.assertIs(self.window.call_args[1]["text_select"], True)

    def test_a_second_copy_says_so(self):
        lock = storage.hold_lock(self.dir)
        self.addCleanup(lock.close)
        code, alert = self.run_main()
        self.assertEqual(code, 1)
        self.assertIn("already open", alert.call_args[0][0])

    def test_damaged_data_shows_its_directions(self):
        (self.dir / "accounts.json").write_text("{", encoding="utf-8")
        code, alert = self.run_main()
        self.assertEqual(code, 1)
        self.assertIn("accounts.json", alert.call_args[0][0])

    def test_normal_start_opens_the_window(self):
        with mock.patch.dict(os.environ, {"BUDGETIER_SELF_CHECK": ""}):
            code, alert = self.run_main()
        self.assertEqual(code, 0)
        alert.assert_not_called()

    def test_self_check_writes_what_the_page_reports(self):
        window = mock.Mock()
        window.evaluate_js.return_value = '{"failed": []}'
        result = Path(self.dir) / "result.json"
        app._self_check(window, str(result))
        report = json.loads(result.read_text(encoding="utf-8"))
        self.assertEqual(report["failed"], [])
        self.assertGreater(report["certificates"], 0)
        self.assertIn("secure_store", report)
        window.destroy.assert_called_once()


if __name__ == "__main__":
    unittest.main()
