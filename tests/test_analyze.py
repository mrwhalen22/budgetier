import re
import unittest
from datetime import date

from budgetier import analyze
from tests.support import ACCOUNTS, Tmp, row


class SingleEdits(unittest.TestCase):
    ROWS = [row("card", 1, "COFFEE  SHOP", -500), row("card", 1, "coffee shop", -500), row("card", 2, "COFFEE SHOP", -500)]

    def test_an_edit_beats_a_rule_for_that_row_alone(self):
        key = analyze.edit_key(date(2026, 1, 2), "card", -500, "COFFEE SHOP", 0)
        rules = [(re.compile("COFFEE"), "Dining", "Cafe")]
        out = analyze.classify(self.ROWS, ACCOUNTS, rules, {key: {"category": "Gifts", "merchant": "Birthday"}})
        self.assertEqual([(r["category"], r["merchant"], r["edited"]) for r in out],
                         [("Dining", "Cafe", False), ("Dining", "Cafe", False), ("Gifts", "Birthday", True)])

    def test_identical_rows_can_be_told_apart(self):
        keys = analyze.edit_keys(self.ROWS)
        self.assertEqual(len(set(keys)), 3)
        out = analyze.classify(self.ROWS, ACCOUNTS, [], {keys[1]: {"category": "Gifts"}})
        self.assertEqual([r["category"] == "Gifts" for r in out], [False, True, False])

    def test_an_edit_can_say_a_row_is_a_transfer(self):
        keys = analyze.edit_keys(self.ROWS)
        self.assertEqual(analyze.classify(self.ROWS, ACCOUNTS, [], {keys[0]: {"category": "Transfer"}})[0]["kind"], "transfer")

    def test_an_edited_row_isnt_claimed_as_the_other_half_of_a_transfer(self):
        rows = [row("chk", 1, "ONLINE TRANSFER", -500), row("sav", 1, "DEPOSIT", 500)]
        key = analyze.edit_keys(rows)[1]
        out = analyze.classify(rows, ACCOUNTS, [], {key: {"category": "Income"}})
        self.assertEqual((out[1]["kind"], out[1]["matched"]), ("income", False))


class Classify(unittest.TestCase):
    def test_a_bill_records_the_range_it_has_been(self):
        rows = [row("card", 3, "NETFLIX", -cents, month=m) for m, cents in ((1, -1), (2, -1), (3, -1))]
        rows = [{**r, "cents": c} for r, c in zip(rows, (-1500, -1500, -1700))]
        found = analyze.find_recurring(analyze.classify(rows, ACCOUNTS, []))[0]
        self.assertEqual((found["low"], found["high"]), (15.0, 17.0))

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

    def test_a_card_payment_has_a_plain_name_on_the_card(self):
        for text in ("AUTOMATIC PAYMENT - THANK YOU", "PAYMENT RECEIVED THANK YOU", "AUTOPAY 8841"):
            out = analyze.classify([row("card", 1, text, 50000)], ACCOUNTS, [])
            self.assertEqual((out[0]["merchant"], out[0]["kind"]), ("Card payment", "transfer"), text)

    def test_the_bank_side_of_a_card_payment_still_says_which_card(self):
        out = analyze.classify([row("chk", 1, "CHASE CREDIT CRD EPAY", -50000)], ACCOUNTS, [])
        self.assertEqual(out[0]["merchant"], "Chase")

    def test_your_rule_names_a_card_payment_over_the_plain_name(self):
        rules = [(re.compile("AUTOPAY"), "Transfer", "Sapphire")]
        self.assertEqual(analyze.classify([row("card", 1, "AUTOPAY 8841", 50000)], ACCOUNTS, rules)[0]["merchant"], "Sapphire")

    def test_a_purchase_refund_on_a_card_keeps_its_name(self):
        out = analyze.classify([row("card", 1, "KROGER #123", 500)], ACCOUNTS, [])
        self.assertEqual(out[0]["merchant"], "Kroger")

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
                           ("SP * SOME SHOP", "Some Shop"),
                           ("PURCHASE AUTHORIZED ON 10/03 TST*HIKO-A-MON ATLANTA GA P000000123 CARD 1234", "Hiko A Mon Atlanta"),
                           ("JANE DOE P2P JANE DOE", "Jane Doe"),
                           ("EARLY PAY: ACME CORP WIDGETS PAYROLL XXXXXXXXXXX4006 050826", "Acme Corp Widgets"),
                           ("DEBIT CARD PURCHASE AT ACME GAMES.COM 425, BELLEVUE, WA ON 053026 FROM CARD#: XXXX4005", "Acme Games")]:
            self.assertEqual(analyze.clean_merchant(text), want)


class MatchText(unittest.TestCase):
    """What a new rule starts with: never just a bank's boilerplate or a payment service's code."""

    def suggest(self, *descriptions):
        return analyze.match_text(analyze.clean_merchant(descriptions[0]), list(descriptions))

    def test_names_with_punctuation_keep_the_banks_spelling(self):
        self.assertEqual(self.suggest("SQ *JOE'S COFFEE"), "JOE'S COFFEE")
        self.assertEqual(self.suggest("TST*HIKO-A-MON ATLANTA GA P000000123"), "HIKO-A-MON ATLANTA GA")

    def test_the_merchant_name_is_used_when_the_bank_always_uses_it(self):
        self.assertEqual(self.suggest("SQ*CAFE & BAKERY"), "CAFE & BAKERY")
        self.assertEqual(self.suggest("PAYPAL *SPOTIFY 4029357733 CA"), "SPOTIFY")

    def test_wells_fargo_boilerplate_is_left_out(self):
        for first in ("PURCHASE AUTHORIZED ON 10/01", "RECURRING PAYMENT AUTHORIZED ON 10/01"):
            text = self.suggest(f"{first} SQ *JOE'S COFFEE SEATTLE WA S586274000000 CARD 1234")
            self.assertEqual(text, "JOE'S COFFEE SEATTLE WA")

    def test_it_matches_what_it_came_from(self):
        for text in ("SQ *JOE'S COFFEE", "TST* A(B) [C] $5", "PURCHASE", "SQ *AB", "#12"):
            self.assertIn(self.suggest(text), text.upper())

    def test_a_number_can_start_a_name(self):
        self.assertEqual(analyze.match_text("Renamed", ["SQ *1800 DINER #44"]), "1800 DINER")

    def test_a_name_the_rule_gave_is_not_searched_for(self):
        self.assertEqual(analyze.match_text("My Gym", ["ACH DEBIT PLANET FIT 123456"]), "PLANET FIT")

    def test_a_name_must_appear_in_every_description(self):
        self.assertEqual(analyze.match_text("Joe", ["SQ *JOE'S", "SQ *THE JOINT"]), "JOE'S")


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
