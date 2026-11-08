"""Recurring: bills, subscriptions and regular income, found over all history."""
from __future__ import annotations

from PySide6.QtWidgets import QWidget

from ... import views
from .. import fmt, theme, widgets
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


def build(ctx: Context) -> QWidget:
    stopped = ctx.options.get("recurring_all", False)
    r = views.recurring(ctx.snapshot, stopped)
    figures = widgets.tiles(
        widgets.tile("Recurring bills", fmt.money(r.bills) + "/mo", fmt.money(r.bills * 12) + " a year"),
        widgets.tile("Subscriptions", fmt.money(r.subscriptions) + "/mo", f"{r.subscription_count} active"),
        widgets.tile("Regular income", fmt.money(r.income) + "/mo", fmt.plural(r.income_count, "source"), "pos"))
    toggle = widgets.check("Include stopped payments", stopped, ctx.toggle("recurring_all"))
    bills = widgets.card(table(ctx, r.expenses), title="Bills and subscriptions",
                         note="~ means the amount varies. Found from the full history, so the period filter doesn't apply here.")
    income = widgets.card(table(ctx, r.incomes), title="Regular income")
    return widgets.column(figures, toggle, bills, income, spacing=theme.SPACE[4])
