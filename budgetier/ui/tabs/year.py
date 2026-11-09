"""Year in review: a year at a glance beside the one before, and what to look at for taxes."""
from __future__ import annotations

from PySide6.QtWidgets import QPushButton, QWidget

from ... import export, views
from .. import fmt, theme, widgets
from ..charts import Chart, Series
from ..context import Context
from ..dialogs import attempt
from ..popup import Dropdown
from .overview import welcome

TAX_NOTE = ("Totals of what's categorized this way, to help gather your records. It isn't tax advice, and what counts "
            "depends on your situation, so check each one before you use it.")


def _versus(now: int, before: int | None, more_is_good: bool) -> tuple[str, str]:
    if not before:
        return "", ""
    gap = now - before
    if not gap:
        return "same as last year", ""
    share = f" ({abs(gap) / before:.0%})" if before > 0 else ""
    word = "more" if gap > 0 else "less"
    if before > 0 and abs(gap) / before < 0.05:
        return f"{fmt.money(abs(gap))} {word} than last year{share}", ""  # about the same: no color
    return f"{fmt.money(abs(gap))} {word} than last year{share}", "pos" if (gap > 0) == more_is_good else "neg"


def open_year(ctx: Context, year: str, category: str = "", query: str = "") -> None:
    """Transactions for the year being looked at, whatever period was chosen before."""
    ctx.choose_range(year)
    ctx.open_transactions(category=category, query=query)


def change_rows(ctx: Context, year: str, found: list[views.Change], rising: bool) -> QWidget:
    if not found:
        return widgets.empty("Nothing went up." if rising else "Nothing went down.")
    return widgets.hbars([(c.category, abs(c.gap), ctx.color(c.category),
                           lambda c=c: open_year(ctx, year, category=c.category)) for c in found],
                         lambda v: ("+" if rising else "-") + fmt.money(v), ctx.tokens)


def export_tax(ctx: Context, year: str) -> None:
    window = ctx.window
    path = window.ask_csv_path(f"Budgetier tax records {year}.csv")
    if not path:
        return
    names = {a.id: a.name for a in ctx.snapshot.accounts}
    ok, result = attempt(export.write_csv, path, views.tax_rows(ctx.snapshot, year), names)
    window.toast.say(f"Saved {path}" if ok else str(result))


def build(ctx: Context) -> QWidget:
    s, t = ctx.snapshot, ctx.tokens
    if not s.txns:
        return welcome(ctx)
    y = views.year_review(s, ctx.options.get("review_year"))
    year = Dropdown()
    year.setAccessibleName("Year")
    for value in y.years:
        year.addItem(value, value)
    year.setCurrentIndex(year.findData(y.year))

    def chosen(i: int) -> None:
        ctx.options["review_year"] = year.itemData(i)
        ctx.redraw()
    year.activated.connect(chosen)
    covered = "all 12 months" if y.complete else \
        f"{fmt.plural(len(y.months), 'month')} so far" if y.months else "no months yet"
    parts: list[QWidget | None] = [widgets.row(year, widgets.text(covered, "sub"), spacing=theme.SPACE[3])]
    before_income, before_spending = y.before or (None, None)
    rate = "n/a" if y.rate is None else f"{round(y.rate * 100)}%"
    over = f"over the {fmt.plural(y.compared, 'month')} both years have" if y.before and y.compared < len(y.months) else ""
    now_income, now_spending = y.matched or (0, 0)
    income_sub, income_tone = _versus(now_income, before_income, True)
    spent_sub, spent_tone = _versus(now_spending, before_spending, False)
    parts.append(widgets.tiles(
        widgets.tile("Income", fmt.money(y.income), income_sub, income_tone or "pos"),
        widgets.tile("Spending", fmt.money(y.spending), spent_sub, spent_tone),
        widgets.tile("Kept", fmt.money(y.kept), f"{rate} of income", fmt.tone(y.kept)),
        widgets.tile("Busiest month", fmt.month_name(y.busiest.month, False) if y.busiest else "n/a",
                     f"{fmt.money(y.busiest.spending)} spent" + (f", {fmt.month_name(y.quietest.month, False)} the least"
                                                                 if y.quietest else "") if y.busiest else "")))
    if over:
        parts.append(widgets.text(f"Compared with last year {over}.", "sub"))
    if y.months:
        parts.append(widgets.card(
            widgets.legend([("Income", t["income"]), ("Spending", t["spending"])]),
            Chart([m.month for m in y.months], [Series("Income", [m.income for m in y.months], t["income"]),
                                                Series("Spending", [m.spending for m in y.months], t["spending"])], t,
                  partial_month=s.partial_month),
            title=f"{y.year} month by month"))
    if y.before:
        parts.append(widgets.Grid([widgets.card(change_rows(ctx, y.year, y.up, True), title="Went up the most"),
                                   widgets.card(change_rows(ctx, y.year, y.down, False), title="Went down the most")],
                                  420, most=2, top=True))
    if y.categories:
        rows = [[widgets.Cell(c.category, icon=widgets.dot_icon(ctx.color(c.category))),
                 widgets.Cell(fmt.money(c.now), right=True, bold=True),
                 widgets.Cell(f"{fmt.money(c.now / len(y.months))}", right=True, tone="dim")] for c in y.categories]
        names = [c.category for c in y.categories]
        where = widgets.card(widgets.Table(["Category", "Spent", "A month"], rows, t, numeric={1, 2},
                                           on_row=lambda r: open_year(ctx, y.year, category=names[r])),
                             title="Where it went")
        top = widgets.card(widgets.Table(["Merchant", "Spent", "Times"],
                                         [[widgets.Cell(n, bold=True, icon=widgets.mono_icon(n, t["muted"])),
                                           widgets.Cell(fmt.money(v), right=True), widgets.Cell(f"{k:,}", right=True)]
                                          for n, v, k in y.merchants], t, numeric={1, 2},
                                         on_row=lambda r: open_year(ctx, y.year, query=y.merchants[r][0])),
                           title="Top merchants")
        parts.append(widgets.Grid([where, top], 420, most=2, top=True))
    parts.append(tax_card(ctx, y))
    return widgets.column(*parts, spacing=theme.SPACE[4])


def tax_card(ctx: Context, y: views.YearReview) -> QWidget:
    if not y.tax:
        return widgets.card(widgets.text("Nothing in this year is categorized as donations, taxes, medical, education, "
                                         "loan interest or retirement contributions.", "dim"),
                            title="For tax time", note=TAX_NOTE)
    rows = [[widgets.Cell(line.label, bold=True), widgets.Cell(fmt.money(line.total), right=True),
             widgets.Cell(f"{line.count:,}", right=True), widgets.Cell(line.note, tone="dim")] for line in y.tax]

    table = widgets.Table(["", "Total", "Rows", ""], rows, ctx.tokens, numeric={1, 2},
                          on_row=lambda r: open_year(ctx, y.year, category=y.tax[r].category))
    save = QPushButton("Export these rows")
    save.setProperty("kind", "small")
    save.clicked.connect(lambda _=False: export_tax(ctx, y.year))
    return widgets.card(table, widgets.row(save) if ctx.window is not None else None, title="For tax time", note=TAX_NOTE)
