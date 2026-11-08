"""views.py must agree with the page it replaces, on the same data and the same choices.

Temporary: this goes when the page does (docs/qt-migration.md, step 7). It runs the page's own
JavaScript in Chromium and compares its numbers, in dollars, with views.py's, in cents.
"""
import unittest
from datetime import date

from budgetier import views
from tests.browser import PageCase

# A year is left out: the page reads 2025 as "the last 2025 months". views.py doesn't.
RANGES = ("12", "3", "all", "2026-03", "2026-10")
ACCOUNTS = (None, frozenset({"card-0002"}), frozenset({"chk-0001", "sav-0003"}))

CHOOSE = """([range, ids]) => {
  S.range = range;
  S.accts = new Set(ids === null ? D.accounts.map(a => a.index) : D.accounts.filter(a => ids.includes(a.id)).map(a => a.index));
}"""


def cents(dollars) -> int:
    return round(dollars * 100)


class Parity(PageCase):
    engine = "chromium"

    def setUp(self):
        super().setUp()
        self.s = views.from_budget(self.budget)

    def choices(self):
        """Each choice in turn, chosen on the page too. Each test runs its checks in a subTest."""
        for r in RANGES:
            for ids in ACCOUNTS:
                self.page.evaluate(CHOOSE, [r, sorted(ids) if ids else None])
                yield views.Choice(r, ids)

    def test_the_months_and_their_totals(self):
        for choice in self.choices():
            with self.subTest(range=choice.range, accounts=choice.accounts):
                self.assertEqual(self.js("rangeMonths()"), views.range_months(self.s, choice))
                page = self.js("monthly(selected(), rangeMonths()).map(m => [m.month, m.income, m.spending, m.cats])")
                ours = views.monthly(views.selected(self.s, choice), views.range_months(self.s, choice))
                self.assertEqual([[m, cents(i), cents(sp), {c: cents(v) for c, v in cats.items()}] for m, i, sp, cats in page],
                                 [[m.month, m.income, m.spending, m.categories] for m in ours])

    def test_the_overview(self):
        for choice in self.choices():
            with self.subTest(range=choice.range, accounts=choice.accounts):
                inc, sp, est, rec = self.js("""(() => {
                  const rows = monthly(selected(), rangeMonths()), done = completed(rows), ms = new Set(done.map(r => r.month));
                  return [sum(done, r => r.income) / done.length, sum(done, r => r.spending) / done.length,
                          -sum(selected().filter(t => t.kind === "estimate" && ms.has(t.month)), t => t.amt) / done.length,
                          sum(activeRecurring(), r => r.per_month)]; })()""")
                o = views.overview(self.s, choice)
                self.assertAlmostEqual(o.income, inc * 100, delta=1)
                self.assertAlmostEqual(o.spending, sp * 100, delta=1)
                self.assertAlmostEqual(o.estimated, est * 100, delta=1)
                self.assertAlmostEqual(o.recurring, rec * 100, delta=o.recurring_count)  # each bill rounds to a cent
                categories = self.js("catTotals(monthly(selected(), rangeMonths())).filter(c => c[1] > 0).slice(0, 8)")
                self.assertEqual([(c, cents(v)) for c, v in categories], o.categories)

    def test_this_month(self):
        for choice in self.choices():
            with self.subTest(range=choice.range, accounts=choice.accounts):
                html = self.js("thisMonth()")
                now = views.this_month(self.s, choice)
                if now is None:
                    self.assertEqual(html, "")
                    continue
                for amount in (now.spent, now.income, abs(now.gap), now.due):
                    if amount:
                        self.assertIn(self.page.evaluate("v => money(v)", amount / 100), html)
                self.assertEqual("Compared with" in html, now.compared_with is not None)
                self.assertEqual("Bills still to come" in html, now.due_count > 0)
                self.assertEqual("budget" in html, now.budget_left is not None)

    def test_spending(self):
        for choice in self.choices():
            with self.subTest(range=choice.range, accounts=choice.accounts):
                page = self.js("""(() => {
                  const rows = monthly(selected(), rangeMonths()), cats = catTotals(rows);
                  const series = cats.map(c => c[0]).filter(c => CAT_COLOR[c]).map(c => [c, rows.map(r => Math.max(r.cats[c] || 0, 0))]);
                  const rest = rows.map(r => sum(Object.entries(r.cats).filter(([k]) => !CAT_COLOR[k]), e => Math.max(e[1], 0)));
                  if (rest.some(v => v)) series.push(["Other", rest]);
                  return series; })()""")
                ours = views.spending(self.s, choice).series
                self.assertEqual([(c, [cents(v) for v in values]) for c, values in page], ours)

    def test_largest(self):
        for choice in self.choices():
            with self.subTest(range=choice.range, accounts=choice.accounts):
                for every in (False, True):
                    page = self.page.evaluate("""all => {
                      const tx = selected().filter(t => t.kind === "expense"), shown = all ? tx : tx.filter(t => !isBill(t));
                      return shown.slice().sort((a, b) => a.amt - b.amt).slice(0, 25).map(t => t.i); }""", every)
                    self.assertEqual(page, [t.i for t in views.largest(self.s, choice, every).expenses])

    def test_savings(self):
        for choice in self.choices():
            with self.subTest(range=choice.range, accounts=choice.accounts):
                nets, moved = self.js("""(() => {
                  const tx = selected(), scope = billed(monthly(tx, rangeMonths())), SAVED = "Savings & Investing";
                  return [scope.map(r => Math.round((r.income - r.spending) * 100) / 100),
                          sum(tx.filter(t => t.cat === SAVED || (t.kind === "transfer" && ACCT[t.acct].type === "savings")), t => t.cat === SAVED ? -t.amt : t.amt)]; })()""")
                s = views.savings(self.s, choice)
                self.assertEqual([cents(n) for n in nets], s.nets)
                self.assertEqual(cents(moved), s.moved)

    def test_transactions_newest_first(self):
        for choice in self.choices():
            with self.subTest(range=choice.range, accounts=choice.accounts):
                page = self.js("selected().sort((a, b) => (a.date < b.date ? -1 : a.date > b.date ? 1 : 0) * -1).map(t => t.i)")
                self.assertEqual(page, [t.i for t in views.transactions(self.s, choice).txns])

    def test_merchants_needing_a_category(self):
        page = self.js("uncategorized().map(m => [m.merchant, m.n, m.total])")
        self.assertEqual([(m, n, cents(total)) for m, n, total in page],
                         [(u.merchant, u.count, u.total) for u in views.uncategorized(self.s)])

    def test_budgets(self):
        page = self.js("B.months.map(m => [m.month, m.targets, m.spent])")
        self.assertEqual([[m, {c: cents(v) for c, v in t.items()}, {c: cents(v) for c, v in sp.items()}] for m, t, sp in page],
                         [[m.month, m.targets, m.spent] for m in self.s.budget_months])
        self.assertEqual(self.js("budgetChoices()"), views.budget_choices(self.s))



def card(day, text, cents):
    return {"date": day, "account": "card-0002", "description": text, "amount": f"{cents / 100:.2f}", "cents": cents,
            "balance": None, "bank_category": "", "source": "x", "sync_id": ""}


class ParityBeforeChecking(Parity):
    """Card spending from before checking history starts, which averages must leave out."""
    extra_rows = (card(date(2025, 6, 9), "KROGER #123", -6100), card(date(2025, 7, 2), "CHIPOTLE 2291", -1300),
                  card(date(2025, 7, 20), "NETFLIX.COM", -1599))


del PageCase  # imported only to build on

if __name__ == "__main__":
    unittest.main()
