"""The budget guide: what a rule of thumb like 50/30/20 says to spend, beside what you spend,
and budgets for each category suggested from your own recent spending.

It's a starting point, not advice, and it says so. The rule chosen is kept in settings.json.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QCheckBox, QFrame, QGridLayout, QLineEdit, QPushButton, QScrollArea, QVBoxLayout, QWidget

from .. import views
from ..parse import parse_money
from . import fmt, settings, theme, widgets
from .context import Context
from .dialogs import Dialog, attempt, busy
from .popup import Dropdown

RULE = "budget_rule"  # in settings.json
TALL = 360  # pixels of suggestions before they scroll


def chosen_rule(ctx: Context) -> str:
    home = getattr(getattr(ctx.window, "budget", None), "home", None)
    saved = settings.load(home).get(RULE) if home else None
    return saved if saved in views.RULES else views.DEFAULT_RULE


def _compare(group: views.PlanGroup) -> widgets.Cell:
    gap = group.actual - group.target
    if group.name == "Savings":
        return widgets.Cell(f"{fmt.money(abs(gap))} {'more' if gap >= 0 else 'short'}", right=True,
                            tone="pos" if gap >= 0 else "neg")
    return widgets.Cell(f"{fmt.money(abs(gap))} {'over' if gap > 0 else 'under'}", right=True,
                        tone="neg" if gap > 0 else "pos")


def guide(ctx: Context) -> QWidget:
    """The rule's split of your income beside yours, and the way to suggested budgets."""
    p = views.plan(ctx.snapshot, chosen_rule(ctx))
    title = "Budget guide"
    if p.income <= 0:
        return widgets.card(title=title, note="The guide works from your income, and there's none yet in a complete "
                                              "month. Add your checking account's history so paychecks are counted.")
    box = Dropdown()
    box.setAccessibleName("Rule")
    for name in views.RULES:
        box.addItem(name, name)
    box.setCurrentIndex(box.findData(p.rule))

    def pick(i: int) -> None:
        window = ctx.window
        if window is not None:
            settings.save(window.budget.home, **{RULE: box.itemData(i)})
        ctx.redraw()
    box.activated.connect(pick)
    rows = [[widgets.Cell(f"{g.name}, {g.share}%", bold=True), widgets.Cell(fmt.money(g.target), right=True),
             widgets.Cell(fmt.money(g.actual), right=True), _compare(g)] for g in p.groups]
    table = widgets.Table(["", "The rule says", "You spend or keep", "Difference"], rows, ctx.tokens, numeric={1, 2, 3},
                          stretch=0)
    suggest = QPushButton("Suggest budgets")
    suggest.setProperty("kind", "primary" if not ctx.snapshot.budget_targets else "")
    suggest.clicked.connect(lambda _=False: suggestions(ctx))
    words = [f"{p.about} From your income of {fmt.money(p.income)} a month, averaged over "
             f"{fmt.plural(p.months, 'complete month')}."]
    if p.for_goals:
        words.append(f"Your savings goals need {fmt.money(p.for_goals)} a month to be met on time.")
    words.append("A rule of thumb to start from, not financial advice.")
    return widgets.card(widgets.row(box, suggest if ctx.window is not None else None), table,
                        widgets.text(" ".join(words), "dim"), title=title,
                        note="Needs are what you'd pay whatever happens, like housing, groceries and bills. Everything "
                             "else is a want. Savings is what's left.")


def suggestions(ctx: Context) -> Dialog:
    """A budget for each category, from what's spent there lately. Tick the ones to set."""
    window, s = ctx.window, ctx.snapshot
    p = views.plan(s, chosen_rule(ctx))
    keep = next(g for g in p.groups if g.name == "Savings")
    trimmed = any(line.suggested < line.average for line in p.lines)
    lead = (f"Each starts from what you've spent a month lately, rounded up. You already keep the {keep.share}% the "
            f"{p.rule} rule asks for, so nothing is trimmed." if not trimmed else
            f"To keep the {keep.share}% the {p.rule} rule asks for, these trim what isn't a regular bill, wants first, "
            "by up to a quarter. Regular bills stay as they are.")
    dialog = Dialog(window, "Suggested budgets", lead)
    grid_box = QWidget()
    grid = QGridLayout(grid_box)
    grid.setContentsMargins(0, 0, 0, 0)
    grid.setHorizontalSpacing(theme.SPACE[3])
    grid.setVerticalSpacing(theme.SPACE[2])
    for col, words in enumerate(("Category", "Spent a month", "Budget a month", "")):
        grid.addWidget(widgets.text(words, "field"), 0, col, Qt.AlignRight if col in (1,) else Qt.AlignLeft)
    picks: list[tuple[views.PlanLine, QCheckBox, QLineEdit]] = []
    for row, line in enumerate(p.lines, 1):
        tick = QCheckBox(line.category)
        tick.setChecked(line.budgeted is None)
        amount = QLineEdit(f"{line.suggested / 100:.0f}")
        amount.setAccessibleName(f"{line.category} budget")
        amount.setFixedWidth(110)
        note = (f"now {fmt.money(line.budgeted)}" if line.budgeted is not None
                else f"{fmt.money(line.fixed)} of it regular bills" if line.fixed >= line.average * .5 and line.fixed else "")
        grid.addWidget(tick, row, 0)
        grid.addWidget(widgets.text(fmt.money(line.average), wrap=False), row, 1, Qt.AlignRight)
        grid.addWidget(amount, row, 2)
        grid.addWidget(widgets.text(note, "dim", wrap=False), row, 3)
        picks.append((line, tick, amount))
    grid.setColumnStretch(3, 1)
    if len(p.lines) > 8:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setWidget(grid_box)
        scroll.setMaximumHeight(TALL)
        scroll.setMinimumHeight(TALL)
        dialog.body.addWidget(scroll)
    else:
        dialog.body.addWidget(grid_box)
    outcome = widgets.text("", "panel-text")
    panel = QFrame()
    panel.setProperty("kind", "panel")
    inside = QVBoxLayout(panel)
    inside.setContentsMargins(*(theme.SPACE[3],) * 4)
    inside.addWidget(outcome)
    dialog.body.addWidget(panel)
    dialog.picks = picks  # for tests

    def chosen() -> dict[str, str]:
        return {line.category: amount.text() for line, tick, amount in picks if tick.isChecked()}

    def refresh() -> None:
        planned = keep.actual
        for line, tick, amount in picks:
            if tick.isChecked():
                cents = parse_money(amount.text())
                if cents is not None:
                    planned += line.average - cents
        share = round(planned / p.income * 100) if p.income else 0
        words = (f"Spending to these budgets, you'd keep about {fmt.money(planned)} a month, {share}% of your income. "
                 f"The rule asks for {keep.share}%.")
        if planned < keep.target:
            words += f" That's {fmt.money(keep.target - planned)} short of it" + (
                ": what's left is mostly regular bills, so a rule with more room for needs may fit better." if p.over else ".")
        outcome.setText(words)
        n = len(chosen())
        if dialog.main is not None:
            dialog.main.setText(f"Set {fmt.plural(n, 'budget')}" if n else "Set budgets")
            dialog.main.setEnabled(bool(n))

    def save() -> None:
        amounts = chosen()

        def work() -> None:
            ok, result = attempt(window.budget.undoable, window.budget.save_budgets, amounts)
            if not ok:
                dialog.show_error(str(result))
                return
            dialog.dismiss()
            window.changed(f"{fmt.plural(len(amounts), 'budget')} set.", undo=True)
        busy(dialog.main, "Saving...", work)

    dialog.set_buttons([("Cancel", dialog.dismiss, ""), ("Set budgets", save, "primary")])
    for _, tick, amount in picks:
        tick.toggled.connect(lambda _on: refresh())
        amount.textChanged.connect(lambda _text: refresh())
    refresh()
    dialog.setMinimumWidth(600)
    dialog.open()
    return dialog
