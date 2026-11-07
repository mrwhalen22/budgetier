"""Savings: what was kept each month, in total, and the accounts' balances."""
from __future__ import annotations

from PySide6.QtWidgets import QWidget

from ... import views
from .. import fmt, theme, widgets
from ..charts import Chart, Series
from ..context import Context
from .overview import welcome


def build(ctx: Context) -> QWidget:
    s, t = ctx.snapshot, ctx.tokens
    if not s.txns:
        return welcome()
    v = views.savings(s, ctx.choice)
    rate = "n/a" if v.rate is None else f"{round(v.rate * 100)}%"
    figures = widgets.tiles(
        widgets.tile("Kept this period", fmt.money(v.kept),
                     "income minus spending" + (f", from {fmt.month_name(v.kept_from)}" if v.kept_from else ""),
                     fmt.tone(v.kept)),
        widgets.tile("Savings rate", rate, "complete months" if v.averaged else "", fmt.tone(v.rate or 0)),
        widgets.tile("Moved to savings and investing", fmt.money(v.moved), "net of withdrawals", fmt.tone(v.moved)),
        widgets.tile("Savings balance", fmt.money(v.balance), "latest known balance", fmt.tone(v.balance))
        if v.balance is not None else None)
    early = " Months before your checking history are left out." if v.kept_from else ""
    kept = widgets.card(Chart(v.months, [Series("Kept", v.nets, color_for=lambda n: t["bad"] if n < 0 else t["income"])], t,
                              partial_month=s.partial_month),
                        title="Kept each month", note=f"Income minus spending. Red months spent more than came in.{early}")
    total_color = t["bad"] if v.running and v.running[-1] < 0 else t["income"]
    running = widgets.card(Chart(v.months, [Series("Running total", v.running, total_color)], t, kind="lines"),
                           title="Running total kept")
    parts = [figures, widgets.Grid([kept, running], 340, most=2)]
    if v.balance_lines:
        colors = [t[f"c{i}"] for i in range(len(v.balance_lines))]
        parts.append(widgets.card(
            widgets.legend([(name, colors[i]) for i, (name, _) in enumerate(v.balance_lines)]),
            Chart(v.balance_months, [Series(name, values, colors[i]) for i, (name, values) in enumerate(v.balance_lines)], t,
                  kind="lines"),
            title="Account balances",
            note="Month-end balances. Exports supply some; the rest are calculated from a balance you entered."))
    return widgets.column(*parts, spacing=theme.SPACE[4])
