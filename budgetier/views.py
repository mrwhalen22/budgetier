"""What each tab shows, worked out in Python. No Qt here, so all of it is tested on its own.

Money is in whole cents. A snapshot is built once per change to the data; each tab then asks
for what it needs, given the period and accounts chosen at the top of the window.
"""
from __future__ import annotations

import calendar
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from . import analyze
from .accounts import INVESTED, KEPT, OWED

SUBSCRIPTIONS = "Subscriptions"
COLORED = 8  # categories with their own color; the rest share "Other"
RECENT = (("12", "Last 12 months"), ("6", "Last 6 months"), ("3", "Last 3 months"), ("all", "All time"))
SPARK_MONTHS = 18
LARGEST, TOP_MERCHANTS = 10, 10
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
    key: str = ""  # how edits and splits find it, when there are any
    whole: int = 0  # for a part of a split transaction: the whole of it; otherwise its own amount
    split: bool = False
    note: str = ""
    tags: tuple[str, ...] = ()


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
    balance: int | None  # cents; negative on a card or loan means owed
    balances: dict[str, int]  # month to month-end balance, in cents
    balance_as_of: str | None
    calculated: bool
    live: bool
    points: tuple[tuple[str, int], ...] = ()  # an investing account's known balances: day, cents


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
    account_id: str = ""


@dataclass(frozen=True)
class BudgetMonth:
    month: str
    partial: bool
    income: int
    base: int  # the income percent targets are taken from
    spent: dict[str, int]
    targets: dict[str, int]  # with anything carried over in
    carried: dict[str, int] = field(default_factory=dict)  # into this month, for budgets that roll over


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
    goals: list[dict] = field(default_factory=list)  # savings goals as saved, each with its id

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
          budget_report: dict, rules: list[dict], all_categories: list[str], today: date | None = None,
          goals: dict | None = None) -> Snapshot:
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
            calculated=bool(balance and balance["calculated"]), live=bool(balance and balance.get("live")),
            points=tuple(balance.get("points", ())) if balance else ()))

    spend: Counter = Counter()
    for r in rows:
        if r["kind"] in analyze.SPENDING_KINDS:
            spend[r["category"]] -= r["cents"]
    end = max((r["date"] for r in rows), default=today or date.today())
    return Snapshot(
        txns=[Tx(i, r["date"].isoformat(), analyze.month_of(r["date"]), r["account"], r["description"], r["merchant"],
                 r["category"], r["kind"], r["cents"], bool(r.get("edited")), r.get("key", ""), r.get("whole", r["cents"]),
                 bool(r.get("split")), r.get("note", ""), tuple(r.get("tags", ()))) for i, r in enumerate(rows)],
        accounts=summaries, categories=[c for c, _ in spend.most_common()], end=end.isoformat(),
        partial_month=analyze.partial_month(end), coverage_from=analyze.coverage_start(rows, accounts),
        recurring=[Recurring(e["merchant"], e["category"], e["kind"], e["cadence"], e["count"], _cents(e["amount"]),
                             _cents(e["per_month"]), _cents(e["low"]), _cents(e["high"]), e["first"], e["last"], e["next"],
                             e["active"], e["variable"], _cents(e["price_change"]), accounts[e["account"]]["name"],
                             e["account"])
                   for e in recurring],
        checks=list(checks),
        imports=[{**i, "key": i.get("stored") or i["file"], "account": accounts[i["account"]]["name"],
                  **{n: _count(i.get(n)) for n in ("rows", "added", "duplicates")}} for i in imports[-30:]][::-1],
        budget_targets=[{**t, "value": _cents(t["value"]) if t["mode"] == "amount" else t["value"]}
                        for t in budget_report["targets"]],
        budget_months=_carry([BudgetMonth(m["month"], m["partial"], _cents(m["income"]), _cents(m["base"]),
                                          {c: _cents(v) for c, v in m["spent"].items()},
                                          {c: _cents(v) for c, v in m["targets"].items()}) for m in budget_report["months"]],
                             budget_report["targets"]),
        rules=list(rules), all_categories=list(all_categories),
        goals=[{**g, "id": goal_id} for goal_id, g in (goals or {}).items()])


def _carry(months: list[BudgetMonth], targets: list[dict]) -> list[BudgetMonth]:
    """A budget that rolls over adds what was left last month to this month's target, and takes
    away what went over, from the month it started rolling over."""
    rolling = [t for t in targets if t.get("rollover")]
    if not rolling:
        return months
    running = {t["category"]: 0 for t in rolling}
    out = []
    for m in months:
        targets_now, carried = dict(m.targets), {}
        for t in rolling:
            c = t["category"]
            if m.month < (t.get("since") or ""):
                continue
            carried[c] = running[c]
            targets_now[c] = targets_now.get(c, 0) + running[c]
            running[c] = targets_now[c] - m.spent.get(c, 0)
        out.append(BudgetMonth(m.month, m.partial, m.income, m.base, m.spent, targets_now, carried))
    return out


def from_budget(budget) -> Snapshot:
    """Everything the window shows about this data folder, as it is now."""
    budgets = budget.budgets()  # first: a damaged file adds a notice to the checks
    rows, recurring, checks = budget.analysis()
    rules = budget.rules()
    names = sorted({*analyze.category_names(), *(r["category"] for r in rules), "Transfer", analyze.SAVED,
                    *analyze.INVESTING_CATEGORIES})
    return build(rows, budget.ledger.accounts, recurring, checks, budget.ledger.imports,
                 analyze.budget_report(rows, budget.ledger.accounts, budgets), rules, names, goals=budget.goals())


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
    expenses: list[Tx]  # the biggest from each merchant, biggest first
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
    # One from each merchant: otherwise a weekly grocery run fills the list, and the one-off
    # purchases it's for get pushed off it.
    biggest, seen = [], set()
    for t in sorted(shown, key=lambda t: t.cents):
        if t.merchant not in seen:
            seen.add(t.merchant)
            biggest.append(t)
    return Largest(merchants, biggest[:LARGEST], len(expenses) - len(shown))


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
                if t.category == analyze.SAVED or (t.kind == "transfer" and types.get(t.account) in KEPT
                                                    and t.category != analyze.ACTIVITY))
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


# ---- what's new since you last looked


@dataclass(frozen=True)
class News:
    since: str  # the newest day there was last time
    count: int  # transactions after it
    spent: int
    received: int
    subscriptions: list[Recurring]  # payments found to recur that weren't before
    prices: list[Recurring]  # bills whose price changed since


def seen(s: Snapshot) -> dict:
    """What's here now, to compare with next time. Kept small: a day and some names."""
    return {"through": s.end if s.txns else None, "recurring": sorted({r.merchant for r in active_bills(s)})}


def news(s: Snapshot, last: dict | None) -> News | None:
    """What came in after the newest day seen last time. Old history imported since isn't
    news, so it's left out by being dated before that day."""
    if not isinstance(last, dict) or not isinstance(last.get("through"), str) or not s.txns:
        return None
    since = last["through"]
    fresh = [t for t in s.txns if t.date > since]
    known = set(last.get("recurring") or [])
    bills = active_bills(s)
    found = News(since, len(fresh), -sum(t.cents for t in fresh if t.kind in analyze.SPENDING_KINDS),
                 sum(t.cents for t in fresh if t.kind == "income"),
                 [r for r in bills if r.merchant not in known],
                 [r for r in bills if r.price_change and r.last > since])
    return found if found.count or found.subscriptions or found.prices else None


# ---- reminders to bring things up to date

SYNC_AFTER_DAYS = 7  # a week without a sync is worth a reminder
FILES_AFTER_DAYS = 30  # files come monthly, as statements do


@dataclass(frozen=True)
class Reminder:
    title: str
    detail: str
    action: str  # "sync" or "add": what its button does


def _ago(days: int) -> str:
    return "today" if days == 0 else "yesterday" if days == 1 else f"{days} days ago"


def reminder(s: Snapshot, sync: dict, now: datetime | None = None) -> Reminder | None:
    """Whether the numbers are out of date enough to say so: a bank connection that hasn't
    synced in a week, or files that stop more than a month back."""
    now = now or datetime.now()
    if sync.get("connected") and sync.get("linked"):
        last = sync.get("lastSync")
        if not last:
            return Reminder("Not synced yet", "Sync to bring in your linked accounts' recent transactions.", "sync")
        try:
            days = (now.date() - datetime.fromisoformat(last).date()).days  # calendar days, as people count them
        except (TypeError, ValueError):
            return None
        if days < SYNC_AFTER_DAYS:
            return None
        return Reminder(f"Last synced {_ago(days)}", "Sync to bring these numbers up to date.", "sync")
    if sync.get("connected") or not s.txns:
        return None
    days = (now.date() - date.fromisoformat(s.end)).days
    if days < FILES_AFTER_DAYS:
        return None
    return Reminder(f"Your newest transaction is from {day_name(s.end)}, {_ago(days)}",
                    "Download recent history from your banks and add it to bring these numbers up to date.", "add")


# ---- Investments


@dataclass(frozen=True)
class Investments:
    accounts: list[Account]  # investing and retirement accounts chosen at the top
    total: int | None  # their latest known balances
    retirement: int | None  # the retirement accounts' part of it
    start: int | None  # what they held as the period began
    end: int | None  # and as it ended
    contributed: int  # paid in over the period, net of withdrawals
    growth: int | None  # the change in balance that wasn't paid in: markets, dividends, fees
    growth_rate: float | None  # growth against what was invested over the period
    tracked_from: str | None  # the first day a balance is known, which growth is seen from
    months: list[str]
    balance: list[int | None]  # their month-end balances added up
    paid_in: list[int | None]  # the starting balance plus what's been paid in since
    lines: list[tuple[str, list[int | None]]]  # each account's month-end balance
    monthly_contribution: int  # paid in on average over recent complete months


def _between(account: Account, flows: list[tuple[str, int]], first: str, last: str) -> tuple[int, int, int] | None:
    """(start, end, paid in between) for one account over the days first to last, from
    balances it really had: the last known before the period, or else the first in it, and
    the last in it. A month's carried-over balance isn't one, so it can't fake a loss."""
    before = [p for p in account.points if p[0] < first]
    inside = [p for p in account.points if first <= p[0] <= last]
    start = before[-1] if before else inside[0] if inside else None
    end = inside[-1] if inside else None
    if start is None or end is None or end[0] <= start[0]:
        return None
    return start[1], end[1], sum(cents for day, cents in flows if start[0] < day <= end[0])


def investments(s: Snapshot, choice: Choice) -> Investments:
    held = [a for a in s.accounts if a.type in INVESTED and choice.has(a.id)]
    months = range_months(s, choice)
    flows: dict[str, list[tuple[str, int]]] = {a.id: [] for a in held}  # paid in or taken out, from outside them
    paid: Counter = Counter()  # the same, by month
    for t in s.txns:
        if t.account in flows and t.kind == "transfer" and t.category != analyze.ACTIVITY:
            flows[t.account].append((t.date, t.cents))
            paid[t.month] += t.cents

    def total(month: str) -> int | None:
        known = [a.balances[month] for a in held if month in a.balances]
        return sum(known) if known else None

    balance = [total(m) for m in months]
    # The line starts at the first balance shown, then adds what's paid in. An account first
    # seen partway through is added as it appears: it was brought in, not grown.
    paid_in, running, seen = [], None, set()
    for m, b in zip(months, balance):
        arriving = sum(a.balances[m] for a in held if m in a.balances and a.id not in seen)
        seen |= {a.id for a in held if m in a.balances}
        running = b if running is None else running + paid[m] + arriving
        paid_in.append(running if b is not None else None)
    first, last = (months[0] + "-01", months[-1] + "-31") if months else ("", "")
    measured = [m for m in (_between(a, flows[a.id], first, last) for a in held) if m]
    start, end, between = (sum(m[i] for m in measured) for i in range(3))
    growth = end - start - between if measured else None
    invested = start + between / 2
    current = [a for a in held if a.balance is not None]
    began = min([day[:7] for a in held for day, _ in a.points] + [m for m, c in paid.items() if c], default=None)
    recent = [m for m in s.months if m != s.partial_month and began and m >= began][-12:]
    points = [p for a in held for p in a.points]
    return Investments(
        accounts=held, total=sum(a.balance for a in current) if current else None,
        retirement=sum(a.balance for a in current if a.type == "retirement") if any(a.type == "retirement" for a in current)
        else None,
        start=start if measured else None, end=end if measured else None, contributed=sum(paid[m] for m in months),
        growth=growth, growth_rate=growth / invested if growth is not None and invested > 0 else None,
        tracked_from=min(day for day, _ in points) if points else None,
        months=months, balance=balance, paid_in=paid_in,
        lines=[(a.name, [a.balances.get(m) for m in months]) for a in held if a.balances][:BALANCE_LINES],
        monthly_contribution=max(0, round(sum(paid[m] for m in recent) / len(recent))) if recent else 0)


@dataclass(frozen=True)
class Grouped:
    """Rows in investing accounts with the same name and category, to check together."""
    merchant: str
    category: str
    count: int
    total: int
    descriptions: list[str]  # the bank's own wording, most recent first
    txns: list[Tx] = field(default_factory=list)


def investing_rows(s: Snapshot, ids: set[str] | None = None) -> list[Grouped]:
    """What's in investing and retirement accounts, by name, under each of their three
    categories in turn, biggest first."""
    held = {a.id for a in s.accounts if a.type in INVESTED and (ids is None or a.id in ids)}
    groups: dict[tuple[str, str], list[Tx]] = {}
    for t in s.txns:
        if t.account in held:
            groups.setdefault((t.merchant, t.category), []).append(t)
    order = {c: i for i, c in enumerate(analyze.INVESTING_CATEGORIES)}
    found = [Grouped(merchant, category, len(txns), sum(t.cents for t in txns),
                     list(dict.fromkeys(t.description for t in reversed(txns))), txns)
             for (merchant, category), txns in groups.items()]
    return sorted(found, key=lambda g: (order.get(g.category, len(order)), -abs(g.total), g.merchant))


@dataclass(frozen=True)
class Plan:
    """What the retirement estimate assumes. Rates are percents a year, after inflation, so
    what it shows is in today's dollars."""
    age: int = 35
    retire_at: int = 65
    monthly: int | None = None  # cents paid in each month; None for what's been paid in lately
    growth: float = 5.0
    withdraw: float = 4.0
    include_investing: bool = False  # count investing accounts too, not only retirement ones

    @classmethod
    def from_saved(cls, saved) -> Plan:
        """A plan that can't be read is worth no more than the default."""
        if not isinstance(saved, dict):
            return cls()
        plain = cls()

        def number(name, kind, low, high):
            value = saved.get(name, getattr(plain, name))
            return kind(value) if type(value) in (int, float) and low <= value <= high else getattr(plain, name)
        monthly = saved.get("monthly")
        return cls(age=number("age", int, 16, 100), retire_at=number("retire_at", int, 16, 110),
                   monthly=int(monthly) if type(monthly) in (int, float) and 0 <= monthly <= 10**9 else None,
                   growth=number("growth", float, -10, 20), withdraw=number("withdraw", float, 0.5, 15),
                   include_investing=bool(saved.get("include_investing", False)))

    def saved(self) -> dict:
        return {"age": self.age, "retire_at": self.retire_at, "monthly": self.monthly, "growth": self.growth,
                "withdraw": self.withdraw, "include_investing": self.include_investing}


@dataclass(frozen=True)
class Projection:
    balance: int  # what's counted, today
    monthly: int  # paid in each month until retiring
    years: int
    at_retirement: int  # in today's dollars
    income: int  # a month, drawing the withdrawal rate each year
    ages: list[str]  # each year's age, for the chart
    path: list[int]  # the balance at each of those ages
    paid: list[int]  # what had been paid in by then, with today's balance


def project(balance: int, monthly: int, plan: Plan) -> Projection:
    """Growing at the plan's rate, compounded each month, with the same paid in each month."""
    years = max(0, plan.retire_at - plan.age)
    rate = (1 + plan.growth / 100) ** (1 / 12) - 1
    value, paid = float(balance), float(balance)
    path, paid_in = [round(value)], [round(paid)]
    for _ in range(years):
        for _ in range(12):
            value = value * (1 + rate) + monthly
            paid += monthly
        path.append(round(value))
        paid_in.append(round(paid))
    at = path[-1]
    return Projection(balance, monthly, years, at, round(at * plan.withdraw / 100 / 12),
                      [str(plan.age + i) for i in range(years + 1)], path, paid_in)


def retirement(s: Snapshot, plan: Plan) -> Projection | None:
    """The estimate, from the accounts as they are now: not filtered by the choices at the top."""
    kinds = INVESTED if plan.include_investing else ("retirement",)
    counted = [a for a in s.accounts if a.type in kinds and a.balance is not None]
    if not counted:
        return None
    every = investments(s, Choice("12", frozenset(a.id for a in counted)))
    monthly = plan.monthly if plan.monthly is not None else every.monthly_contribution
    return project(sum(a.balance for a in counted), monthly, plan)


# ---- Accounts


@dataclass(frozen=True)
class AccountsView:
    cash: int | None  # checking and savings with a balance
    cash_accounts: int
    banked_accounts: int  # checking and savings: not cards, and not investing accounts
    owed: Owed | None
    net: int | None  # cash minus what cards owe
    accounts: list[Account]
    imports: list[dict]
    warnings: list[dict]
    notes: list[dict]  # the checks that aren't warnings
    loans: int | None = None  # negative: what loans owe


def accounts(s: Snapshot) -> AccountsView:
    cash = [a for a in s.accounts if a.type not in (*OWED, *INVESTED)]  # investing accounts aren't cash
    banked = [a for a in cash if a.balance is not None]
    cards = [a for a in s.accounts if a.type == "credit" and a.balance is not None]
    total = sum(a.balance for a in banked) if banked else None
    o = owed(s)
    loans = [a for a in s.accounts if a.type == "loan" and a.balance is not None]
    return AccountsView(total, len(banked), len(cash), o,
                        total + sum(a.balance for a in cards) if banked and o else None, list(s.accounts), list(s.imports),
                        [c for c in s.checks if c["level"] == "warning"], [c for c in s.checks if c["level"] != "warning"],
                        sum(a.balance for a in loans) if loans else None)


# ---- Net worth


@dataclass(frozen=True)
class Holding:
    account: Account
    balance: int | None  # at the end of the period
    change: int | None  # over the period, from the balance before it or its first in it


@dataclass(frozen=True)
class NetWorth:
    months: list[str]
    assets: list[int | None]  # each month's end, of the accounts known by then
    debts: list[int | None]  # negative
    net: list[int | None]
    have: list[Holding]  # what you have: bank, savings and investing accounts
    owe: list[Holding]  # cards and loans
    missing: list[Account]  # no balance yet, so left out
    loan_paid: int  # paid toward loans in the period
    loan_interest: int  # what they charged for it, negative

    @property
    def now(self) -> int | None:
        return next((n for n in reversed(self.net) if n is not None), None)

    @property
    def change(self) -> int | None:
        """How the balances moved over the period. An account first seen partway through
        adds to net worth from then, but it was brought in, not gained."""
        moved = [h.change for h in (*self.have, *self.owe) if h.change is not None]
        return sum(moved) if moved else None


def _carried(account: Account, months: list[str]) -> list[int | None]:
    """Each month's end balance, carrying the last one known through a quiet month, and
    nothing before the account's first balance: it isn't known to have been worth anything."""
    earlier = [m for m in account.balances if m < months[0]] if months else []
    last = account.balances[max(earlier)] if earlier else None
    out = []
    for m in months:
        last = account.balances.get(m, last)
        out.append(last)
    return out


def net_worth(s: Snapshot, choice: Choice) -> NetWorth:
    months = range_months(s, choice)
    chosen = [a for a in s.accounts if choice.has(a.id)]
    known = [a for a in chosen if a.balances or a.balance is not None]
    by_month = {a.id: _carried(a, months) for a in known}

    def total(accounts: list[Account], i: int) -> int | None:
        found = [by_month[a.id][i] for a in accounts if by_month[a.id][i] is not None]
        return sum(found) if found else None

    have = [a for a in known if a.type not in OWED]
    owe = [a for a in known if a.type in OWED]
    assets = [total(have, i) for i in range(len(months))]
    debts = [total(owe, i) for i in range(len(months))]
    net = [None if a is None and d is None else (a or 0) + (d or 0) for a, d in zip(assets, debts)]

    def holding(a: Account) -> Holding:
        values = [v for v in by_month[a.id] if v is not None]
        return Holding(a, values[-1] if values else None, values[-1] - values[0] if len(values) > 1 else None)

    shown = set(months)
    loans = {a.id for a in chosen if a.type == "loan"}
    in_loans = [t for t in s.txns if t.account in loans and t.month in shown]
    return NetWorth(months, assets, debts, net,
                    sorted((holding(a) for a in have), key=lambda h: -(h.balance or 0)),
                    sorted((holding(a) for a in owe), key=lambda h: h.balance or 0),
                    [a for a in chosen if a not in known],
                    sum(t.cents for t in in_loans if t.kind == "transfer" and t.cents > 0),
                    sum(t.cents for t in in_loans if t.category == analyze.INTEREST))


# ---- Transactions


SORTS = {"date": lambda t, names: t.date, "merchant": lambda t, names: t.merchant.lower(),
         "category": lambda t, names: t.category, "amount": lambda t, names: t.cents,
         "account": lambda t, names: names.get(t.account, "")}


@dataclass(frozen=True)
class Found:
    txns: list[Tx]
    net: int  # everything listed, transfers too
    spent: int = 0  # spending, less refunds, as everywhere else
    received: int = 0  # income


def transactions(s: Snapshot, choice: Choice, query: str = "", category: str = "", kind: str = "",
                 sort: str = "date", descending: bool = True) -> Found:
    """Newest first unless asked otherwise. Ties keep the ledger's order either way. A search
    looks in notes too, and #japan finds what's tagged Japan, but not what merely mentions it."""
    q = query.lower().strip()
    tag = q[1:].strip() if q.startswith("#") else None
    found = [t for t in selected(s, choice) if (not category or t.category == category) and (not kind or t.kind == kind)
             and (not q or (any(x.lower() == tag for x in t.tags) if tag is not None
                            else q in f"{t.description} {t.merchant} {t.note}".lower()))]
    names = {a.id: a.name for a in s.accounts}
    key = SORTS[sort]
    found.sort(key=lambda t: key(t, names), reverse=descending)
    return Found(found, sum(t.cents for t in found), -sum(t.cents for t in found if t.kind in analyze.SPENDING_KINDS),
                 sum(t.cents for t in found if t.kind == "income"))


def edit_target(s: Snapshot, t: Tx) -> dict:
    """What Budget.save_edit needs to find this one transaction: n tells apart identical
    rows, counted the way analyze.edit_keys counts them."""
    if t.key:
        return {"key": t.key, "date": t.date, "account": t.account, "cents": t.whole, "description": t.description}
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
    carried: int = 0  # into this month's goal, when it rolls over: negative when last month went over
    rollover: bool = False


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
                      "over" if used > 1 else "near" if used >= .9 else "", m.carried.get(target["category"], 0),
                      bool(target.get("rollover")))


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


# ---- Budget planner

# Rules of thumb for splitting take-home pay: needs, wants, and what's kept.
RULES = {
    "50/30/20": (50, 30, 20, "Half to needs, under a third to wants, and a fifth kept. The usual starting point."),
    "60/30/10": (60, 30, 10, "For when rent or other bills take more, as they often do in an expensive city."),
    "70/20/10": (70, 20, 10, "A tighter plan, for paying down debt or a lean stretch."),
}
DEFAULT_RULE = "50/30/20"
# Spending you'd have whatever happens. Everything else counts as a want, until it's in a budget of its own.
NEEDS = frozenset({"Housing", "Groceries", "Utilities", "Transport", "Insurance", "Health", analyze.INTEREST,
                   "Education", "Taxes", "Fees"})
MOST_CUT = .25  # off what's spent in a category now: deeper than this isn't a plan anyone keeps
PLAN_LEAST = 2500  # cents a month: a category smaller than this isn't worth a budget


@dataclass(frozen=True)
class PlanLine:
    category: str
    need: bool
    average: int  # a month, over recent complete months
    fixed: int  # of that, regular bills, which a budget can't trim
    suggested: int  # a month, rounded up to a round number
    budgeted: int | None  # its budget now, a month, if it has one


@dataclass(frozen=True)
class PlanGroup:
    name: str  # Needs, Wants or Savings
    share: int  # percent of income the rule gives it
    target: int
    actual: int  # spent, or for Savings, kept
    planned: int  # with every suggested budget kept to


@dataclass(frozen=True)
class BudgetPlan:
    rule: str
    about: str
    income: int  # a month
    months: int  # complete months it's taken from
    groups: list[PlanGroup]
    lines: list[PlanLine]  # needs first, then the most spent
    unsorted: int  # spending with no category a budget can take, a month: counted as a want
    over: int  # a month the rule's savings share is still out of reach, with bills that can't be trimmed
    for_goals: int  # what savings goals with a date need a month


def _round_up(cents: float) -> int:
    """Up to a round number: $5 steps under $100, $10 steps above."""
    step = 1000 if cents >= 10000 else 500
    return int(-(-cents // step) * step)


def plan(s: Snapshot, rule: str = DEFAULT_RULE) -> BudgetPlan:
    """What a rule of thumb says to spend, beside what's spent now, and a budget for each
    category that starts from what's really spent there. When less is kept than the rule's
    savings share, only what isn't a regular bill is trimmed, wants first, and by no more than
    a quarter, so it stays doable."""
    rule = rule if rule in RULES else DEFAULT_RULE
    need_share, want_share, keep_share, about = RULES[rule]
    months = complete_budget_months(s)
    n = len(months) or 1
    income = round(sum(m.income for m in months) / n)
    totals: dict[str, int] = {}
    for m in months:
        for category, cents in m.spent.items():
            totals[category] = totals.get(category, 0) + cents
    average = {c: round(v / n) for c, v in totals.items()}
    bills: dict[str, int] = {}
    for r in active_bills(s):
        bills[r.category] = bills.get(r.category, 0) + r.per_month
    targets = {t["category"]: t for t in s.budget_targets}

    def budgeted(category: str) -> int | None:
        t = targets.get(category)
        if t is None:
            return None
        return int(t["value"]) if t["mode"] == "amount" else round(income * t["value"] / 100)

    chosen = sorted((c for c, v in average.items() if c not in analyze.NOT_BUDGETED and (v >= PLAN_LEAST or c in targets)),
                    key=lambda c: (c not in NEEDS, -average[c]))
    unsorted = sum(v for c, v in average.items() if c in analyze.NOT_BUDGETED and v > 0)
    # Categories too small for a budget still count toward their group, as they are.
    small = {need: sum(max(v, 0) for c, v in average.items() if c not in chosen and c not in analyze.NOT_BUDGETED
                       and (c in NEEDS) == need) for need in (True, False)}
    # Trim only what the rule's savings share needs: someone already keeping enough isn't asked to
    # spend less, wherever their needs and wants fall. Wants give first, then needs.
    spending = sum(max(v, 0) for v in average.values())
    short = max(0, round(income * keep_share / 100) - (income - spending))
    cuts = {}
    for need in (False, True):
        group = [c for c in chosen if (c in NEEDS) == need]
        room = sum(max(average[c], 0) - min(max(average[c], 0), bills.get(c, 0)) for c in group)
        take = min(short, room * MOST_CUT)
        cuts[need] = take / room if room else 0
        short -= take
    lines = []
    for c in chosen:
        need = c in NEEDS
        spent = max(average[c], 0)
        fixed = min(spent, bills.get(c, 0))
        lines.append(PlanLine(c, need, average[c], fixed, _round_up(fixed + (spent - fixed) * (1 - cuts[need])), budgeted(c)))
    over = round(short)
    planned = sum(line.suggested for line in lines) + unsorted + small[True] + small[False]
    groups = [
        PlanGroup("Needs", need_share, round(income * need_share / 100),
                  sum(max(average[c], 0) for c in chosen if c in NEEDS) + small[True],
                  sum(line.suggested for line in lines if line.need) + small[True]),
        PlanGroup("Wants", want_share, round(income * want_share / 100),
                  sum(max(average[c], 0) for c in chosen if c not in NEEDS) + unsorted + small[False],
                  sum(line.suggested for line in lines if not line.need) + unsorted + small[False]),
        PlanGroup("Savings", keep_share, round(income * keep_share / 100), income - spending, income - planned)]
    for_goals = sum(g.monthly or 0 for g in goals(s) if g.state not in ("reached",))
    return BudgetPlan(rule, about, income, len(months), groups, lines, unsorted, over, for_goals)


# ---- Savings goals


@dataclass(frozen=True)
class Goal:
    id: str
    name: str
    target: int
    saved: int | None  # None while the accounts it's held in have no balance
    by: str | None  # YYYY-MM-DD
    accounts: tuple[str, ...]  # ids; none means an amount kept up to date by hand
    held_in: str  # where it's kept, in words
    share: float  # of the target, 0 to 1
    left: int  # still to save
    monthly: int | None  # a month from now on, to reach it by its date
    expected: int | None  # where it would be by now, saving steadily from when it was set
    state: str  # reached, on track, behind, no date or no balance
    since: str  # when it was set


def _months_until(today: date, when: date) -> int:
    return max((when.year - today.year) * 12 + when.month - today.month, 1)


def _held(accounts: list[Account], month: str) -> int | None:
    """What these accounts held at a month's end: the last balance known by then, or the
    first known after it for an account that's newer than the goal."""
    found = []
    for a in accounts:
        before = [m for m in a.balances if m <= month]
        if before:
            found.append(a.balances[max(before)])
        elif a.balances:
            found.append(a.balances[min(a.balances)])
    return sum(found) if found else None


def goals(s: Snapshot, today: date | None = None) -> list[Goal]:
    today = today or date.today()
    by_id = s.by_id
    out = []
    for g in s.goals:
        held = [by_id[a] for a in g.get("accounts", []) if a in by_id]
        since = g.get("since") or today.isoformat()
        if g.get("accounts"):
            known = [a for a in held if a.balance is not None]
            saved = sum(a.balance for a in known) if known else None
            start = _held(known, since[:7])
            where = ", ".join(a.name for a in held) or "an account that's been removed"
        else:
            saved, start, where = g.get("saved", 0), g.get("start", g.get("saved", 0)), "an amount you keep up to date"
        target, by = g["target"], g.get("by")
        left = max(target - (saved or 0), 0)
        monthly = expected = None
        if by and left:
            monthly = -(-left // _months_until(today, date.fromisoformat(by)))  # rounded up, so it's enough
        if by and start is not None:
            begun, end = date.fromisoformat(since), date.fromisoformat(by)
            elapsed = min(max((today - begun).days, 0), (end - begun).days)
            expected = round(start + (target - start) * elapsed / max((end - begun).days, 1))
        if saved is None:
            state = "no balance"
        elif saved >= target:
            state = "reached"
        elif not by:
            state = "no date"
        else:
            state = "on track" if expected is None or saved >= expected - target // 100 else "behind"
        out.append(Goal(g["id"], g["name"], target, saved, by, tuple(g.get("accounts", [])), where,
                        min(max((saved or 0) / target, 0), 1), left, monthly, expected, state, since))
    return sorted(out, key=lambda x: (x.state == "reached", x.by or "9999", x.name.lower()))


def goal_accounts(s: Snapshot) -> list[Account]:
    """Where a goal can be kept: anything that holds money, not a card or loan."""
    return [a for a in s.accounts if a.type not in OWED]


# ---- What's coming up


AHEAD_DAYS = 30
CARD_PAYMENTS_FROM = 3  # recent payments a card's next one is guessed from


@dataclass(frozen=True)
class Upcoming:
    day: str  # YYYY-MM-DD
    merchant: str
    category: str
    cents: int  # money out is negative
    account: str  # the account's name
    from_checking: bool  # so it moves the forecast
    variable: bool  # the amount changes from time to time
    estimated: bool = False  # a card payment, guessed from recent ones


@dataclass(frozen=True)
class Forecast:
    items: list[Upcoming]  # from the day after the balance through the days ahead, in date order
    today: str
    start: str | None  # the checking balance's date, which the forecast starts from
    balance: int | None  # checking, then
    days: list[str]
    path: list[int]  # checking at each day's end
    low: int | None
    low_day: str | None
    bills: int  # due from today on, negative
    income: int  # due from today on

    @property
    def short(self) -> bool:
        return self.low is not None and self.low < 0


def _repeats(last: date, cadence: str, until: date):
    """Each day a payment is due after the last one, through until: the same days Recurring
    shows as next."""
    n = 1
    while True:
        day = analyze.due_after(last, cadence, n)
        if day > until:
            return
        yield day
        n += 1


def _debt_payments(s: Snapshot, checking: set[str], after: date, until: date) -> list[Upcoming]:
    """Paying a card or a loan isn't spending, so Recurring leaves it out, but it leaves checking
    all the same. The next is guessed from each one's recent payments: their average, a month on."""
    by_name: dict[tuple[str, str], list[Tx]] = {}
    for t in s.txns:
        if t.account not in checking or t.cents >= 0 or t.kind not in ("transfer", "estimate"):
            continue
        if analyze.is_card_payment(t.description):
            by_name.setdefault((t.merchant, "Card payment"), []).append(t)
        elif analyze.is_loan_payment(t.description):
            by_name.setdefault((t.merchant, analyze.LOAN_PAYMENT), []).append(t)
    found = []
    for (name, what), paid in by_name.items():
        recent = paid[-CARD_PAYMENTS_FROM:]
        last = date.fromisoformat(recent[-1].date)
        if (after - last).days > 45:
            continue  # no longer paid from here
        amount = round(sum(t.cents for t in recent) / len(recent))
        for day in _repeats(last, "Monthly", until):
            if day > after:
                found.append(Upcoming(day.isoformat(), name, what, amount, s.by_id[recent[-1].account].name, True,
                                      len({t.cents for t in recent}) > 1, estimated=True))
    return found


def forecast(s: Snapshot, today: date | None = None, ahead: int = AHEAD_DAYS) -> Forecast:
    """Bills, income and card payments due over the days ahead, and what they'd do to checking.

    It starts from checking's latest balance, so anything due between then and today that
    hasn't come in yet counts too."""
    today = today or date.today()
    until = today + timedelta(days=ahead)
    accounts = [a for a in s.accounts if a.type == "checking"]
    known = [a for a in accounts if a.balance is not None]
    ids = {a.id for a in accounts}
    start = max((date.fromisoformat(a.balance_as_of) for a in known if a.balance_as_of), default=None)
    after = min(start or today, today)
    items, by_id = [], s.by_id
    for r in s.recurring:
        if not r.active or r.kind not in ("expense", "income"):
            continue
        if r.account_id in by_id and by_id[r.account_id].type == "loan":
            continue  # a loan's interest is part of its payment, which is counted already
        sign = -1 if r.kind == "expense" else 1
        for day in _repeats(date.fromisoformat(r.last), r.cadence, until):
            if day > after:
                items.append(Upcoming(day.isoformat(), r.merchant, r.category, sign * r.amount, r.account, r.account_id in ids,
                                      r.variable))
    items += _debt_payments(s, ids, after, until)
    items.sort(key=lambda u: (u.day, u.cents))
    upcoming = [u for u in items if u.day >= today.isoformat()]
    days, path, low, low_day = [], [], None, None
    if known and start:
        balance, day, i = sum(a.balance for a in known), start, 0
        running = balance
        while day <= until:
            while i < len(items) and items[i].day <= day.isoformat():
                running += items[i].cents if items[i].from_checking else 0
                i += 1
            if day >= today:
                days.append(day.isoformat())
                path.append(running)
                if low is None or running < low:
                    low, low_day = running, day.isoformat()
            day += timedelta(days=1)
    return Forecast(items, today.isoformat(), start.isoformat() if start and known else None,
                    sum(a.balance for a in known) if known else None, days, path, low, low_day,
                    sum(u.cents for u in upcoming if u.cents < 0), sum(u.cents for u in upcoming if u.cents > 0))


# ---- Tags


@dataclass(frozen=True)
class Tagged:
    tag: str
    spent: int  # spending less refunds, so positive
    received: int  # income
    count: int
    first: str
    last: str
    categories: list[tuple[str, int]]  # where the spending went, most first


def tags(s: Snapshot, choice: Choice) -> list[Tagged]:
    """What each tag gathers, in the period: a trip or a project across all its categories."""
    by: dict[str, list[Tx]] = {}
    names: dict[str, str] = {}
    for t in selected(s, choice):
        for tag in t.tags:
            names.setdefault(tag.lower(), tag)
            by.setdefault(tag.lower(), []).append(t)
    out = []
    for key, found in by.items():
        spending = [t for t in found if t.kind in analyze.SPENDING_KINDS]
        where: Counter = Counter()
        for t in spending:
            where[t.category] -= t.cents
        out.append(Tagged(names[key], -sum(t.cents for t in spending), sum(t.cents for t in found if t.kind == "income"),
                          len(found), min(t.date for t in found), max(t.date for t in found), where.most_common()))
    return sorted(out, key=lambda x: (-x.spent, x.tag.lower()))


def all_tags(s: Snapshot) -> list[str]:
    """Every tag used, for suggesting as you type."""
    found: dict[str, str] = {}
    for t in s.txns:
        for tag in t.tags:
            found.setdefault(tag.lower(), tag)  # the spelling first used
    return sorted(found.values(), key=str.lower)


# ---- Year in review


TAX_LINES = (  # label, what's counted, a word on it
    ("Donations and gifts", "Gifts & Donations", "Gifts to people are in here too, so pick out the donations."),
    ("Taxes paid", "Taxes", "Payments to the IRS and state, beyond what came out of your pay."),
    ("Medical", "Health", "Doctors, pharmacies and the like."),
    ("Education", "Education", "Tuition and student loan payments filed as Education."),
    ("Loan interest", analyze.INTEREST, "Interest charged inside a loan account, like a mortgage."),
    ("Paid into retirement", analyze.CONTRIBUTED, "Contributions into retirement accounts."),
)


@dataclass(frozen=True)
class TaxLine:
    label: str
    category: str
    total: int  # positive
    count: int
    note: str


@dataclass(frozen=True)
class Change:
    category: str
    now: int
    before: int

    @property
    def gap(self) -> int:
        return self.now - self.before


@dataclass(frozen=True)
class YearReview:
    year: str
    years: list[str]  # newest first
    months: list[Month]  # the year's months that have data
    complete: bool  # all twelve months are in
    income: int
    spending: int
    before: tuple[int, int] | None  # last year's income and spending, over the months both years have
    compared: int  # how many months that is
    matched: tuple[int, int] | None  # this year's income and spending over those same months
    categories: list[Change]  # by this year's spending
    up: list[Change]  # the biggest rises on last year
    down: list[Change]
    merchants: list[tuple[str, int, int]]  # name, spent, how many
    largest: list[Tx]
    busiest: Month | None  # the month with the most spending
    quietest: Month | None
    tax: list[TaxLine]

    @property
    def kept(self) -> int:
        return self.income - self.spending

    @property
    def rate(self) -> float | None:
        return self.kept / self.income if self.income > 0 else None


def review_years(s: Snapshot) -> list[str]:
    return sorted({m[:4] for m in s.months}, reverse=True)


def year_review(s: Snapshot, year: str | None = None) -> YearReview:
    """A year at a glance, beside the same months of the year before, and what to look at
    when doing taxes. Over all accounts: the filters at the top don't apply."""
    years = review_years(s)
    year = year if year in years else (years[0] if years else str(date.today().year))
    shown = [m for m in s.months if m.startswith(year)]
    txns = [t for t in s.txns if t.month[:4] == year]
    rows = [m for m in monthly(txns, shown) if m.income or m.spending]
    prior_months = [f"{int(year) - 1}{m.month[4:]}" for m in rows]
    earlier = [t for t in s.txns if t.month in set(prior_months)]
    # Only months both years have, or a year that began partway would look like a jump.
    pairs = [(m, b) for m, b in zip(rows, monthly(earlier, prior_months)) if b.income or b.spending]
    income, spending = sum(m.income for m in rows), sum(m.spending for m in rows)
    all_now, now_by, before_by = Counter(), Counter(), Counter()
    for m in rows:
        all_now.update(m.categories)
    for m, b in pairs:
        now_by.update(m.categories)
        before_by.update(b.categories)
    categories = sorted((Change(c, v, before_by[c]) for c, v in all_now.items() if v), key=lambda c: -c.now)
    compared = [Change(c, now_by[c], before_by[c]) for c in {*now_by, *before_by} if now_by[c] or before_by[c]]
    spent = [t for t in txns if t.kind in ("expense", "estimate")]
    merchants: dict[str, list[int]] = {}
    for t in spent:
        merchants.setdefault(t.merchant, []).append(-t.cents)
    held = {a.id for a in s.accounts if a.type == "retirement"}
    tax = []
    for label, category, note in TAX_LINES:
        if category == analyze.CONTRIBUTED:
            found = [t for t in txns if t.category == category and t.account in held and t.cents > 0]
            total = sum(t.cents for t in found)
        else:
            found = [t for t in txns if t.category == category and t.kind in analyze.SPENDING_KINDS]
            total = -sum(t.cents for t in found)
        if found:
            tax.append(TaxLine(label, category, total, len(found), note))
    return YearReview(
        year, years, rows, len(rows) == 12 and not (s.partial_month or "").startswith(year),
        income, spending,
        (sum(b.income for _, b in pairs), sum(b.spending for _, b in pairs)) if pairs else None, len(pairs),
        (sum(m.income for m, _ in pairs), sum(m.spending for m, _ in pairs)) if pairs else None,
        categories,
        sorted((c for c in compared if c.gap >= 100), key=lambda c: -c.gap)[:3],  # a dollar or more
        sorted((c for c in compared if c.gap <= -100), key=lambda c: c.gap)[:3],
        sorted(((n, sum(v), len(v)) for n, v in merchants.items()), key=lambda x: -x[1])[:TOP_MERCHANTS],
        sorted(spent, key=lambda t: t.cents)[:5],
        max(rows, key=lambda m: m.spending) if rows else None,
        _quietest(rows, s.partial_month),
        tax)


def _quietest(rows: list[Month], partial: str | None) -> Month | None:
    """The month with the least spending, of the whole months: one still in progress has had
    only days to spend in, so it would nearly always win."""
    whole = [m for m in rows if m.month != partial]
    return min(whole, key=lambda m: m.spending) if len(whole) > 1 else None


def tax_rows(s: Snapshot, year: str) -> list[Tx]:
    """Every transaction behind the tax-time lines, for a spreadsheet."""
    wanted = {category for _, category, _ in TAX_LINES}
    held = {a.id for a in s.accounts if a.type == "retirement"}
    return [t for t in s.txns if t.month[:4] == year and t.category in wanted
            and (t.category != analyze.CONTRIBUTED or t.account in held)]


# ---- Alerts


NEAR_BUDGET = 0.8  # of a month's target, spent
RECENT_DAYS = 7  # how far back from the newest day a charge is news
UNUSUAL_TIMES = 3  # a charge this many times what a merchant usually takes
UNUSUAL_LEAST = 10000  # cents: smaller than this is never worth a word
NEW_MERCHANT_LEAST = 25000  # cents, for a merchant never seen before
DISMISSED_KEPT = 200


@dataclass(frozen=True)
class Alert:
    key: str  # stays the same while it's the same news, so dismissing it sticks
    level: str  # warning or info
    title: str
    detail: str
    category: str = ""  # what to list on Transactions
    query: str = ""


def _money(cents: int) -> str:
    return f"${abs(cents) / 100:,.0f}"


def _budget_alerts(s: Snapshot) -> list[Alert]:
    """Categories past most of this month's budget, while the month is in progress."""
    if not s.budget_months or not s.budget_targets:
        return []
    m = s.budget_months[-1]
    if not m.partial:
        return []
    found = []
    days_left = calendar.monthrange(int(m.month[:4]), int(m.month[5:]))[1] - int(s.end[8:])
    for t in s.budget_targets:
        line = _line(t, m)
        if line.goal <= 0 or line.used < NEAR_BUDGET:
            continue
        over = line.used > 1
        state = "over" if over else "near"
        left = f"{days_left} day{'s' if days_left != 1 else ''} left" if days_left > 0 else "the month's last day"
        found.append(Alert(
            f"budget:{line.category}:{m.month}:{state}", "warning" if over else "info",
            f"{line.category} is {_money(-line.left)} over budget" if over
            else f"{line.category} has used {round(line.used * 100)}% of its budget",
            f"{_money(line.spent)} of {_money(line.goal)} spent, with {left} in {month_name(m.month)}.",
            category=line.category))
    return found


def _unusual(s: Snapshot) -> list[Alert]:
    """A charge in the last week far bigger than that merchant usually takes, or a big one from
    a merchant never seen before."""
    since = (date.fromisoformat(s.end) - timedelta(days=RECENT_DAYS)).isoformat()
    usual: dict[str, list[int]] = {}
    found = []
    for t in sorted(s.txns, key=lambda t: t.date):  # what a merchant usually takes is from before each charge
        if t.kind != "expense":
            continue
        earlier = usual.setdefault(t.merchant, [])
        amount = -t.cents
        if t.date > since and amount >= UNUSUAL_LEAST:
            typical = sorted(earlier)[len(earlier) // 2] if earlier else None
            if typical is not None and len(earlier) >= 3 and amount >= typical * UNUSUAL_TIMES:
                found.append(Alert(f"charge:{t.date}:{t.account}:{t.cents}:{t.merchant}", "warning",
                                   f"{t.merchant} charged {_money(amount)}",
                                   f"On {day_name(t.date)}. It's usually about {_money(typical)}.", query=t.merchant))
            elif not earlier and amount >= NEW_MERCHANT_LEAST:
                found.append(Alert(f"charge:{t.date}:{t.account}:{t.cents}:{t.merchant}", "info",
                                   f"A first charge from {t.merchant}: {_money(amount)}",
                                   f"On {day_name(t.date)}. Worth a look if you don't recognize it.", query=t.merchant))
        earlier.append(amount)
    return found


def alerts(s: Snapshot, dismissed: set[str] | None = None) -> list[Alert]:
    """What's worth a word on the Overview: budgets running out, and unusual charges."""
    dismissed = dismissed or set()
    return [a for a in [*_budget_alerts(s), *_unusual(s)] if a.key not in dismissed]
