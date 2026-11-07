import unittest
from pathlib import Path
from unittest import mock

from budgetier import analyze, pdf2csv, service
from budgetier.ledger import Ledger
from tests import test_parse
from tests.support import AppCase, Tmp


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
        statement = pdf2csv.parse_pages(test_parse.SynchronyPdf.PAGES)
        with mock.patch("budgetier.pdf2csv.read_pdf", return_value=statement):
            plan = self.budget.inspect([str(pdf)])
        item = plan["items"][0]
        self.assertEqual((item["bank"], item["number"], item["type"], item["hasBalance"]), ("Synchrony", "4004", "savings", True))
        self.budget.commit([{"id": item["id"], "bank": "Synchrony", "number": "4004", "type": "savings"}])
        self.assertEqual(sorted(p.name for p in self.budget.imported.iterdir()), ["Synchrony.pdf", "Synchrony_Savings_4004.csv"])
        self.assertEqual(self.budget.ledger.imports[0]["stored"], "Synchrony_Savings_4004.csv")

    def test_data_folder(self):
        with mock.patch.dict("os.environ", {"LOCALAPPDATA": "C:/x"}, clear=False), \
                mock.patch.object(service.sys, "platform", "win32"):
            import os
            os.environ.pop("BUDGETIER_HOME", None)
            self.assertEqual(service.app_home(), Path("C:/x/Budgetier"))
        with mock.patch.dict("os.environ", {"BUDGETIER_HOME": "D:/y"}):
            self.assertEqual(service.app_home(), Path("D:/y"))

    def test_data_folder_on_a_mac(self):
        with mock.patch.dict("os.environ", {"LOCALAPPDATA": "C:/x"}, clear=False), \
                mock.patch.object(service.sys, "platform", "darwin"), \
                mock.patch.object(service.Path, "home", return_value=Path("/Users/pat")):
            import os
            os.environ.pop("BUDGETIER_HOME", None)
            self.assertEqual(service.app_home(), Path("/Users/pat/Library/Application Support/Budgetier"))


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

    def test_a_name_with_special_characters_finds_itself(self):
        path = self.file("Chase_4002.csv", self.CHASE, ["10/04/2026,10/04/2026,SQ *JOE'S (A&B) CAFE+ #1,,Sale,-5.00,\n"])
        self.add(path, number="4002")
        self.assertEqual(self.budget.preview_rule("sq *joe's (a&b) cafe+ #1")["count"], 1)
        self.budget.save_rule(None, "SQ *JOE'S (A&B) CAFE+ #1", "Dining", "Joe's")
        rule = self.budget.rules()[0]
        self.assertEqual((rule["text"], rule["advanced"], rule["count"]), ("SQ *JOE'S (A&B) CAFE+ #1", False, 1))
        self.assertEqual(self.categories()["SQ *JOE'S (A&B) CAFE+ #1"], ("Dining", "Joe's"))

    def test_suggestion_previews_as_a_match(self):
        path = self.file("Chase_4002.csv", self.CHASE, ["10/04/2026,10/04/2026,TST* A&B CAFE,,Sale,-5.00,\n"])
        self.add(path, number="4002")
        text = self.budget.suggest_rule("Whatever", ["TST* A&B CAFE"])["text"]
        self.assertEqual(self.budget.preview_rule(text)["count"], 1)

    def test_saving_reports_what_the_rule_matches(self):
        self.assertEqual(self.budget.save_rule(None, "ZZYZX", "Home", ""), {"count": 2})

    def test_a_covered_transaction_opens_its_rule(self):
        self.budget.save_rule(None, "ZZYZX", "Home", "Zzyzx")
        found = self.budget.suggest_rule("Zzyzx", ["ZZYZX HARDWARE #12"])
        self.assertEqual((found["rule"]["text"], found["rule"]["category"]), ("ZZYZX", "Home"))
        self.assertTrue(found["rule"]["line"])

    def test_the_rule_that_applies_is_the_one_opened(self):
        self.budget.save_rule(None, "ZZYZX", "Home", "")
        self.budget.save_rule(None, "ZZYZX HARDWARE #12", "Shopping", "")
        self.assertEqual(self.budget.suggest_rule("x", ["ZZYZX HARDWARE #12"])["rule"]["category"], "Shopping")
        self.assertEqual(self.budget.suggest_rule("x", ["ZZYZX HARDWARE #99"])["rule"]["category"], "Home")

    def test_a_rule_elsewhere_still_gets_a_suggestion(self):
        self.budget.save_rule(None, "ZZYZX", "Home", "")
        self.assertEqual(self.budget.suggest_rule("Kroger", ["KROGER 123"]), {"text": "KROGER"})

    def test_a_broken_rule_does_not_stop_a_suggestion(self):
        with self.budget.rules_path.open("a", encoding="utf-8") as f:
            f.write("(unclosed,Home,\n")
        self.assertEqual(self.budget.suggest_rule("Kroger", ["KROGER 123"]), {"text": "KROGER"})

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


class SingleTransactions(AppCase):
    def setUp(self):
        super().setUp()
        self.add(self.chase("Chase_4001.csv", [1, 2]))
        first = self.budget.ledger.rows[0]
        self.tx = {"date": first["date"].isoformat(), "account": first["account"], "cents": first["cents"],
                   "description": first["description"], "n": 0}

    def analysed(self):
        return self.budget._analysis()[0]

    def test_one_transaction_changes_and_the_others_dont(self):
        self.budget.save_edit(self.tx, "Gifts", "Birthday")
        first, second = self.analysed()
        self.assertEqual((first["category"], first["merchant"], first["edited"]), ("Gifts", "Birthday", True))
        self.assertEqual((second["category"], second["edited"]), ("Shopping", False))

    def test_an_edit_outranks_a_rule_saved_later(self):
        self.budget.save_edit(self.tx, "Gifts", "Birthday")
        self.budget.save_rule(None, "SHOP", "Home", "")
        self.assertEqual([r["category"] for r in self.analysed()], ["Gifts", "Home"])

    def test_undoing_lets_the_rules_back_in(self):
        self.budget.save_edit(self.tx, "Gifts", "")
        self.budget.clear_edit(self.tx)
        self.assertEqual(self.analysed()[0]["category"], "Shopping")
        with self.assertRaises(service.BudgetError):
            self.budget.clear_edit(self.tx)

    def test_an_edit_survives_a_restart_and_reaches_the_page(self):
        self.budget.save_edit(self.tx, "Gifts", "Birthday")
        again = service.Budget(self.budget.home)
        self.assertEqual(again._analysis()[0][0]["category"], "Gifts")
        self.assertIn('"Birthday","Gifts","expense",-1.0,1]', again.html_path.read_text(encoding="utf-8"))

    def test_an_edit_survives_its_file_being_removed_and_added_again(self):
        self.budget.save_edit(self.tx, "Gifts", "")
        self.budget.remove_import("Chase_4001.csv")
        self.add(self.chase("Chase_4001.csv", [1, 2]))
        self.assertEqual(self.analysed()[0]["category"], "Gifts")

    def test_refused_and_nothing_saved(self):
        for tx, category in ((self.tx, " "), ({**self.tx, "cents": 1}, "Gifts"), ({"date": "x"}, "Gifts"),
                             ({**self.tx, "n": "one"}, "Gifts"), ({**self.tx, "n": 1}, "Gifts")):
            with self.assertRaises(service.BudgetError, msg=tx):
                self.budget.save_edit(tx, category, "")
        self.assertFalse(self.budget.edits_path.exists())

    def test_a_damaged_edits_file_is_kept_and_the_app_still_opens(self):
        self.budget.edits_path.write_text("{oops", encoding="utf-8")
        again = service.Budget(self.budget.home)
        again.refresh()
        self.assertEqual((again.home / "edits.damaged.json").read_text(encoding="utf-8"), "{oops")
        self.assertIn("transaction changes couldn't be read", again.html_path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
