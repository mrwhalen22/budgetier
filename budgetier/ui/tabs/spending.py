"""Spending: each category by month, as a chart and as a table."""
from __future__ import annotations

import math

from PySide6.QtGui import QColor
from PySide6.QtWidgets import QWidget

from ... import views
from .. import fmt, theme, widgets
from ..charts import PICK, Chart, Series
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
                               stacked=True, height=300, partial_month=s.partial_month, on_pick=ctx.choose_range),
                         title="Spending by category", note=PICK)
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
    return widgets.column(chart, heat, tagged(ctx), spacing=theme.SPACE[4])


def tagged(ctx: Context) -> QWidget | None:
    """What each tag cost in the period, across every category it touched."""
    found = views.tags(ctx.snapshot, ctx.choice)
    if not found:
        return None
    rows = [[widgets.Cell(f"#{g.tag}", bold=True),
             widgets.Cell(", ".join(c for c, _ in g.categories[:3]) + (" and more" if len(g.categories) > 3 else ""), tone="dim"),
             widgets.Cell(f"{fmt.month_name(g.first[:7])} to {fmt.month_name(g.last[:7])}"
                          if g.first[:7] != g.last[:7] else fmt.month_name(g.first[:7]), tone="dim"),
             widgets.Cell(f"{g.count:,}", right=True),
             widgets.Cell(fmt.money(g.spent), right=True, bold=True)] for g in found]
    table = widgets.Table(["Tag", "Mostly", "When", "Rows", "Spent"], rows, ctx.tokens, numeric={3, 4},
                          on_row=lambda r: ctx.open_transactions(query=f"#{found[r].tag}"))
    return widgets.card(table, title="Tags", note="Add tags to transactions with Add note. Select one to list what it gathers.")
