"""Savings: what you keep each month, the goals you're saving toward, and your net worth."""
from __future__ import annotations

from PySide6.QtWidgets import QWidget

from ... import views
from .. import fmt, theme, widgets
from ..charts import PICK, Chart, Series
from ..context import Context
from . import networth
from .budgets import goals_card
from .overview import welcome


def build(ctx: Context) -> QWidget:
    s, t = ctx.snapshot, ctx.tokens
    if not s.txns and not s.accounts:
        return welcome(ctx)
    v = views.savings(s, ctx.choice)
    worth = views.net_worth(s, ctx.choice)
    rate = "n/a" if v.rate is None else f"{round(v.rate * 100)}%"
    kept_sub = f"{fmt.money(v.kept)} kept this period" + (f", from {fmt.month_name(v.kept_from)}" if v.kept_from else "")
    figures = widgets.tiles(
        widgets.tile("Savings rate", rate, kept_sub, fmt.tone(v.rate or 0)),
        widgets.tile("Moved to savings and investing", fmt.money(v.moved), "net of withdrawals", fmt.tone(v.moved)),
        *networth.figures(ctx, worth))
    early = " Months before your checking history are left out." if v.kept_from else ""
    kept = widgets.card(Chart(v.months, [Series("Kept", v.nets, color_for=lambda n: t["bad"] if n < 0 else t["income"])], t,
                              partial_month=s.partial_month, on_pick=ctx.choose_range),
                        title="Kept each month",
                        note=f"Income minus spending. Red months spent more than came in.{early} {PICK}")
    total_color = t["bad"] if v.running and v.running[-1] < 0 else t["income"]
    running = widgets.card(Chart(v.months, [Series("Running total", v.running, total_color)], t, kind="lines"),
                           title="Running total kept")
    parts = [figures, networth.missing(ctx, worth), goals_card(ctx),
             widgets.Grid([kept, running], 340, most=2), *networth.sections(ctx, worth)]
    return widgets.column(*parts, spacing=theme.SPACE[4])
