"""Spending: each category by month, as a chart and as a table."""
from __future__ import annotations

import math

from PySide6.QtGui import QColor
from PySide6.QtWidgets import QWidget

from ... import views
from .. import fmt, theme, widgets
from ..charts import Chart, Series
from ..context import Context
from .overview import welcome


def build(ctx: Context) -> QWidget:
    s, t = ctx.snapshot, ctx.tokens
    if not s.txns:
        return welcome(ctx)
    sp = views.spending(s, ctx.choice)
    colors = {name: (t["other"] if name == "Other" else ctx.color(name)) for name, _ in sp.series}
    chart = widgets.card(widgets.legend([(name, colors[name]) for name, _ in sp.series]),
                         Chart(sp.months, [Series(name, values, colors[name]) for name, values in reversed(sp.series)], t,
                               stacked=True, height=300, partial_month=s.partial_month),
                         title="Spending by category")
    longer = "; showing the latest 12 months, totals cover the full period" if len(sp.months) > 12 else ""
    accent = QColor(t["accent"])
    rows, names = [], [c for c, _ in sp.categories]
    for category, total in sp.categories:
        cells = [widgets.Cell(category, icon=widgets.dot_icon(ctx.color(category)))]
        for value in sp.heat[category]:
            shade = QColor(accent)
            shade.setAlphaF(math.sqrt(max(value, 0) / sp.heat_peak) * .30)
            cells.append(widgets.Cell(fmt.short(value) if value else "", right=True, tone=fmt.gain(-value), background=shade))
        cells.append(widgets.Cell(fmt.money(total), right=True, tone=fmt.gain(-total), bold=True))
        rows.append(cells)
    headers = ["Category", *(fmt.month_name(m, False) for m in sp.heat_months), "Total"]
    table = widgets.Table(headers, rows, t, on_cell=lambda r, _c: ctx.open_transactions(category=names[r]),
                          numeric=set(range(1, len(headers))))
    heat = widgets.card(table, title="Category by month",
                        note=f"Darker means more spent{longer}. Refunds are netted out.")
    return widgets.column(chart, heat, spacing=theme.SPACE[4])
