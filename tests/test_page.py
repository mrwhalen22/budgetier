"""The dashboard page, used the way a person uses it. See tests/browser.py."""
import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

from budgetier.ledger import _money
from tests.browser import UNSORTED, PageCase, build


class EveryTab:
    def test_every_tab_draws(self):
        for name in self.js("TABS"):
            self.tab(name)
            self.assertTrue(self.text("#view").strip(), name)

    def test_a_phone_never_scrolls_sideways(self):
        self.page = self.open_page(self.budget.html_path, 390, 800)
        self.assertFalse(self.js("document.documentElement.scrollWidth > innerWidth"))


class Dialogs:
    def test_esc_closes_a_plain_form(self):
        self.tab("Rules")
        self.page.click("[data-act=rule-new]")
        self.dialog_open()
        self.press("Escape")
        self.dialog_open(False)

    def test_esc_on_review_cancels_the_import(self):
        self.page.click("#addFiles")
        self.dialog_open()
        self.press("Escape")
        self.dialog_open(False)
        self.assertEqual(len(self.calls("cancel")), 1)

    def test_esc_on_files_added_still_refreshes(self):
        self.page.click("#addFiles")
        self.page.click("[data-modal=import]")
        self.until("document.querySelector('#modal h2').textContent === 'Files added'")
        self.mark_page()
        self.press("Escape")
        self.wait_for_reload()

    def test_esc_waits_while_something_is_saving(self):
        self.js("""showModal('T', '', '', '<button class="btn" data-modal="close">Cancel</button><button class="btn primary" disabled>Saving...</button>')""")
        self.press("Escape")
        self.page.wait_for_timeout(150)
        self.assertTrue(self.js("modal.open"))

    def test_an_empty_rule_form_shows_no_error(self):
        self.tab("Rules")
        self.page.click("[data-act=rule-new]")
        self.dialog_open()
        self.assertEqual(self.text("#rPreview").strip(), "")


class Rows:
    def open_first_row(self):
        self.tab("Transactions")
        self.page.focus("#tx tr[data-tx]")
        self.press("Enter")
        self.dialog_open()

    def test_a_row_opens_from_the_keyboard_and_enter_saves(self):
        self.open_first_row()
        self.assertTrue(self.page.is_visible("#modal .field .code"))
        self.page.select_option("#rCat", index=2)
        self.page.click("#rMatch")
        self.mark_page()
        self.press("Enter")
        self.wait_for_reload()
        self.toast("Rule saved. It matches 3 transactions.")

    def test_largest_rows_open_too(self):
        self.tab("Largest")
        self.page.click("#view tr[data-tx]")
        self.dialog_open()

    def test_a_row_a_rule_covers_opens_that_rule(self):
        self.js("window.ruleReply = {ok: true, rule: {line: 'KROGER,Groceries,', text: 'KROGER', merchant: 'Kroger', category: 'Groceries', advanced: false}}")
        self.open_first_row()
        self.assertEqual(self.text("#modal h2"), "Edit rule")
        self.assertEqual(self.page.input_value("#rName"), "Kroger")
        self.assertIn("already covers", self.text("#modal .modal-head"))

    def test_clear_filters_appears_and_clears(self):
        self.tab("Overview")
        self.page.click("#cats .hbar")
        self.until("document.getElementById('clearTx')")
        self.assertTrue(self.page.is_visible("#clearTx"))
        self.page.click("#clearTx")
        self.until("document.getElementById('clearTx').hidden")
        self.assertEqual((self.js("S.txcat"), self.page.input_value("#cat")), ("", ""))


class ThisMonth:
    def test_a_month_in_progress_says_so_and_compares(self):
        section = self.text(".now")
        self.assertIn("so far", section)
        self.assertRegex(section, r"Compared with Sep")
        self.assertRegex(section, r"by day 15")
        self.assertIn("Left in budgets", section)

    def test_its_spending_is_the_months(self):
        spent = self.js("money(monthly(TX, [MONTHS[MONTHS.length - 1]])[0].spending)")
        self.assertIn(spent, self.text(".now"))

    def test_bills_still_to_come(self):
        self.assertIn("Bills still to come", self.text(".now"))

    def test_see_this_month_chooses_it(self):
        self.page.click("[data-act=see-month]")
        self.until("rangeMonths().length === 1")
        self.assertEqual(self.page.input_value("#range"), self.js("S.range"))
        self.assertIsNone(self.page.query_selector(".now"))


class Largest:
    ON_SCREEN = "[...document.querySelectorAll('#view tr[data-tx]')]"

    def test_regular_bills_are_hidden_until_asked_for(self):
        self.tab("Largest")
        self.assertEqual(self.js(f"{self.ON_SCREEN}.filter(r => isBill(TX[r.dataset.tx])).length"), 0)
        self.assertIn("Best Buy", self.text("#view"))
        self.page.click("#largeAll")
        self.until(f"{self.ON_SCREEN}.some(r => isBill(TX[r.dataset.tx]))")

    def test_rent_is_a_bill_and_a_one_off_isnt(self):
        self.assertTrue(self.js("isBill(TX.find(t => t.merchant === 'Lakeside Apts Rent'))"))
        self.assertFalse(self.js("isBill(TX.find(t => t.merchant === 'Best Buy'))"))


class RedMeansAProblem:
    def test_ordinary_spending_uses_the_text_color(self):
        self.tab("Transactions")
        color = self.js("getComputedStyle([...document.querySelectorAll('#tx tr[data-tx]')].find(r => TX[r.dataset.tx].amt < 0).querySelector('td.num')).color")
        self.assertEqual(color, self.js("getComputedStyle(document.body).color"))

    def test_chart_colors_all_exist(self):
        self.tab("Savings")
        for fill in self.js("[...document.querySelectorAll('#c1 rect[fill]:not(.hit)')].map(r => r.getAttribute('fill'))"):
            self.assertNotIn("--neg", fill)
        self.tab("Overview")
        self.assertNotIn(self.js("getComputedStyle(document.querySelector('#c1 line')).stroke"), ("none", ""))


class OneTransaction:
    def open_row(self):
        self.tab("Transactions")
        self.page.click("#tx tr[data-tx]")
        self.dialog_open()

    def test_everything_that_matches_is_the_default(self):
        self.open_row()
        self.assertTrue(self.page.is_checked("[name=rScope][value=all]"))
        self.assertTrue(self.page.is_visible("#rMatch"))

    def test_just_this_one_hides_the_matching_text(self):
        self.open_row()
        self.page.check("[name=rScope][value=one]")
        self.assertFalse(self.page.is_visible("#rMatch"))
        self.assertIn("only this transaction", self.text(".modal-head"))

    def test_what_the_page_sends_finds_the_transaction(self):
        self.open_row()
        self.page.check("[name=rScope][value=one]")
        self.page.select_option("#rCat", index=2)
        self.page.fill("#rName", "One Off")
        self.mark_page()
        self.page.click("[data-modal=rule-save]")
        self.wait_for_reload()
        self.toast("Saved. Nothing else changed.")
        sent = self.calls("save_edit")
        self.assertEqual(len(sent), 1)
        with tempfile.TemporaryDirectory() as folder:
            real = build(Path(folder) / "home")  # the real service, given what the page sent
            real.save_edit(*sent[0][1])
            changed = [r for r in real._analysis()[0] if r["edited"]]
            self.assertEqual([r["merchant"] for r in changed], ["One Off"])

    def test_identical_rows_are_told_apart(self):
        with tempfile.TemporaryDirectory() as folder:
            rows = [{"date": date(2026, 1, 2), "account": "chk-0001", "description": "COFFEE", "amount": _money(-500), "cents": -500,
                     "balance": None, "bank_category": "", "source": "x", "sync_id": ""} for _ in range(3)]
            budget = build(Path(folder) / "home", rows)
            self.page = self.open_page(budget.html_path)
            self.assertEqual(self.js("TX.map(t => txId(t).n)"), [0, 1, 2])

    def test_an_edited_row_is_marked_and_offers_undo(self):
        with tempfile.TemporaryDirectory() as folder:
            budget = build(Path(folder) / "home")
            first = budget.ledger.rows[-1]  # in the period the page opens on
            budget.save_edit({"date": first["date"].isoformat(), "account": first["account"], "cents": first["cents"],
                              "description": first["description"], "n": 0}, "Gifts", "One Off")
            self.page = self.open_page(budget.html_path)
            self.tab("Transactions")
            self.page.fill("#q", "one off")
            self.until("document.getElementById('tx').innerText.includes('edited')")
            self.page.click("#tx tr[data-tx]")
            self.dialog_open()
            self.assertTrue(self.page.is_checked("[name=rScope][value=one]"))
            self.assertEqual(self.page.input_value("#rName"), "One Off")
            self.assertTrue(self.page.is_visible("[data-modal=edit-clear]"))
            self.press("Escape")
            self.dialog_open(False)


class SaveAndNext:
    def start(self):
        self.tab("Rules")
        self.page.click("[data-act=categorize]")
        self.dialog_open()

    def names(self):
        return self.js("uncategorized().map(m => m.merchant)")

    def test_it_shows_its_place_and_lands_on_the_category(self):
        self.start()
        self.assertIn(f"1 of {len(UNSORTED)}", self.text(".modal-head"))
        self.assertEqual(self.text("[data-modal=rule-next]"), "Save and next")
        self.assertEqual(self.js("document.activeElement.id"), "rCat")

    def test_enter_saves_and_moves_on_without_a_reload(self):
        names = self.names()
        self.start()
        self.page.select_option("#rCat", index=2)
        self.page.click("#rName")
        self.mark_page()
        self.press("Enter")
        self.until("name => document.getElementById('rName').value === name", names[1])
        self.assertEqual(self.js("window.marker"), 1)
        self.assertIn("matches 3 transactions", self.text(".modal-head"))
        self.assertEqual(self.page.input_value("#rCat"), "")

    def test_it_passes_over_what_a_saved_rule_covered(self):
        names = self.names()
        self.start()
        self.js(f"window.covered = {json.dumps([names[1]])}")
        self.page.select_option("#rCat", index=2)
        self.page.click("[data-modal=rule-next]")
        self.until("name => document.getElementById('rName').value === name", names[2])

    def test_skip_saves_nothing(self):
        names = self.names()
        self.start()
        self.page.click("[data-modal=rule-skip]")
        self.until("name => document.getElementById('rName').value === name", names[1])
        self.assertEqual(self.calls("save_rule"), [])

    def test_stopping_early_shows_what_was_saved(self):
        names = self.names()
        self.start()
        self.page.select_option("#rCat", index=2)
        self.page.click("[data-modal=rule-next]")
        self.until("name => document.getElementById('rName').value === name", names[1])
        self.mark_page()
        self.press("Escape")
        self.wait_for_reload()
        self.toast("Saved 1 rule.")

    def test_stopping_with_nothing_saved_just_closes(self):
        self.start()
        self.mark_page()
        self.press("Escape")
        self.dialog_open(False)
        self.assertEqual(self.js("window.marker"), 1)


class Keyboard:
    def test_sorting_keeps_focus_and_says_which_way(self):
        self.tab("Transactions")
        self.page.focus("[data-sort=amt]")
        self.press("Enter")
        self.until("S.txsort === 'amt'")
        self.assertEqual(self.js("document.activeElement.dataset.sort"), "amt")
        self.assertEqual(self.page.get_attribute("th[aria-sort]", "aria-sort"), "ascending")

    def test_arrows_read_a_chart(self):
        self.page.focus("#c1 svg")
        self.press("ArrowLeft")
        self.until("document.getElementById('say').textContent.includes('Income')")
        self.assertTrue(self.page.is_visible("#tip"))
        self.press("ArrowLeft")
        self.assertEqual(self.js("document.querySelectorAll('#c1 .hit.on').length"), 1)
        self.press("Tab")
        self.assertFalse(self.page.is_visible("#tip"))

    def test_charts_describe_themselves(self):
        self.assertGreater(len(self.page.get_attribute("#c1 svg", "aria-label")), 60)

    def test_recurring_rows_work(self):
        self.tab("Recurring")
        self.page.focus("#view tr.link")
        self.press("Enter")
        self.until("S.tab === 'Transactions'")

    def test_skip_to_content_comes_first(self):
        # Not by pressing Tab: by default, Tab on a Mac only stops at fields.
        self.assertEqual(self.js("document.querySelector('button, a[href], input, select, summary').id"), "skip")
        self.page.focus("#skip")
        self.press("Enter")
        self.assertEqual(self.js("document.activeElement.id"), "view")


class Words:
    def test_a_warning_shows_once_on_accounts(self):
        self.tab("Accounts")
        self.assertEqual(self.text("#view").count("Transfers out with no matching account"), 1)

    def test_help_covers_bank_sync(self):
        self.tab("Help")
        self.assertIn("Connect or download.", self.text("#view"))

    def test_savings_doesnt_assume_a_file(self):
        self.tab("Savings")
        self.assertNotIn("as of latest export", self.text("#view"))

    def test_card_payments_have_a_plain_name(self):
        names = self.js("[...new Set(TX.filter(t => t.kind === 'transfer' && ACCT[t.acct].type === 'credit').map(t => t.merchant))]")
        self.assertEqual(names, ["Card payment"])


class ManualSync:
    def test_opening_the_app_does_not_sync(self):
        with tempfile.TemporaryDirectory() as folder:
            budget = build(Path(folder) / "home")
            budget.sync.state = {"connected": True, "links": {"bank/1": {"account": "chk-0001", "since": None}}}
            budget.refresh()
            self.page = self.open_page(budget.html_path)
            self.assertEqual(self.js("D.sync.linked.length"), 1)
            self.until("window.calls('check_update').length > 0")  # the app's start-up calls have gone
            self.assertEqual(self.calls("sync_bank"), [])


class HostileText:
    """Bank text is whatever the bank sent, so it must only ever show as text."""

    def test_descriptions_cant_run_or_add_anything(self):
        for text in ("</script><img src=x onerror=window.pwned=1>", "<img src=x onerror=window.pwned=1>",
                     '" onmouseover="window.pwned=1', "' onclick='window.pwned=1"):
            with self.subTest(text), tempfile.TemporaryDirectory() as folder:
                rows = [{"date": date(2026, 1, 2), "account": "chk-0001", "description": text, "amount": _money(-500), "cents": -500,
                         "balance": None, "bank_category": "", "source": "x", "sync_id": ""}]
                self.page = self.open_page(build(Path(folder) / "home", rows).html_path)
                for name in self.js("TABS"):
                    self.tab(name)
                    self.assertFalse(self.js("window.pwned === 1 || document.querySelectorAll('#view img').length > 0"), name)


SUITES = (EveryTab, Dialogs, Rows, ThisMonth, Largest, RedMeansAProblem, OneTransaction, SaveAndNext, Keyboard, Words, ManualSync, HostileText)


class Chromium(*SUITES, PageCase):
    engine = "chromium"


class WebKit(*SUITES, PageCase):
    engine = "webkit"


del PageCase  # imported only to build on; running it alone would have no engine

if __name__ == "__main__":
    unittest.main()
