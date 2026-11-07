"""Run the real page in real browser engines, with a stand-in for the desktop app.

Chromium is close to the WebView2 window on Windows and WebKit to the window on a Mac, so
each test runs in both. The page is built by the real code from made-up data. Saving is
the stand-in's job here; tests/test_service.py covers what saving does.

These need Playwright and its browsers, and are skipped without them unless
BUDGETIER_BROWSERS=required, which CI sets so that they can't quietly stop running:

    python -m playwright install chromium webkit
"""
import json
import os
import shutil
import tempfile
import unittest
from datetime import date
from pathlib import Path

from budgetier import service
from budgetier.accounts import pin_balance
from budgetier.ledger import _money

try:
    from playwright.sync_api import Error as PlaywrightError
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright = None
    PlaywrightError = Exception

REQUIRED = os.environ.get("BUDGETIER_BROWSERS") == "required"
ACCOUNTS = {"chk-0001": ("Bank", "0001", "checking", "Bank Checking 0001"), "card-0002": ("Chase", "0002", "credit", "Chase Card 0002"),
            "sav-0003": ("Bank", "0003", "savings", "Bank Savings 0003")}
UNSORTED = ["QQQ WIDGETS", "VVV PARTS", "XYLO GOODS", "ZZYZX HARDWARE"]
FIRST, LAST = date(2025, 8, 1), date(2026, 10, 15)

# Answers what the page asks, and remembers each call across the page's reloads.
STAND_IN = """
const remember = call => { const all = JSON.parse(sessionStorage.getItem('calls') || '[]'); all.push(call); sessionStorage.setItem('calls', JSON.stringify(all)); };
window.calls = name => JSON.parse(sessionStorage.getItem('calls') || '[]').filter(c => c[0] === name);
window.pywebview = {platform: 'test', api: new Proxy({}, {get: (_, name) => async (...args) => {
  remember([name, args]);
  if (name === 'preview_rule') return {ok: true, count: 3, total: -5, share: .01, examples: ['AN EXAMPLE']};
  if (name === 'suggest_rule') return (window.covered || []).includes(args[0]) ? {ok: true, rule: {line: 'x', text: 'X', merchant: args[0], category: 'Dining', advanced: false}} : window.ruleReply || {ok: true, text: args[0].toUpperCase()};
  if (name === 'check_update') return {ok: true, available: false};
  if (name === 'save_rule') return {ok: true, count: 3};
  if (name === 'pick_files') return {ok: true, paths: ['a.csv']};
  if (name === 'inspect') return {ok: true, errors: [], items: [{id: 'i', file: 'a.csv', count: 1, first: '2026-01-01', last: '2026-01-02', known: false, new: 1, notes: [], bank: 'X', number: '1234', type: 'checking', hasBalance: true, askSign: false}]};
  if (name === 'commit') return {ok: true, results: [{account: 'X', added: 1, duplicates: 0}]};
  return {ok: true};
}})};
try { localStorage.setItem('budgetier-toured', '1'); } catch {}
"""


def _rows() -> list[dict]:
    def row(account, day, text, cents):
        return {"date": day, "account": account, "description": text, "amount": _money(cents), "cents": cents, "balance": None,
                "bank_category": "", "source": "made-up.csv", "sync_id": ""}

    rows, n = [], 0
    year, month = FIRST.year, FIRST.month
    while date(year, month, 1) <= LAST:
        n += 1
        on = lambda d: date(year, month, d)  # noqa: B023, E731 - used within this pass of the loop
        rows += [row("chk-0001", on(1), "ACH DEBIT LAKESIDE APTS RENT", -185000), row("chk-0001", on(5), "ACME INC PAYROLL", 312100),
                 row("card-0002", on(3), "NETFLIX.COM", -1599), row("card-0002", on(6), "KROGER #123", -8000 - n * 37),
                 row("card-0002", on(8), "CHIPOTLE 2291", -1450 - n), row("card-0002", on(12), "PAYMENT THANK YOU", 60000),
                 row("chk-0001", on(12), "CHASE CREDIT CRD EPAY", -60000), row("chk-0001", on(13), "ONLINE TRANSFER TO BROKER", -10000),
                 row("sav-0003", on(15), "INT PMT", 500)]
        if date(year, month, 20) <= LAST:
            rows.append(row("chk-0001", on(20), "COMCAST CABLE 800", -7999))
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    rows += [row("card-0002", date(2026, 6, 14), "BEST BUY 00123", -129999), row("card-0002", date(2026, 3, 21), "DELTA AIR 0062", -68430),
             *[row("card-0002", date(2026, 9, 2 + i), text, -2500 - i) for i, text in enumerate(UNSORTED)]]
    return rows


def build(home: Path, rows: list[dict] | None = None) -> service.Budget:
    budget = service.Budget(home)
    budget.ledger.accounts = {a: {"name": name, "bank": bank, "number": number, "type": kind, "invert_sign": False}
                              for a, (bank, number, kind, name) in ACCOUNTS.items()}
    pin_balance(budget.ledger.accounts["sav-0003"], 500000, LAST)
    budget.ledger.rows = _rows() if rows is None else rows
    budget.ledger.save()
    budget.save_rule(None, "KROGER", "Groceries", "Kroger")
    budget.save_budget("Dining", "amount", "300")
    budget.refresh()
    return budget


@unittest.skipUnless(sync_playwright or REQUIRED, "needs Playwright")
class PageCase(unittest.TestCase):
    """A subclass sets engine. Each test gets a fresh page of the shared report."""
    engine = ""
    extra_rows: tuple = ()  # added to the made-up data, for a subclass that needs more
    WIDTH, HEIGHT = 1300, 860

    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.mkdtemp(prefix="budgetier-page-")
        cls.addClassCleanup(shutil.rmtree, cls.folder, ignore_errors=True)
        cls.budget = build(Path(cls.folder) / "home", _rows() + list(cls.extra_rows) if cls.extra_rows else None)
        cls.playwright = sync_playwright().start()
        cls.addClassCleanup(cls.playwright.stop)
        try:
            cls.browser = getattr(cls.playwright, cls.engine).launch()
        except PlaywrightError as e:
            if REQUIRED:
                raise
            raise unittest.SkipTest(f"{cls.engine} isn't installed") from e
        cls.addClassCleanup(cls.browser.close)

    def setUp(self):
        self.errors = []
        self.addCleanup(lambda: self.assertEqual(self.errors, []))
        self.page = self.open_page(self.budget.html_path)

    def open_page(self, path: Path, width=None, height=None):
        context = self.browser.new_context(viewport={"width": width or self.WIDTH, "height": height or self.HEIGHT})
        self.addCleanup(context.close)
        page = context.new_page()
        page.on("pageerror", lambda e: self.errors.append(str(e)))
        page.add_init_script(STAND_IN)
        page.goto(path.as_uri())
        page.wait_for_function("document.body.classList.contains('in-app')")
        return page

    # ---- doing what a person does

    def tab(self, name: str) -> None:
        self.page.click(f'[data-tab="{name}"]')
        self.page.wait_for_function(f"document.getElementById('title').textContent === {json.dumps(name)}")

    def press(self, key: str) -> None:
        self.page.keyboard.press(key)

    def until(self, script: str, *args) -> None:
        self.page.wait_for_function(script, arg=args[0] if args else None, timeout=5000)

    def text(self, selector: str) -> str:
        return self.page.inner_text(selector)

    def js(self, script: str):
        return self.page.evaluate(script)

    def calls(self, name: str) -> list:
        return self.page.evaluate("name => window.calls(name)", name)

    def dialog_open(self, is_open: bool = True) -> None:
        self.until(f"modal.open === {json.dumps(is_open)}")

    def toast(self, words: str) -> None:
        self.page.wait_for_function("words => document.getElementById('toast').innerText === words", arg=words, timeout=5000)

    def mark_page(self) -> None:
        """A reload wipes this, which is how wait_for_reload knows one happened."""
        self.js("window.marker = 1")

    def wait_for_reload(self) -> None:
        self.until("window.marker === undefined && document.body.classList.contains('in-app')")
