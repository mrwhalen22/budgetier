"""Bank sync, against a fake SimpleFIN server speaking real HTTPS on this machine."""
import base64
import datetime as dt
import ipaddress
import json
import ssl
import threading
import unittest
from datetime import UTC, date, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock
from urllib.parse import parse_qs, urlsplit

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec

from budgetier import analyze, app, credentials, simplefin, sync
from budgetier.ledger import Ledger
from budgetier.parse import RawRow
from budgetier.service import Budget, BudgetError
from budgetier.simplefin import SimpleFinError
from tests.support import Tmp

SECRET = "secret-user:secret-pass"


def certificate(folder):
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(x509.NameOID.COMMON_NAME, "localhost")])
    now = dt.datetime.now(UTC)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now - timedelta(days=1))
            .not_valid_after(now + timedelta(days=1))
            .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]), False)
            .add_extension(x509.BasicConstraints(ca=True, path_length=None), True).sign(key, hashes.SHA256()))
    path = folder / "server.pem"
    path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                       serialization.NoEncryption()) + cert.public_bytes(serialization.Encoding.PEM))
    return path


class Bank(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def reply(self, code, body=b"", **headers):
        self.send_response(code)
        for name, value in headers.items():
            self.send_header(name, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def firewall(self):
        """Cloudflare turns away Python's default client before the bank sees anything."""
        if self.server.bridge.block_all or self.headers.get("User-Agent", "").startswith("Python-urllib"):
            self.reply(403, b"error code: 1010")
            return True
        return False

    def do_POST(self):
        bridge = self.server.bridge
        if self.firewall():
            return None
        bridge.claims.append(self.path)
        if bridge.claimed:
            return self.reply(403, b"Forbidden (was it already claimed?)")
        bridge.claimed = True
        self.reply(200, bridge.access().encode())

    def do_GET(self):
        bridge = self.server.bridge
        if self.firewall():
            return None
        bridge.requests.append({"path": self.path, "auth": self.headers.get("Authorization")})
        if bridge.status:
            return self.reply(bridge.status)
        if bridge.redirect:
            return self.reply(302, Location=bridge.redirect)
        expected = "Basic " + base64.b64encode(SECRET.encode()).decode()
        if self.headers.get("Authorization") != expected:
            return self.reply(403)
        self.reply(200, json.dumps(bridge.answer(parse_qs(urlsplit(self.path).query))).encode())


class Bridge:
    """Holds what the fake bank serves. Honors the date range, like the real one."""

    def __init__(self, port):
        self.port, self.claimed, self.claims, self.requests = port, False, [], []
        self.status, self.redirect, self.problems, self.block_all = 0, None, [], False
        self.feed = {}  # account id -> {name, balance, currency, transactions}

    def access(self):
        return f"https://{SECRET}@127.0.0.1:{self.port}/simplefin"

    def token(self):
        return base64.b64encode(f"https://127.0.0.1:{self.port}/simplefin/claim/abc".encode()).decode()

    def answer(self, query):
        start, end = int(query["start-date"][0]), int(query["end-date"][0])
        now = int(dt.datetime.now(UTC).timestamp())
        return {"errlist": self.problems, "connections": [{"conn_id": "c1", "name": "Testbank"}],
                "accounts": [{"id": key, "conn_id": "c1", "name": a["name"], "currency": a.get("currency", "USD"),
                              "balance": a["balance"], "balance-date": now,
                              "transactions": [t for t in a["transactions"] if t.get("pending") or start <= t["posted"] < end]}
                             for key, a in self.feed.items()]}


def tx(id_, day, amount, description="COFFEE SHOP", **extra):
    stamp = int(dt.datetime(day.year, day.month, day.day, 12, tzinfo=UTC).timestamp())
    return {"id": id_, "posted": stamp, "amount": amount, "description": description, **extra}


class FakeKeyring:
    def __init__(self):
        self.saved = {}

    def get_keyring(self):
        return self

    def set_password(self, service, name, value):
        self.saved[service, name] = value

    def get_password(self, service, name):
        return self.saved.get((service, name))

    def delete_password(self, service, name):
        del self.saved[service, name]


class Server(Tmp):
    @classmethod
    def setUpClass(cls):
        import tempfile
        from pathlib import Path
        cls.folder = tempfile.TemporaryDirectory()
        cls.pem = certificate(Path(cls.folder.name))
        cls.http = ThreadingHTTPServer(("127.0.0.1", 0), Bank)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(cls.pem)
        cls.http.socket = context.wrap_socket(cls.http.socket, server_side=True)
        threading.Thread(target=cls.http.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.http.shutdown()
        cls.http.server_close()
        cls.folder.cleanup()

    def setUp(self):
        super().setUp()
        self.bridge = self.http.bridge = Bridge(self.http.server_address[1])
        patcher = mock.patch.object(simplefin, "tls_context", lambda: ssl.create_default_context(cafile=str(self.pem)))
        patcher.start()
        self.addCleanup(patcher.stop)


class Protocol(Server):
    def test_a_setup_token_decodes_to_its_claim_url(self):
        self.assertTrue(simplefin.claim_url(f"  {self.bridge.token()}\n").startswith("https://127.0.0.1"))

    def test_rubbish_is_not_a_token(self):
        for text in ("", "not base64!", base64.b64encode(b"http://plain.example/claim").decode(),
                     base64.b64encode(b"not a url").decode()):
            with self.assertRaises(SimpleFinError):
                simplefin.claim_url(text)

    def test_claiming_returns_the_access_url(self):
        self.assertEqual(simplefin.claim(self.bridge.token()), self.bridge.access())

    def test_a_used_token_warns_it_may_be_compromised(self):
        self.bridge.claimed = True
        with self.assertRaisesRegex(SimpleFinError, "someone else may have"):
            simplefin.claim(self.bridge.token())

    def test_every_request_gets_past_the_firewall(self):
        simplefin.claim(self.bridge.token())
        simplefin.fetch(self.bridge.access(), date(2026, 1, 1), date(2026, 1, 2))
        self.assertEqual((len(self.bridge.claims), len(self.bridge.requests)), (1, 1))

    def test_a_firewall_block_is_not_called_a_used_token(self):
        self.bridge.block_all = True
        with self.assertRaises(SimpleFinError) as caught:
            simplefin.claim(self.bridge.token())
        self.assertIn("nothing was used", str(caught.exception))
        self.assertNotIn("someone else", str(caught.exception))
        self.assertEqual(self.bridge.claims, [])

    def test_a_firewall_block_is_not_called_a_disabled_connection(self):
        self.bridge.block_all = True
        with self.assertRaisesRegex(SimpleFinError, "firewall"):
            simplefin.fetch(self.bridge.access(), date(2026, 1, 1), date(2026, 1, 2))

    def test_credentials_go_in_a_header_and_never_the_url(self):
        simplefin.fetch(self.bridge.access(), date(2026, 1, 1), date(2026, 1, 31))
        request = self.bridge.requests[0]
        self.assertNotIn("secret", request["path"])
        self.assertTrue(request["auth"].startswith("Basic "))
        self.assertIn("version=2", request["path"])

    def test_plain_http_is_refused_before_sending_anything(self):
        with self.assertRaises(SimpleFinError):
            simplefin.fetch(f"http://{SECRET}@127.0.0.1:{self.bridge.port}/simplefin", date(2026, 1, 1), date(2026, 1, 2))
        self.assertEqual(self.bridge.requests, [])

    def test_an_untrusted_certificate_is_refused(self):
        with mock.patch.object(simplefin, "tls_context", lambda: ssl.create_default_context(cafile=None, capath=None)):
            with self.assertRaisesRegex(SimpleFinError, "couldn't be reached"):
                simplefin.fetch(self.bridge.access(), date(2026, 1, 1), date(2026, 1, 2))

    def test_redirects_are_not_followed_with_the_password(self):
        self.bridge.redirect = f"https://127.0.0.1:{self.bridge.port}/elsewhere"
        with self.assertRaises(SimpleFinError):
            simplefin.fetch(self.bridge.access(), date(2026, 1, 1), date(2026, 1, 2))
        self.assertEqual(len(self.bridge.requests), 1)

    def test_errors_are_worded_and_never_hold_the_secret(self):
        for status, words in ((402, "payment"), (403, "disabled"), (500, "error 500")):
            self.bridge.status = status
            with self.assertRaises(SimpleFinError) as caught:
                simplefin.fetch(self.bridge.access(), date(2026, 1, 1), date(2026, 1, 2))
            self.assertIn(words, str(caught.exception))
            self.assertNotIn("secret", str(caught.exception))

    def test_nobody_home_is_reported(self):
        with self.assertRaisesRegex(SimpleFinError, "couldn't be reached"):
            simplefin.fetch(f"https://{SECRET}@127.0.0.1:1/simplefin", date(2026, 1, 1), date(2026, 1, 2))

    def test_the_packaged_certificates_load(self):
        mock.patch.stopall()
        self.assertGreater(simplefin.certificate_count(), 50)


class Reading(unittest.TestCase):
    def feed(self, **account):
        base = {"id": "a", "conn_id": "c", "name": "Card 1234", "currency": "USD", "balance": "-12.50", "balance-date": 1760000000}
        return simplefin.parse_feed({"errlist": [], "connections": [{"conn_id": "c", "name": "Bank"}],
                                     "accounts": [{**base, **account}]})

    def test_amounts_are_cents_and_money_out_is_negative(self):
        row = self.feed(transactions=[tx("1", date(2026, 3, 2), "-33.29")]).accounts[0].rows[0]
        self.assertEqual((row.cents, row.date, row.sync_id), (-3329, date(2026, 3, 2), "1"))

    def test_the_account_balance_keeps_its_sign(self):
        self.assertEqual(self.feed().accounts[0].balance, -1250)

    def test_pending_rows_wait_until_they_post(self):
        rows = [tx("1", date(2026, 3, 2), "-1.00", pending=True), {"id": "2", "posted": 0, "amount": "-1.00", "description": "x"}]
        self.assertEqual(self.feed(transactions=rows).accounts[0].rows, [])

    def test_unreadable_rows_are_reported_not_fatal(self):
        feed = self.feed(transactions=[tx("1", date(2026, 3, 2), "abc"), tx("2", date(2026, 3, 2), "-1.00")])
        self.assertEqual(len(feed.accounts[0].rows), 1)
        self.assertIn("skipped 1", feed.problems[0])

    def test_an_account_without_a_balance_is_reported(self):
        self.assertIn("skipped", self.feed(balance="n/a").problems[0])

    def test_server_problems_are_collected_and_cleaned(self):
        feed = simplefin.parse_feed({"errlist": [{"code": "con.auth", "msg": "Sign in\x07 again"}], "accounts": []})
        self.assertEqual(feed.problems, ["Sign in again"])

    def test_the_older_error_list_still_works(self):
        self.assertEqual(simplefin.parse_feed({"errors": ["Slow down"], "accounts": []}).problems, ["Slow down"])

    def test_the_older_organization_field_still_works(self):
        data = {"accounts": [{"id": "a", "org": {"domain": "b.example", "name": "Old Bank"}, "name": "Card",
                              "balance": "1.00", "balance-date": 1760000000}]}
        account = simplefin.parse_feed(data).accounts[0]
        self.assertEqual((account.key, account.connection), ("b.example/a", "Old Bank"))


def raw(day, cents, text="FILE WORDING", sync_id=""):
    return RawRow(date=day, description=text, cents=cents, sync_id=sync_id)


class Matching(Tmp):
    def setUp(self):
        super().setUp()
        self.ledger = Ledger(self.dir)

    def test_syncing_twice_adds_nothing(self):
        rows = [raw(date(2026, 3, 1), -500, "A", "1")]
        self.assertEqual(self.ledger.merge_synced("x", rows, None), 1)
        self.assertEqual(self.ledger.merge_synced("x", rows, None), 0)

    def test_nothing_before_the_cut_over_is_added(self):
        self.assertEqual(self.ledger.merge_synced("x", [raw(date(2026, 3, 1), -500, "A", "1")], date(2026, 3, 2)), 0)

    def test_a_feed_row_matches_a_file_row_nearby_despite_the_wording(self):
        self.ledger.merge("x", [raw(date(2026, 3, 1), -500)], "a.csv")
        self.assertEqual(self.ledger.merge_synced("x", [raw(date(2026, 3, 3), -500, "CARD 1234 WORDING", "1")], date(2026, 3, 1)), 0)

    def test_the_same_amount_later_is_a_new_purchase(self):
        self.ledger.merge("x", [raw(date(2026, 3, 1), -500)], "a.csv")
        self.assertEqual(self.ledger.merge_synced("x", [raw(date(2026, 3, 5), -500, "B", "1")], date(2026, 3, 1)), 1)

    def test_real_repeats_survive_because_each_row_matches_once(self):
        self.ledger.merge("x", [raw(date(2026, 3, 1), -500)], "a.csv")
        rows = [raw(date(2026, 3, 1), -500, "B", "1"), raw(date(2026, 3, 2), -500, "B", "2")]
        self.assertEqual(self.ledger.merge_synced("x", rows, date(2026, 3, 1)), 1)

    def test_a_file_imported_after_sync_does_not_double_count(self):
        self.ledger.merge_synced("x", [raw(date(2026, 3, 3), -500, "FEED WORDING", "1")], None)
        result = self.ledger.merge("x", [raw(date(2026, 3, 2), -500), raw(date(2026, 3, 20), -900)], "a.csv")
        self.assertEqual((result["added"], result["duplicates"]), (1, 1))

    def test_ledgers_saved_before_sync_still_load(self):
        self.ledger.path.write_text("date,account,description,amount,balance,bank_category,source\n"
                                    "2026-03-01,x,COFFEE,-5.00,,,a.csv\n", encoding="utf-8")
        ledger = Ledger(self.dir)
        self.assertEqual(ledger.rows[0]["sync_id"], "")
        ledger.save()
        self.assertEqual(len(Ledger(self.dir).rows), 1)


class Syncing(Server):
    def setUp(self):
        super().setUp()
        self.keyring = FakeKeyring()
        patcher = mock.patch.object(credentials, "keyring", self.keyring)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.budget = Budget(self.dir / "home")
        self.addCleanup(self.budget.cancel)
        self.today = date.today()
        self.bridge.feed = {"chk": {"name": "Everyday Checking ...1234", "balance": "1000.00", "transactions": [
                                tx("t1", self.today - timedelta(days=40), "-20.00"),
                                tx("t2", self.today - timedelta(days=10), "-30.00", "GROCERY")]},
                            "card": {"name": "Rewards Card 5678", "balance": "-250.00", "transactions": [
                                tx("t1", self.today - timedelta(days=9), "-250.00", "SHOES")]}}

    def connect(self):
        return self.budget.sync.connect(self.bridge.token())

    def link_all(self):
        plan = self.connect()
        return self.budget.sync.link([{**a, "account": a["account"], "number": a["number"], "name": a["name"]}
                                       for a in plan["accounts"]])

    def later(self, hours=7):
        stamp = dt.datetime.now() - timedelta(hours=hours)
        self.budget.sync.state["last_sync"] = stamp.isoformat(timespec="seconds")

    def csv(self, name, rows):
        path = self.dir / name
        path.write_text("Date,Description,Amount\n" + "\n".join(rows) + "\n", encoding="utf-8")
        return path

    def import_file(self, path, number="1234"):
        plan = self.budget.inspect([str(path)])
        self.budget.commit([{"id": i["id"], "bank": "Testbank", "number": number, "type": "checking", "balance": "",
                             "spent": True} for i in plan["items"]])

    def test_connecting_lists_accounts_and_guesses_details(self):
        accounts = {a["key"]: a for a in self.connect()["accounts"]}
        self.assertEqual((accounts["c1/card"]["number"], accounts["c1/card"]["bank"]), ("5678", "Testbank"))
        self.assertEqual(accounts["c1/chk"]["type"], "checking")
        self.assertEqual(accounts["c1/card"]["balance"], -250)

    def test_the_access_url_is_only_in_secure_storage(self):
        self.link_all()
        self.assertIn(self.bridge.access(), self.keyring.saved.values())
        for path in self.budget.home.rglob("*"):
            if path.is_file():
                self.assertNotIn(b"secret", path.read_bytes(), path.name)

    def test_a_broken_secure_store_does_not_spend_the_token(self):
        with mock.patch.object(self.keyring, "set_password", side_effect=RuntimeError("locked")):
            with self.assertRaisesRegex(BudgetError, "secure storage"):
                self.connect()
        self.assertEqual(self.bridge.claims, [])

    def test_a_mistyped_token_does_not_spend_anything(self):
        with self.assertRaises(SimpleFinError):
            self.budget.sync.connect("oops!")
        self.assertEqual(self.bridge.claims, [])

    def test_each_data_folder_has_its_own_connection(self):
        self.assertNotEqual(credentials._name(self.dir / "a"), credentials._name(self.dir / "b"))

    def test_reviewing_changes_no_accounts(self):
        self.connect()
        self.assertEqual((self.budget.ledger.accounts, self.budget.ledger.rows), ({}, []))

    def test_linking_makes_accounts_and_brings_in_history(self):
        self.assertEqual(self.link_all()["added"], 3)
        again = Budget(self.budget.home)
        self.assertEqual(sorted(again.ledger.accounts), ["testbank-1234", "testbank-5678"])
        self.assertEqual({r["source"] for r in again.ledger.rows}, {"SimpleFIN"})
        self.assertFalse(any(i.get("invert_sign") for i in again.ledger.accounts.values()))

    def test_the_same_transaction_id_on_two_accounts_is_two_transactions(self):
        self.link_all()
        self.assertEqual(sum(r["sync_id"] == "t1" for r in self.budget.ledger.rows), 2)

    def test_linking_needs_a_bank_for_a_new_account(self):
        plan = self.connect()
        with self.assertRaisesRegex(BudgetError, "bank and type"):
            self.budget.sync.link([{**plan["accounts"][0], "bank": ""}])
        self.assertEqual(self.budget.ledger.accounts, {})

    def test_partial_digits_are_questioned(self):
        plan = self.connect()
        with self.assertRaisesRegex(BudgetError, "all 4 digits"):
            self.budget.sync.link([{**plan["accounts"][0], "number": "12"}])

    def test_a_feed_with_no_digits_still_makes_a_stable_account(self):
        self.bridge.feed = {"chk": {"name": "Everyday Checking", "balance": "10.00", "transactions": [
            tx("t1", self.today, "-1.00")]}}
        plan = self.connect()
        self.assertEqual(plan["accounts"][0]["number"], "")
        self.budget.sync.link(plan["accounts"])
        (account, info), = self.budget.ledger.accounts.items()
        self.assertEqual(info["name"], "Testbank Everyday Checking")
        self.assertRegex(info["number"], r"^\d{4}$")
        self.assertEqual(self.budget.sync.links["c1/chk"]["account"], account)

    def test_trying_the_token_again_does_not_spend_it_again(self):
        self.connect()
        self.budget.sync.connect(self.bridge.token())
        self.assertEqual(len(self.bridge.claims), 1)

    def test_a_failure_right_after_claiming_keeps_the_connection(self):
        self.bridge.status = 500
        plan = self.connect()
        self.assertTrue(self.budget.sync.status()["connected"])
        self.assertEqual(plan["accounts"], [])
        self.assertIn("Connected, but", plan["problems"][0])
        self.bridge.status = 0
        self.assertEqual(len(self.budget.sync.connect(self.bridge.token())["accounts"]), 2)
        self.assertEqual(len(self.bridge.claims), 1)

    def test_opening_the_review_again_costs_no_request(self):
        self.connect()
        self.bridge.requests.clear()
        self.budget.sync.review()
        self.assertEqual(self.bridge.requests, [])

    def test_an_old_review_is_refreshed(self):
        self.connect()
        self.budget.sync._feed_at -= timedelta(minutes=10)
        self.bridge.requests.clear()
        self.budget.sync.review()
        self.assertEqual(len(self.bridge.requests), 1)

    def test_the_page_knows_about_a_review_without_saving_choices(self):
        self.connect()
        self.assertEqual(self.budget.sync.status()["unlinked"], 2)
        self.assertIn('"unlinked":2', self.budget.html_path.read_text(encoding="utf-8"))

    def test_review_lists_accounts_that_have_no_rows_yet(self):
        self.bridge.feed["quiet"] = {"name": "Quiet Savings 3333", "balance": "500.00", "transactions": []}
        self.link_all()
        self.budget.sync._feed = None
        names = [a["name"] for a in self.budget.sync.review()["existing"]]
        self.assertIn("Testbank Savings 3333", names)

    def test_a_quiet_account_still_shows_its_balance(self):
        self.bridge.feed["quiet"] = {"name": "Quiet Savings 3333", "balance": "500.00", "transactions": []}
        self.link_all()
        html = self.budget.html_path.read_text(encoding="utf-8")
        self.assertIn("Testbank Savings 3333", html)
        self.budget.export_workbook(self.dir / "out.xlsx")

    def test_chosen_later_accounts_are_counted_until_chosen(self):
        plan = self.connect()
        self.assertEqual(self.budget.sync.status()["unlinked"], 2)
        self.budget.sync.link(plan["accounts"])
        self.assertEqual(self.budget.sync.status()["unlinked"], 0)

    def test_two_bank_accounts_cant_share_one(self):
        self.import_file(self.csv("Testbank_1234.csv", ["01/02/2026,X,-5.00"]))
        plan = self.connect()
        with self.assertRaisesRegex(BudgetError, "can't share"):
            self.budget.sync.link([{**a, "account": "testbank-1234"} for a in plan["accounts"]])
        self.assertEqual(self.budget.sync.links, {})

    def test_a_failed_save_keeps_nothing(self):
        plan = self.connect()
        with mock.patch.object(self.budget.ledger, "save", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                self.budget.sync.link(plan["accounts"])
        self.assertEqual((self.budget.ledger.rows, self.budget.ledger.accounts, self.budget.sync.links), ([], {}, {}))

    def test_a_matching_last_four_is_suggested(self):
        self.import_file(self.csv("Testbank_1234.csv", ["01/02/2026,X,-5.00"]))
        accounts = {a["key"]: a for a in self.connect()["accounts"]}
        self.assertEqual(accounts["c1/chk"]["account"], "testbank-1234")
        self.assertEqual(accounts["c1/card"]["account"], "")

    def test_files_stay_the_record_up_to_the_cut_over(self):
        last = self.today - timedelta(days=11)
        self.import_file(self.csv("Testbank_1234.csv", [f"{last:%m/%d/%Y},FILE WORDING,-20.00"]))
        plan = self.connect()
        self.budget.sync.link([a if a["key"] == "c1/chk" else {**a, "account": "skip"} for a in plan["accounts"]])
        descriptions = sorted(r["description"] for r in self.budget.ledger.rows)
        self.assertEqual(descriptions, ["FILE WORDING", "GROCERY"])  # the older feed row isn't added

    def test_skipped_accounts_stay_out_and_are_not_offered_as_new(self):
        plan = self.connect()
        self.budget.sync.link([a if a["key"] == "c1/chk" else {**a, "account": "skip"} for a in plan["accounts"]])
        self.later()
        self.assertEqual(self.budget.sync.sync()["unlinked"], 0)
        self.assertEqual(list(self.budget.ledger.accounts), ["testbank-1234"])

    def test_a_new_bank_account_is_mentioned_after_a_sync(self):
        self.link_all()
        self.bridge.feed["new"] = {"name": "Savings 9999", "balance": "5.00", "transactions": []}
        self.later()
        self.assertEqual(self.budget.sync.sync()["unlinked"], 1)

    def test_other_currencies_are_skipped(self):
        self.bridge.feed["eur"] = {"name": "Euro 1111", "balance": "5.00", "currency": "EUR", "transactions": []}
        plan = self.connect()
        self.budget.sync.link(plan["accounts"])
        self.assertNotIn("c1/eur", self.budget.sync.links)

    def test_syncing_adds_only_what_is_new(self):
        self.link_all()
        self.bridge.feed["chk"]["transactions"].append(tx("t3", self.today, "-7.00", "LUNCH"))
        self.later()
        self.assertEqual(self.budget.sync.sync()["added"], 1)
        self.later()
        self.assertEqual(self.budget.sync.sync()["added"], 0)

    def test_a_sync_looks_back_over_recent_days(self):
        self.link_all()
        self.later(24)
        self.bridge.requests.clear()
        self.budget.sync.sync()
        start = parse_qs(urlsplit(self.bridge.requests[0]["path"]).query)["start-date"][0]
        days = (dt.date.today() - dt.datetime.fromtimestamp(int(start), UTC).date()).days  # sync counts in local days
        self.assertEqual(days, sync.OVERLAP_DAYS + 1)

    def test_a_review_left_without_linking_does_not_skip_days(self):
        self.link_all()
        self.later(24 * 20)
        self.bridge.feed["chk"]["transactions"].append(tx("t3", self.today - timedelta(days=15), "-11.00", "LUNCH"))
        self.budget.sync.review()  # then closed without linking anything
        self.assertEqual(self.budget.sync.sync()["added"], 1)

    def test_reviewing_is_not_syncing(self):
        self.connect()
        self.assertIsNone(self.budget.sync.status()["lastSync"])
        self.assertNotIn("skipped", self.budget.sync.sync(automatic=True))

    def test_a_long_absence_is_fetched_in_allowed_steps(self):
        self.link_all()
        self.later(24 * 200)
        self.bridge.requests.clear()
        self.budget.sync.sync()
        ranges = [parse_qs(urlsplit(r["path"]).query) for r in self.bridge.requests]
        self.assertGreaterEqual(len(ranges), 3)
        for query in ranges:
            self.assertLessEqual(int(query["end-date"][0]) - int(query["start-date"][0]), 90 * 86400)

    def test_opening_the_app_syncs_at_most_every_six_hours(self):
        self.link_all()
        self.bridge.requests.clear()
        self.assertTrue(self.budget.sync.sync(automatic=True)["skipped"])
        self.later()
        self.assertNotIn("skipped", self.budget.sync.sync(automatic=True))

    def test_sync_now_right_after_a_sync_costs_no_request(self):
        self.link_all()
        self.bridge.requests.clear()
        self.assertTrue(self.budget.sync.sync()["skipped"])
        self.assertEqual(self.bridge.requests, [])

    def test_not_connected_does_nothing(self):
        self.assertTrue(self.budget.sync.sync(automatic=True)["skipped"])
        self.assertEqual(self.bridge.requests, [])

    def test_the_daily_limit_is_respected(self):
        self.link_all()
        self.later()
        now = dt.datetime.now().isoformat(timespec="seconds")
        self.budget.sync.state["requests"] = [now] * sync.DAILY_LIMIT
        self.bridge.requests.clear()
        with self.assertRaisesRegex(BudgetError, "as often as"):
            self.budget.sync.sync()
        self.assertTrue(self.budget.sync.sync(automatic=True)["skipped"])
        self.assertEqual(self.bridge.requests, [])

    def test_old_requests_stop_counting(self):
        self.link_all()
        self.later()
        old = (dt.datetime.now() - timedelta(days=2)).isoformat(timespec="seconds")
        self.budget.sync.state["requests"] = [old] * 50
        self.assertEqual(self.budget.sync.sync()["added"], 0)

    def test_problems_from_the_bank_are_kept_for_the_screen(self):
        self.link_all()
        self.bridge.problems = [{"code": "con.auth", "msg": "Sign in to Testbank again"}]
        self.later()
        self.assertEqual(self.budget.sync.sync()["problems"], ["Sign in to Testbank again"])
        self.assertIn("Sign in to Testbank again", self.budget.html_path.read_text(encoding="utf-8"))

    def test_a_refused_sync_keeps_your_data(self):
        self.link_all()
        self.bridge.status = 403
        self.later()
        with self.assertRaisesRegex(SimpleFinError, "Disconnect"):
            self.budget.sync.sync()
        self.assertEqual(len(self.budget.ledger.rows), 3)

    def test_a_missing_credential_says_how_to_recover(self):
        self.link_all()
        self.keyring.saved.clear()
        self.later()
        with self.assertRaisesRegex(BudgetError, "connect"):
            self.budget.sync.sync()

    def test_the_banks_balance_beats_an_old_export(self):
        self.import_file(self.balance_file())
        plan = self.connect()
        self.budget.sync.link([a if a["key"] == "c1/chk" else {**a, "account": "skip"} for a in plan["accounts"]])
        rows = analyze.classify(self.budget.ledger.rows, self.budget.ledger.accounts, [])
        balance = analyze.account_balances(rows, self.budget.ledger.accounts)["testbank-1234"]
        self.assertEqual(balance["current"], 100000)

    def balance_file(self):
        path = self.dir / "Testbank_1234.csv"
        path.write_text("Date,Description,Amount,Balance\n01/02/2026,X,-5.00,77.00\n", encoding="utf-8")
        return path

    def test_a_card_balance_is_what_you_owe(self):
        self.link_all()
        self.assertEqual(self.budget.ledger.accounts["testbank-5678"]["balance_anchor"]["amount"], 250)
        rows = analyze.classify(self.budget.ledger.rows, self.budget.ledger.accounts, [])
        self.assertEqual(analyze.account_balances(rows, self.budget.ledger.accounts)["testbank-5678"]["current"], -25000)

    def test_removing_a_file_keeps_synced_rows(self):
        self.import_file(self.csv("Testbank_1234.csv", ["01/02/2026,X,-5.00"]))
        plan = self.connect()
        self.budget.sync.link([a if a["key"] == "c1/chk" else {**a, "account": "skip"} for a in plan["accounts"]])
        self.assertEqual(self.budget.remove_import(self.budget.ledger.imports[0]["stored"]), {"removed": 1})
        self.assertEqual(sorted(r["sync_id"] for r in self.budget.ledger.rows), ["t1", "t2"])
        self.assertIn("testbank-1234", self.budget.ledger.accounts)

    def test_a_removed_account_is_not_brought_back(self):
        self.link_all()
        self.budget.remove_account("testbank-1234")
        self.later()
        self.budget.sync.sync()
        self.assertNotIn("testbank-1234", self.budget.ledger.accounts)

    def test_disconnecting_keeps_transactions_and_forgets_the_connection(self):
        self.link_all()
        self.budget.sync.disconnect()
        self.assertEqual(self.keyring.saved, {})
        self.assertFalse(self.budget.sync.path.exists())
        self.assertEqual(len(Budget(self.budget.home).ledger.rows), 3)
        self.assertFalse(self.budget.sync.status()["connected"])
        self.assertNotIn("live", self.budget.ledger.accounts["testbank-1234"]["balance_anchor"])

    def test_the_connection_survives_a_restart(self):
        self.link_all()
        again = Budget(self.budget.home)
        self.assertTrue(again.sync.status()["connected"])
        self.assertEqual(len(again.sync.status()["linked"]), 2)

    def test_damaged_settings_keep_the_app_open_and_the_connection(self):
        self.link_all()
        self.budget.sync.path.write_text("{", encoding="utf-8")
        again = Budget(self.budget.home)
        again.refresh()
        self.assertTrue(again.sync.status()["connected"])
        self.assertIn("Bank sync settings couldn't be read", again.html_path.read_text(encoding="utf-8"))
        self.assertTrue((again.home / "sync.damaged.json").exists())

    def test_the_page_calls_reach_sync(self):
        api = app.Api(self.budget)
        reply = api.connect_bank(self.bridge.token())
        self.assertTrue(reply["ok"])
        self.assertEqual(len(api.review_bank()["accounts"]), 2)
        self.assertEqual(api.link_bank(reply["accounts"])["added"], 3)
        self.assertTrue(api.sync_bank(True)["skipped"])
        self.assertTrue(api.disconnect_bank()["ok"])

    def test_a_token_problem_reaches_the_page_in_words(self):
        self.bridge.claimed = True
        reply = app.Api(self.budget).connect_bank(self.bridge.token())
        self.assertFalse(reply["ok"])
        self.assertIn("someone else may have", reply["error"])


if __name__ == "__main__":
    unittest.main()
