"""The bottom of the Spending tab: the merchants spent with most, and the biggest purchases."""
from __future__ import annotations

from PySide6.QtWidgets import QWidget

from ... import views
from .. import fmt, widgets
from ..context import Context


def sections(ctx: Context) -> QWidget:
    s, t = ctx.snapshot, ctx.tokens
    every = ctx.options.get("largest_all", False)
    found = views.largest(s, ctx.choice, every)
    if found.merchants:
        bars = widgets.hbars([(name, total, None, lambda name=name: ctx.open_transactions(query=name))
                              for name, total, _ in found.merchants], fmt.money, t)
    else:
        bars = widgets.empty("Nothing in this period.")
    merchants = widgets.card(bars, title="Top merchants", note="By total spent.")
    leaving = "" if every or not found.hidden else ", leaving out regular bills"
    toggle = widgets.check("Include regular bills", every, ctx.toggle("largest_all"))
    rows = [[widgets.Cell(x.merchant, icon=widgets.mono_icon(x.merchant, ctx.color(x.category)), tip=x.description, bold=True),
             widgets.Cell(fmt.day_name(x.date), tone="dim"),
             widgets.Cell(fmt.cents(-x.cents), right=True)] for x in found.expenses]
    listing = (widgets.Table(["Merchant", "Date", "Amount"], rows, t, numeric={2},
                             on_row=lambda r: ctx.edit.categorize(found.expenses[r])) if rows
               else widgets.empty("Nothing else in this period."))
    biggest = widgets.card(toggle, listing, title="Biggest purchases",
                           note=f"The biggest from each merchant in this period{leaving}. Select one to change it.")
    return widgets.Grid([merchants, biggest], 340, most=2)
