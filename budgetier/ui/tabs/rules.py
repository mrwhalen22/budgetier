"""Rules: merchants that still need a category, and your own rules."""
from __future__ import annotations

from PySide6.QtWidgets import QPushButton, QWidget

from ... import analyze, views
from .. import fmt, theme, widgets
from ..context import Context
from ..editing import code_font


def _button(label: str, run, kind: str = "small") -> QPushButton:
    button = QPushButton(label)
    button.setProperty("kind", kind)
    button.clicked.connect(lambda _=False: run())
    return button


def _actions(*buttons: QPushButton) -> QWidget:
    box = widgets.row(*buttons, spacing=theme.SPACE[1])
    box.layout().setContentsMargins(theme.SPACE[1], 0, theme.SPACE[1], 0)
    return box


def needing(ctx: Context) -> QWidget:
    open_ = views.uncategorized(ctx.snapshot)
    if not open_:
        return widgets.empty("Everything has a category.")
    color = ctx.color(analyze.UNCATEGORIZED)
    rows = [[widgets.Cell(u.merchant, icon=widgets.mono_icon(u.merchant, color), bold=True),
             widgets.Cell(u.description, tone="dim", tip=u.description),
             widgets.Cell(f"{u.count:,}", right=True),
             widgets.Cell(fmt.cents(u.total), right=True, tone=fmt.gain(u.total)),
             widgets.Cell("")] for u in open_]
    table = widgets.Table(["Merchant", "The bank's description", "Transactions", "Total", ""], rows, ctx.tokens,
                          on_row=lambda r: ctx.edit.start_queue(open_[r].merchant), numeric={2, 3})
    for r, u in enumerate(open_):
        table.setCellWidget(r, 4, _actions(_button("Categorize", lambda m=u.merchant: ctx.edit.start_queue(m))))
    table.resizeColumnsToContents()
    return table


def yours(ctx: Context) -> QWidget:
    found = ctx.snapshot.rules
    if not found:
        return widgets.empty("No rules yet.")
    rows = [[widgets.Cell(r["text"] + ("  ·  not valid" if r["broken"] else ""), tip=r["text"],
                          tone="neg" if r["broken"] else ""),
             widgets.Cell(r["merchant"] or "unchanged", tone="" if r["merchant"] else "dim"),
             widgets.Cell(r["category"], icon=widgets.dot_icon(ctx.color(r["category"]))),
             widgets.Cell(f"{r['count']:,}", right=True),
             widgets.Cell("")] for r in found]
    table = widgets.Table(["Description contains", "Shows as", "Category", "Matches", ""], rows, ctx.tokens,
                          on_row=lambda i: ctx.edit.edit_rule(found[i]), numeric={3})
    for i, r in enumerate(found):
        if r["advanced"]:
            table.item(i, 0).setFont(code_font())
        table.setCellWidget(i, 4, _actions(_button("Edit", lambda r=r: ctx.edit.edit_rule(r))))
    table.resizeColumnsToContents()
    return table


def build(ctx: Context) -> QWidget:
    open_ = views.uncategorized(ctx.snapshot)
    total = abs(sum(u.total for u in open_))
    figures = widgets.tiles(
        widgets.tile("To categorize", f"{len(open_)}",
                     f"{'merchant' if len(open_) == 1 else 'merchants'}, {fmt.cents(total)} in total"),
        widgets.tile("Your rules", f"{len(ctx.snapshot.rules)}", "applied across all history"))
    add = _button("Add rule", ctx.edit.new_rule, "primary")
    return widgets.column(
        figures,
        widgets.card(needing(ctx), title="Needs a category",
                     note="Categorize one and you'll move through the rest. To change a single transaction, select its row "
                          "on the Transactions tab."),
        widgets.card(widgets.row(add), yours(ctx), title="Your rules",
                     note="Rules run before anything built in. If two match, the higher one wins."),
        spacing=theme.SPACE[4])
