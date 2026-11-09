"""Recurring: bills, subscriptions and regular income, found over all history."""
from __future__ import annotations

from datetime import date

from PySide6.QtWidgets import QWidget

from ... import views
from .. import fmt, theme, widgets
from ..charts import Chart, Series
from ..context import Context

HEADERS = ["Name", "Category", "Every", "Amount", "Monthly", "Change", "Last", "Next", "Account"]


def _change(r: views.Recurring) -> widgets.Cell:
    if not r.price_change:
        return widgets.Cell("")
    rise = r.price_change > 0
    word = "▲ up" if rise else "▼ down"
    return widgets.Cell(f"{word} {fmt.cents(abs(r.price_change))}", tone="up" if rise == (r.kind == "expense") else "down")


def table(ctx: Context, found: list[views.Recurring]) -> QWidget:
    if not found:
        return widgets.empty("None found.")
    money_tone = {"income": "pos"}
    rows = [[widgets.Cell(r.merchant + ("  ·  stopped" if not r.active else ""), bold=True,
                          icon=widgets.mono_icon(r.merchant, ctx.color(r.category))),
             widgets.Cell(r.category, icon=widgets.dot_icon(ctx.color(r.category))),
             widgets.Cell(r.cadence, tone="dim"),
             widgets.Cell(("~" if r.variable else "") + fmt.cents(r.amount), right=True, tone=money_tone.get(r.kind, "")),
             widgets.Cell(fmt.cents(r.per_month), right=True, tone=money_tone.get(r.kind, "")),
             _change(r),
             widgets.Cell(fmt.day_name(r.last), tone="dim"),
             widgets.Cell(fmt.day_name(r.next) if r.active else "", tone="dim"),
             widgets.Cell(r.account, tone="dim")] for r in found]
    return widgets.Table(HEADERS, rows, ctx.tokens, on_row=lambda i: ctx.open_transactions(query=found[i].merchant),
                         numeric={3, 4})


def _short_day(day: str) -> str:
    when = date.fromisoformat(day)
    return f"{when:%b} {when.day}"


def coming_up(ctx: Context, f: views.Forecast) -> QWidget | None:
    """The next 30 days: what's due, and what it does to checking."""
    if not f.items:
        return None
    t = ctx.tokens
    parts: list[QWidget | None] = []
    if f.path:
        parts.append(widgets.tiles(
            widgets.tile("Checking now", fmt.money(f.balance), f"as of {fmt.day_name(f.start)}"),
            widgets.tile("Bills due", fmt.money(-f.bills), f"next {views.AHEAD_DAYS} days, cards too"),
            widgets.tile("Income expected", fmt.money(f.income), f"next {views.AHEAD_DAYS} days", "pos"),
            widgets.tile("Lowest point", fmt.money(f.low), f"around {fmt.day_name(f.low_day)}", "neg" if f.short else "")))
        labels = [_short_day(d) if i % 7 == 0 else "" for i, d in enumerate(f.days)]
        parts.append(Chart(f.days, [Series("Checking", f.path, t["accent"])], t, kind="lines", labels=labels,
                           titles=[fmt.day_name(d) for d in f.days]))
    rows = []
    for u in f.items:
        late = u.day < f.today
        note = ("estimated from recent payments" if u.estimated else "due, not in yet" if late
                else "amount varies" if u.variable else "")
        rows.append([widgets.Cell(fmt.day_name(u.day), tone="dim"),
                     widgets.Cell(u.merchant, bold=True, icon=widgets.mono_icon(u.merchant, ctx.color(u.category))),
                     widgets.Cell(fmt.cents(u.cents), right=True,
                                  tone="pos" if u.cents > 0 else ""),
                     widgets.Cell(u.account, tone="dim"), widgets.Cell(note, tone="dim")])
    parts.append(widgets.Table(["Due", "Name", "Amount", "Account", "Note"], rows, t, numeric={2},
                               on_row=lambda i: ctx.open_transactions(query=f.items[i].merchant)))
    note = (f"Starting from checking's balance on {fmt.day_name(f.start)}, with each bill, paycheck and card payment as it "
            "comes due. Bills on a card leave checking when the card is paid, so only its payment moves the line, and a loan's "
            "payment is guessed from recent ones."
            if f.path else "Set your checking balance on the Accounts tab to see what these do to it.")
    return widgets.card(*parts, title=f"Next {views.AHEAD_DAYS} days", note=note)


def build(ctx: Context) -> QWidget:
    stopped = ctx.options.get("recurring_all", False)
    r = views.recurring(ctx.snapshot, stopped)
    figures = widgets.tiles(
        widgets.tile("Recurring bills", fmt.money(r.bills) + "/mo", fmt.money(r.bills * 12) + " a year"),
        widgets.tile("Subscriptions", fmt.money(r.subscriptions) + "/mo", f"{r.subscription_count} active"),
        widgets.tile("Regular income", fmt.money(r.income) + "/mo", fmt.plural(r.income_count, "source"), "pos"))
    toggle = widgets.check("Include stopped payments", stopped, ctx.toggle("recurring_all"))
    bills = widgets.card(toggle, table(ctx, r.expenses), title="Bills and subscriptions",
                         note="~ means the amount varies. Found from the full history, so the period filter doesn't apply here.")
    income = widgets.card(table(ctx, r.incomes), title="Regular income")
    return widgets.column(figures, coming_up(ctx, views.forecast(ctx.snapshot)), bills, income,
                          spacing=theme.SPACE[4])
