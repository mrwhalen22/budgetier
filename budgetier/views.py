"""What each tab shows, worked out in Python. No Qt here, so all of it is tested on its own.

Money is in whole cents. A snapshot is built once per change to the data; each tab then asks
for what it needs, given the period and accounts chosen at the top of the window.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import date

from . import analyze

SUBSCRIPTIONS = "Subscriptions"
COLORED = 8  # categories with their own color; the rest share "Other"
RECENT = (("12", "Last 12 months"), ("6", "Last 6 months"), ("3", "Last 3 months"), ("all", "All time"))
SPARK_MONTHS = 18
LARGEST, TOP_MERCHANTS = 25, 15
HEAT_MONTHS, BUDGET_HISTORY, BUDGET_PREVIEW = 12, 6, 6
BALANCE_LINES = 8
KINDS = (("", "All kinds"), ("expense", "Expenses"), ("refund", "Refunds"), ("estimate", "Estimated"),
         ("income", "Income"), ("transfer", "Transfers"))


def month_name(month: str, year: bool = True) -> str:
    when = date(int(month[:4]), int(month[5:7]), 1)
    return f"{when:%b} {when.year}" if year else f"{when:%b}"


def day_name(day: str) -> str:
    when = date.fromisoformat(day)
    return f"{when:%b} {when.day}, {when.year}"


# ---- the data, once per change


@dataclass(frozen=True, slots=True)
class Tx:
    i: int  # position in the ledger's order, which the edit key follows
    date: str  # YYYY-MM-DD
    month: str  # YYYY-MM
    account: str
    description: str
    merchant: str
    category: str
    kind: str
    cents: int
    edited: bool = False


@dataclass(frozen=True)
class Account:
    id: str
    name: str
    bank: str
    number: str
    type: str
    count: int
    first: str | None
    last: str | None
    balance: int | None  # cents; negative on a card means owed
    balances: dict[str, int]  # month to month-end balance, in cents
    balance_as_of: str | None
    calculated: bool
    live: bool


@dataclass(frozen=True)
class Recurring:
    merchant: str
    category: str
    kind: str
    cadence: str
    count: int
    amount: int
    per_month: int
    low: int
    high: int
    first: str
    last: str
    next: str
    active: bool
    variable: bool
    price_change: int
    account: str  # the account's name


@dataclass(frozen=True)
class BudgetMonth:
    month: str
    partial: bool
    income: int
    base: int  # the income percent targets are taken from
    spent: dict[str, int]
    targets: dict[str, int]


@dataclass(frozen=True)
class Snapshot:
    txns: list[Tx]
    accounts: list[Account]  # by name
    categories: list[str]  # by spending over all history, so a category keeps its color
    end: str  # the newest transaction's date, or today
    partial_month: str | None
    coverage_from: str | None  # the first month with checking history
    recurring: list[Recurring]
    checks: list[dict]
    imports: list[dict]
    budget_targets: list[dict]  # category, mode, value: cents for an amount, a number for a percent
    budget_months: list[BudgetMonth]
    rules: list[dict]
    all_categories: list[str]
    months: list[str] = field(default_factory=list)  # every month from the first transaction to the end

    def __post_init__(self):
        if not self.months:
            first = self.txns[0].month if self.txns else self.end[:7]
            self.months.extend(_months_between(first, self.end[:7]))

    @property
    def by_id(self) -> dict[str, Account]:
        return {a.id: a for a in self.accounts}

    @property
    def colored(self) -> list[str]:
        return self.categories[:COLORED]


def _months_between(first: str, last: str) -> list[str]:
    year, month, out = int(first[:4]), int(first[5:7]), []
    while True:
        key = f"{year}-{month:02d}"
        out.append(key)
        if key >= last:
            return out
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)


def _count(value) -> int:
    """A count from imports.csv, where it's saved as text."""
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _cents(dollars) -> int:
    return round(dollars * 100)


def build(rows: list[dict], accounts: dict, recurring: list[dict], checks: list[dict], imports: list[dict],
          budget_report: dict, rules: list[dict], all_categories: list[str], today: date | None = None) -> Snapshot:
    """From the classified rows, recurring payments, checks, imports, budgets and rules."""
    ids = sorted(accounts, key=lambda a: accounts[a]["name"])
    balances = analyze.account_balances(rows, accounts)
    summaries = []
    for account in ids:
        own = [r for r in rows if r["account"] == account]
        info, balance = accounts[account], balances.get(account)
        if not own and not (balance and balance.get("live")):
            continue
        summaries.append(Account(
            id=account, name=info["name"], bank=info["bank"], number=info["number"], type=info["type"], count=len(own),
            first=min(r["date"] for r in own).isoformat() if own else None,
            last=max(r["date"] for r in own).isoformat() if own else None,
            balance=balance["current"] if balance else None, balances=dict(balance["months"]) if balance else {},
            balance_as_of=balance["as_of"] if balance else None,
            calculated=bool(balance and balance["calculated"]), live=bool(balance and balance.get("live"))))

    spend: Counter = Counter()
    for r in rows:
        if r["kind"] in analyze.SPENDING_KINDS:
            spend[r["category"]] -= r["cents"]
    end = max((r["date"] for r in rows), default=today or date.today())
    return Snapshot(
        txns=[Tx(i, r["date"].isoformat(), r["date"].strftime("%Y-%m"), r["account"], r["description"], r["merchant"],
                 r["category"], r["kind"], r["cents"], bool(r.get("edited"))) for i, r in enumerate(rows)],
        accounts=summaries, categories=[c for c, _ in spend.most_common()], end=end.isoformat(),
        partial_month=analyze.partial_month(end), coverage_from=analyze.coverage_start(rows, accounts),
        recurring=[Recurring(e["merchant"], e["category"], e["kind"], e["cadence"], e["count"], _cents(e["amount"]),
                             _cents(e["per_month"]), _cents(e["low"]), _cents(e["high"]), e["first"], e["last"], e["next"],
                             e["active"], e["variable"], _cents(e["price_change"]), accounts[e["account"]]["name"])
                   for e in recurring],
        checks=list(checks),
        imports=[{**i, "key": i.get("stored") or i["file"], "account": accounts[i["account"]]["name"],
                  **{n: _count(i.get(n)) for n in ("rows", "added", "duplicates")}} for i in imports[-30:]][::-1],
        budget_targets=[{**t, "value": _cents(t["value"]) if t["mode"] == "amount" else t["value"]}
                        for t in budget_report["targets"]],
        budget_months=[BudgetMonth(m["month"], m["partial"], _cents(m["income"]), _cents(m["base"]),
                                   {c: _cents(v) for c, v in m["spent"].items()},
                                   {c: _cents(v) for c, v in m["targets"].items()}) for m in budget_report["months"]],
        rules=list(rules), all_categories=list(all_categories))


def from_budget(budget) -> Snapshot:
    """Everything the window shows about this data folder, as it is now."""
    budgets = budget.budgets()  # first: a damaged file adds a notice to the checks
    rows, recurring, checks = budget.analysis()
    rules = budget.rules()
    names = sorted({*analyze.category_names(), *(r["category"] for r in rules), "Transfer", analyze.SAVED})
    return build(rows, budget.ledger.accounts, recurring, checks, budget.ledger.imports,
                 analyze.budget_report(rows, budget.ledger.accounts, budgets), rules, names)


# ---- the period and accounts chosen at the top


@dataclass(frozen=True)
class Choice:
    """What the period and account filters say. range is 12, 6, 3 or all for recent months,
    a year like 2026, or a month like 2026-03. accounts are ids, or None for all of them."""
    range: str = "12"
    accounts: frozenset[str] | None = None

    def has(self, account: str) -> bool:
        return self.accounts is None or account in self.accounts


def range_options(s: Snapshot) -> list[tuple[str, str, str]]:
    """(group, value, label) for the period list, newest first within each group."""
    years = list(dict.fromkeys(m[:4] for m in s.months))[::-1]
    return ([("Recent", v, label) for v, label in RECENT] + [("Year", y, y) for y in years]
            + [("Month", m, month_name(m)) for m in s.months[::-1]])


def range_months(s: Snapshot, choice: Choice) -> list[str]:
    r = choice.range
    if r == "all":
        return list(s.months)
    if len(r) == 4 and r.isdigit():  # a year, before the recent counts: 2026 isn't 2026 months
        return [m for m in s.months if m.startswith(r)]
    if r.isdigit():
        return s.months[-int(r):]
    return [r]


def range_label(s: Snapshot, choice: Choice) -> str:
    return next((label for _, value, label in range_options(s) if value == choice.range), choice.range)


def selected(s: Snapshot, choice: Choice) -> list[Tx]:
    months = set(range_months(s, choice))
    return [t for t in s.txns if t.month in months and choice.has(t.account)]


@dataclass
class Month:
    month: str
    income: int = 0
    spending: int = 0
    categories: dict[str, int] = field(default_factory=dict)


def monthly(txns: list[Tx], months: list[str]) -> list[Month]:
    """Income and spending per month. Refunds count against spending, so a category can
    end a month below zero."""
    out = {m: Month(m) for m in months}
    for t in txns:
        m = out.get(t.month)
        if m is None:
            continue
        if t.kind == "income":
            m.income += t.cents
        elif t.kind in analyze.SPENDING_KINDS:
            m.spending -= t.cents
            m.categories[t.category] = m.categories.get(t.category, 0) - t.cents
    return [out[m] for m in months]


def has_bills(s: Snapshot, choice: Choice, month: str) -> bool:
    """Before checking history starts, a month has card spending but no rent or income."""
    checking = any(a.type == "checking" and choice.has(a.id) for a in s.accounts)
    return not checking or not s.coverage_from or month >= s.coverage_from


def completed(s: Snapshot, choice: Choice, rows: list[Month]) -> list[Month]:
    """The months averages use: not the one in progress, nor any before checking history."""
    done = [r for r in rows if r.month != s.partial_month and has_bills(s, choice, r.month)]
    return done or rows


def billed(s: Snapshot, choice: Choice, rows: list[Month]) -> list[Month]:
    return [r for r in rows if has_bills(s, choice, r.month)] or rows


def category_totals(rows: list[Month]) -> list[tuple[str, int]]:
    totals: dict[str, int] = {}
    for r in rows:
        for c, v in r.categories.items():
            totals[c] = totals.get(c, 0) + v
    return sorted(totals.items(), key=lambda item: -item[1])


def active_bills(s: Snapshot) -> list[Recurring]:
    return [r for r in s.recurring if r.active and r.kind == "expense"]


@dataclass(frozen=True)
class Period:
    """How many months an average covers, and how many before checking history it left out."""
    months: int
    complete: int
    early: int


def period(s: Snapshot, choice: Choice, rows: list[Month]) -> Period:
    return Period(len(rows), len(completed(s, choice, rows)), sum(not has_bills(s, choice, r.month) for r in rows))


@dataclass(frozen=True)
class Owed:
    owed: int  # negative: what the cards owe
    missing: int  # cards with no balance


def owed(s: Snapshot) -> Owed | None:
    cards = [a for a in s.accounts if a.type == "credit"]
    known = [a for a in cards if a.balance is not None]
    if not known:
        return None
    return Owed(sum(a.balance for a in known), len(cards) - len(known))


def _average(total: int, count: int) -> int:
    return round(total / count) if count else 0


# ---- Overview


@dataclass(frozen=True)
class ThisMonth:
    month: str
    open: bool  # still in progress
    spent: int
    income: int
    compared_with: str | None  # last month, compared by the same day
    gap: int  # spent this month so far minus last month by the same day
    day: int
    due: int  # bills expected later this month
    due_count: int
    budget_left: int | None  # negative when over
    budget_count: int


def this_month(s: Snapshot, choice: Choice) -> ThisMonth | None:
    """What the averages can't say: how the newest month is going so far."""
    if len(range_months(s, choice)) == 1 or not s.months:
        return None
    month = s.months[-1]
    last = s.months[-2] if len(s.months) > 1 else None
    is_open = month == s.partial_month
    mine = [t for t in s.txns if choice.has(t.account)]
    day = s.end[8:]
    now = monthly(mine, [month])[0]
    compared, gap = None, 0
    if is_open and last and has_bills(s, choice, last):
        then = monthly([t for t in mine if t.date[8:] <= day], [last])[0]
        compared, gap = last, now.spending - then.spending
    due = [r for r in active_bills(s) if r.next > s.end and r.next.startswith(month)] if is_open else []
    plan = next((m for m in s.budget_months if m.month == month), None)
    left = None
    if plan and s.budget_targets and choice.accounts is None:
        left = sum(plan.targets.get(t["category"], 0) - plan.spent.get(t["category"], 0) for t in s.budget_targets)
    return ThisMonth(month, is_open, now.spending, now.income, compared, gap, int(day), sum(r.amount for r in due),
                     len(due), left, len(s.budget_targets))


@dataclass(frozen=True)
class Overview:
    months: list[str]
    one: bool  # a single month, so nothing is averaged
    period: Period
    income: int  # average over complete months
    spending: int
    estimated: int  # of that spending, estimated from card payments
    rate: float | None  # share of income kept
    kept: int
    spent_share: float  # of each dollar earned, at most 1
    recurring: int  # active bills a month
    recurring_count: int
    owed: Owed | None
    spark: list[tuple[str, float, bool]]  # month, height from 0 to 1, whether it's complete
    chart_income: list[int]
    chart_spending: list[int]
    categories: list[tuple[str, int]]  # where it went, up to 8
    warnings: list[dict]
    this_month: ThisMonth | None


def overview(s: Snapshot, choice: Choice) -> Overview:
    months = range_months(s, choice)
    txns = selected(s, choice)
    rows = monthly(txns, months)
    done = completed(s, choice, rows)
    income = _average(sum(r.income for r in done), len(done))
    spending = _average(sum(r.spending for r in done), len(done))
    done_months = {r.month for r in done}
    estimated = _average(-sum(t.cents for t in txns if t.kind == "estimate" and t.month in done_months), len(done))
    peak = max([r.spending for r in rows] + [1])
    bills = active_bills(s)
    return Overview(
        months=months, one=len(rows) == 1, period=period(s, choice, rows), income=income, spending=spending,
        estimated=estimated, rate=(income - spending) / income if income > 0 else None, kept=income - spending,
        spent_share=min(spending / income, 1) if income > 0 else 1, recurring=sum(r.per_month for r in bills),
        recurring_count=len(bills), owed=owed(s),
        spark=[(r.month, max(r.spending / peak, .02), r.month in done_months) for r in rows[-SPARK_MONTHS:]],
        chart_income=[r.income for r in rows], chart_spending=[r.spending for r in rows],
        categories=[(c, v) for c, v in category_totals(rows) if v > 0][:COLORED],
        warnings=[c for c in s.checks if c["level"] == "warning"], this_month=this_month(s, choice))


# ---- Spending


@dataclass(frozen=True)
class Spending:
    months: list[str]
    series: list[tuple[str, list[int]]]  # colored categories, then "Other"; no month below zero
    categories: list[tuple[str, int]]  # every category in the period, most spent first
    heat_months: list[str]  # the table shows the latest 12
    heat: dict[str, list[int]]  # category to its amounts in those months
    heat_peak: int


def spending(s: Snapshot, choice: Choice) -> Spending:
    months = range_months(s, choice)
    rows = monthly(selected(s, choice), months)
    totals = category_totals(rows)
    colored = set(s.colored)
    series = [(c, [max(r.categories.get(c, 0), 0) for r in rows]) for c, _ in totals if c in colored]
    rest = [sum(max(v, 0) for c, v in r.categories.items() if c not in colored) for r in rows]
    if any(rest):
        series.append(("Other", rest))
    shown = rows[-HEAT_MONTHS:]
    return Spending(months, series, totals, [r.month for r in shown],
                    {c: [r.categories.get(c, 0) for r in shown] for c, _ in totals},
                    max([v for r in shown for v in r.categories.values()] + [1]))


# ---- Recurring


@dataclass(frozen=True)
class RecurringView:
    bills: int  # a month, active only
    subscriptions: int
    subscription_count: int
    income: int
    income_count: int
    expenses: list[Recurring]  # the bills table, stopped ones too if asked
    incomes: list[Recurring]


def recurring(s: Snapshot, include_stopped: bool = False) -> RecurringView:
    listed = [r for r in s.recurring if include_stopped or r.active]
    bills = [r for r in listed if r.kind == "expense" and r.active]
    income = [r for r in listed if r.kind == "income" and r.active]
    subs = [r for r in bills if r.category == SUBSCRIPTIONS]
    return RecurringView(sum(r.per_month for r in bills), sum(r.per_month for r in subs), len(subs),
                         sum(r.per_month for r in income), len(income),
                         [r for r in listed if r.kind == "expense"], [r for r in listed if r.kind == "income"])


# ---- Largest


def is_bill(s: Snapshot, t: Tx) -> bool:
    """Rent would fill the list, and bills are already on Recurring. A one-off from a merchant
    that also bills you stays, because its amount is outside what the bill has ever been."""
    return any(r.kind == "expense" and r.merchant == t.merchant and r.low <= -t.cents <= r.high for r in s.recurring)


@dataclass(frozen=True)
class Largest:
    merchants: list[tuple[str, int, int]]  # name, total spent, how many
    expenses: list[Tx]
    hidden: int  # bills left out


def largest(s: Snapshot, choice: Choice, include_bills: bool = False) -> Largest:
    expenses = [t for t in selected(s, choice) if t.kind == "expense"]
    shown = expenses if include_bills else [t for t in expenses if not is_bill(s, t)]
    by: dict[str, list[int]] = {}
    for t in expenses:
        total = by.setdefault(t.merchant, [0, 0])
        total[0] -= t.cents
        total[1] += 1
    merchants = sorted(((name, v, n) for name, (v, n) in by.items()), key=lambda m: -m[1])[:TOP_MERCHANTS]
    return Largest(merchants, sorted(shown, key=lambda t: t.cents)[:LARGEST], len(expenses) - len(shown))


# ---- Savings


@dataclass(frozen=True)
class Savings:
    kept: int  # income minus spending over the months with bills
    kept_from: str | None  # when months before checking history were left out
    rate: float | None  # over complete months
    averaged: bool  # the rate covers complete months, not a single one
    moved: int  # to savings and investing, net of withdrawals
    balance: int | None  # savings accounts' latest known balance
    months: list[str]  # the months kept is shown for
    nets: list[int]
    running: list[int]
    balance_months: list[str]
    balance_lines: list[tuple[str, list[int | None]]]  # account name, month-end balance per month


def savings(s: Snapshot, choice: Choice) -> Savings:
    months = range_months(s, choice)
    txns = selected(s, choice)
    rows = monthly(txns, months)
    done = completed(s, choice, rows)
    income, spent = sum(r.income for r in done), sum(r.spending for r in done)
    scope = billed(s, choice, rows)
    types = {a.id: a.type for a in s.accounts}
    moved = sum(-t.cents if t.category == analyze.SAVED else t.cents for t in txns
                if t.category == analyze.SAVED or (t.kind == "transfer" and types.get(t.account) == "savings"))
    held = [a for a in s.accounts if a.type == "savings" and choice.has(a.id) and a.balance is not None]
    nets = [r.income - r.spending for r in scope]
    running, total = [], 0
    for n in nets:
        total += n
        running.append(total)
    shown = [a for a in s.accounts if choice.has(a.id) and a.balances][:BALANCE_LINES]
    return Savings(
        kept=sum(nets), kept_from=scope[0].month if len(scope) < len(rows) else None,
        rate=(income - spent) / income if income > 0 else None, averaged=len(rows) > 1,
        moved=moved, balance=sum(a.balance for a in held) if held else None, months=[r.month for r in scope], nets=nets,
        running=running, balance_months=months,
        balance_lines=[(a.name, [a.balances.get(m) for m in months]) for a in shown])


# ---- Accounts


@dataclass(frozen=True)
class AccountsView:
    cash: int | None  # checking and savings with a balance
    cash_accounts: int
    banked_accounts: int  # all that aren't cards
    owed: Owed | None
    net: int | None  # cash minus what cards owe
    accounts: list[Account]
    imports: list[dict]
    warnings: list[dict]
    notes: list[dict]  # the checks that aren't warnings


def accounts(s: Snapshot) -> AccountsView:
    banked = [a for a in s.accounts if a.type != "credit" and a.balance is not None]
    cards = [a for a in s.accounts if a.type == "credit" and a.balance is not None]
    cash = sum(a.balance for a in banked) if banked else None
    o = owed(s)
    return AccountsView(cash, len(banked), sum(a.type != "credit" for a in s.accounts), o,
                        cash + sum(a.balance for a in cards) if banked and o else None, list(s.accounts), list(s.imports),
                        [c for c in s.checks if c["level"] == "warning"], [c for c in s.checks if c["level"] != "warning"])


# ---- Transactions


SORTS = {"date": lambda t, names: t.date, "merchant": lambda t, names: t.merchant.lower(),
         "category": lambda t, names: t.category, "amount": lambda t, names: t.cents,
         "account": lambda t, names: names.get(t.account, "")}


@dataclass(frozen=True)
class Found:
    txns: list[Tx]
    net: int


def transactions(s: Snapshot, choice: Choice, query: str = "", category: str = "", kind: str = "",
                 sort: str = "date", descending: bool = True) -> Found:
    """Newest first unless asked otherwise. Ties keep the ledger's order either way."""
    q = query.lower()
    found = [t for t in selected(s, choice) if (not category or t.category == category) and (not kind or t.kind == kind)
             and (not q or q in f"{t.description} {t.merchant}".lower())]
    names = {a.id: a.name for a in s.accounts}
    key = SORTS[sort]
    found.sort(key=lambda t: key(t, names), reverse=descending)
    return Found(found, sum(t.cents for t in found))


def edit_target(s: Snapshot, t: Tx) -> dict:
    """What Budget.save_edit needs to find this one transaction: n tells apart identical
    rows, counted the way analyze.edit_keys counts them."""
    words = " ".join(t.description.upper().split())
    n = sum(1 for x in s.txns[:t.i] if x.date == t.date and x.account == t.account and x.cents == t.cents
            and " ".join(x.description.upper().split()) == words)
    return {"date": t.date, "account": t.account, "cents": t.cents, "description": t.description, "n": n}


def rule_categories(s: Snapshot) -> list[str]:
    """What a rule or a single change can choose from."""
    return sorted({*s.all_categories, *s.categories} - {analyze.UNCATEGORIZED, analyze.ESTIMATED})


def category_filter(s: Snapshot) -> list[str]:
    """The category list on Transactions: the moves first, then by spending."""
    return ["Transfer", analyze.SAVED, "Income", *(c for c in s.categories if c != "Income")]


# ---- Rules


@dataclass(frozen=True)
class Unsorted:
    merchant: str
    description: str  # the first one seen, to show what the bank calls it
    count: int
    total: int


def uncategorized(s: Snapshot) -> list[Unsorted]:
    """Merchants still needing a category, the most money first."""
    by: dict[str, list] = {}
    for t in s.txns:
        if t.category == analyze.UNCATEGORIZED:
            m = by.setdefault(t.merchant, [t.description, 0, 0])
            m[1] += 1
            m[2] += t.cents
    return sorted((Unsorted(name, d, n, total) for name, (d, n, total) in by.items()), key=lambda u: u.total)


# ---- Budgets


def budget_choices(s: Snapshot) -> list[str]:
    """Categories that can still get a budget."""
    taken = {t["category"] for t in s.budget_targets}
    return sorted(c for c in {*s.all_categories, *s.categories} if c not in analyze.NOT_BUDGETED and c not in taken)


def complete_budget_months(s: Snapshot) -> list[BudgetMonth]:
    done = [m for m in s.budget_months if not m.partial][-BUDGET_PREVIEW:]
    return done or list(s.budget_months)


@dataclass(frozen=True)
class BudgetLine:
    category: str
    mode: str
    value: int | float  # cents for an amount, a number for a percent
    goal: int
    spent: int
    left: int  # negative when over
    used: float  # share of the goal spent
    state: str  # "over", "near" or ""


@dataclass(frozen=True)
class BudgetsView:
    month: BudgetMonth | None
    months: list[str]  # for the month list, newest first
    goal: int
    spent: int
    left: int
    other: int  # spending with no budget
    lines: list[BudgetLine]  # the fullest first
    uses_percent: bool
    history: list[BudgetMonth]
    history_lines: dict[str, list[tuple[int, bool]]]  # category to (spent, over target) per month


def _line(target: dict, m: BudgetMonth) -> BudgetLine:
    goal, spent = m.targets.get(target["category"], 0), m.spent.get(target["category"], 0)
    used = spent / goal if goal > 0 else (2 if spent > 0 else 0)
    return BudgetLine(target["category"], target["mode"], target["value"], goal, spent, goal - spent, used,
                      "over" if used > 1 else "near" if used >= .9 else "")


def budgets(s: Snapshot, month: str | None = None) -> BudgetsView:
    if not s.budget_months:
        return BudgetsView(None, [], 0, 0, 0, 0, [], False, [], {})
    m = next((x for x in s.budget_months if x.month == month), s.budget_months[-1])
    lines = [_line(t, m) for t in s.budget_targets]
    budgeted = {t["category"] for t in s.budget_targets}
    history = s.budget_months[-BUDGET_HISTORY:]
    return BudgetsView(
        m, [x.month for x in s.budget_months][::-1], sum(x.goal for x in lines), sum(x.spent for x in lines),
        sum(x.left for x in lines), sum(v for c, v in m.spent.items() if c not in budgeted),
        sorted(lines, key=lambda x: -(x.spent / (x.goal or 1))),
        any(t["mode"] == "percent" for t in s.budget_targets), history,
        {t["category"]: [(h.spent.get(t["category"], 0), h.spent.get(t["category"], 0) > h.targets.get(t["category"], 0))
                         for h in history] for t in s.budget_targets})


@dataclass(frozen=True)
class BudgetPreview:
    average: int  # spent a month in this category lately
    income: int  # earned a month lately
    amount: int | None  # what a percent target comes to
    share: float | None  # what an amount target is of income


def budget_preview(s: Snapshot, category: str, mode: str, value: str) -> BudgetPreview:
    months = complete_budget_months(s)
    n = len(months) or 1
    income = round(sum(m.income for m in months) / n)
    average = round(sum(m.spent.get(category, 0) for m in months) / n)
    try:
        number = float(value.replace("$", "").replace(",", "").strip().rstrip("%"))
    except ValueError:
        number = 0
    amount = round(income * number / 100) if mode == "percent" and number > 0 else None
    share = number * 100 / income if mode == "amount" and number > 0 and income > 0 else None
    return BudgetPreview(average, income, amount, share)
