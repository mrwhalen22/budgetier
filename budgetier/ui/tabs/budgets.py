"""Budgets: a monthly target per category, what's left this month, and recent months."""
from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QFrame, QGridLayout, QLineEdit, QPushButton, QVBoxLayout, QWidget

from ... import views
from .. import fmt, theme, widgets
from ..context import Context
from ..dialogs import Dialog, attempt, busy, confirm
from ..importing import field
from ..popup import Dropdown

MODES = (("amount", "Dollar amount"), ("percent", "Percent of income"))


def number(value: float) -> str:
    """A percent as typed: 10, not 10.0."""
    return f"{value:g}"


def goal_text(line: views.BudgetLine) -> str:
    return f"{number(line.value)}% of income" if line.mode == "percent" else f"{fmt.money(line.value)} a month"


def _button(label: str, run, kind: str = "small") -> QPushButton:
    button = QPushButton(label)
    button.setProperty("kind", kind)
    button.clicked.connect(lambda _=False: run())
    return button


class Meter(QWidget):
    """How much of a target is used: green, amber near it, red over it."""

    def __init__(self, used: float, state: str, tokens: dict[str, str]):
        super().__init__()
        self.used, self.tokens = used, tokens
        self.color = tokens["spending" if state == "over" else "c3" if state == "near" else "income"]
        self.setFixedHeight(8)
        self.setAccessibleName(f"{round(used * 100)}% used")

    def paintEvent(self, _event):  # noqa: N802 - Qt's name
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        rect = QRectF(self.rect())
        painter.setBrush(QColor(self.tokens["line"]))
        painter.drawRoundedRect(rect, 4, 4)
        share = min(max(self.used, 0), 1)
        if share:
            painter.setBrush(QColor(self.color))
            painter.drawRoundedRect(QRectF(0, 0, max(rect.width() * share, 8), rect.height()), 4, 4)


def line_row(ctx: Context, line: views.BudgetLine) -> QWidget:
    box = QFrame()
    box.setProperty("kind", "budget")
    grid = QGridLayout(box)
    grid.setContentsMargins(0, theme.SPACE[3], 0, theme.SPACE[3])
    grid.setHorizontalSpacing(theme.SPACE[4])
    grid.setVerticalSpacing(theme.SPACE[2])
    grid.addWidget(widgets.column(widgets.chip(line.category, ctx.color(line.category)), widgets.text(goal_text(line), "s"),
                                  spacing=2), 0, 0)
    left = widgets.text(f"{fmt.money(abs(line.left))} {'over' if line.left < 0 else 'left'}", "strong")
    left.setProperty("tone", "neg" if line.left < 0 else "pos")
    left.setAlignment(Qt.AlignRight)
    used = widgets.text(f"{fmt.money(line.spent)} of {fmt.money(line.goal)}", "s")
    used.setAlignment(Qt.AlignRight)
    grid.addWidget(widgets.column(left, used, spacing=2), 0, 1)
    actions = widgets.row(_button("Edit", lambda: budget_form(ctx, line)),
                          _button("Remove", lambda: remove_budget(ctx, line.category), "small-danger"), spacing=theme.SPACE[1])
    grid.addWidget(actions, 0, 2)
    grid.addWidget(Meter(line.used, line.state, ctx.tokens), 1, 0, 1, 3)
    grid.setColumnStretch(0, 1)
    return box


def history(ctx: Context, b: views.BudgetsView) -> QWidget:
    rows = []
    for t in ctx.snapshot.budget_targets:
        cells = [widgets.Cell(t["category"], icon=widgets.dot_icon(ctx.color(t["category"])))]
        for spent, missed in b.history_lines[t["category"]]:
            cells.append(widgets.Cell(fmt.short(spent) if spent else "", right=True, tone="neg" if missed else ""))
        rows.append(cells)
    headers = ["Category", *(fmt.month_name(m.month, False) for m in b.history)]
    return widgets.card(widgets.Table(headers, rows, ctx.tokens, numeric=set(range(1, len(headers))), stretch=0),
                        title="Recent months",
                        note="What you spent in each category. Amounts in red went over that month's target.")


def build(ctx: Context) -> QWidget:
    s = ctx.snapshot
    add = _button("Add budget", lambda: budget_form(ctx), "primary")
    if not s.budget_targets:
        return widgets.card(widgets.row(add), title="Set your first budget",
                            note="Choose a category and give it a monthly target: a dollar amount, or a percent of your "
                                 "income. Budgetier shows what's left each month.")
    b = views.budgets(s, ctx.options.get("budget_month"))
    if b.month is None:
        return widgets.card(widgets.row(add), title="Budgets", note="Budgets show once there are transactions.")
    m = b.month
    month = Dropdown()
    month.setAccessibleName("Month")
    for value in b.months:
        month.addItem(fmt.month_name(value), value)
    month.setCurrentIndex(month.findData(m.month))

    def chosen(i: int) -> None:
        ctx.options["budget_month"] = month.itemData(i)
        ctx.redraw()
    month.activated.connect(chosen)
    head = widgets.row(month, add, stretch_last=True)
    head.layout().insertStretch(1, 1)
    figures = widgets.tiles(
        widgets.tile("Budgeted", fmt.money(b.goal), f"{round(b.goal / m.base * 100)}% of income" if m.base > 0 else ""),
        widgets.tile("Spent on budgets", fmt.money(b.spent)),
        widgets.tile("Over budget" if b.left < 0 else "Left to spend", fmt.money(abs(b.left)),
                     "so far this month" if m.partial else "", "neg" if b.left < 0 else "pos"),
        widgets.tile("Not budgeted", fmt.money(b.other), "other spending this month"))
    if m.partial:
        note = f"Month in progress, data through {fmt.day_name(s.end)}."
        if b.uses_percent:
            note += f" Percent targets use your recent income, {fmt.money(m.base)} a month, until the month is complete."
    else:
        note = f"Percent targets use this month's income of {fmt.money(m.base)}." if b.uses_percent else ""
    lines = widgets.card(*(line_row(ctx, line) for line in b.lines), title=fmt.month_name(m.month), note=note)
    return widgets.column(head, figures, lines, history(ctx, b), spacing=theme.SPACE[4])


# ---- the form


def budget_form(ctx: Context, line: views.BudgetLine | None = None) -> Dialog | None:
    window = ctx.window
    names = [line.category] if line else views.budget_choices(ctx.snapshot)
    if not names:
        window.toast.say("Every category already has a budget.")
        return None
    dialog = Dialog(window, "Edit budget" if line else "Add budget", "Targets apply to every month, including past ones.")
    category = Dropdown(dot_for=ctx.color)
    category.setAccessibleName("Category")
    for name in names:
        category.addItem(name, name)
    category.setEnabled(line is None)
    mode = Dropdown()
    mode.setAccessibleName("Target type")
    for value, label in MODES:
        mode.addItem(label, value)
    mode.setCurrentIndex(mode.findData(line.mode if line else "amount"))
    value = QLineEdit("" if line is None else number(line.value / 100) if line.mode == "amount" else number(line.value))
    value_label = widgets.text("Dollars a month", "field")
    value_box = widgets.column(value_label, value, spacing=theme.SPACE[1])
    grid = QGridLayout()
    grid.setHorizontalSpacing(theme.SPACE[3])
    grid.addWidget(field("Category", category), 0, 0, 1, 2)
    grid.addWidget(field("Target type", mode), 1, 0)
    grid.addWidget(value_box, 1, 1)
    dialog.body.addLayout(grid)
    panel = QFrame()
    panel.setProperty("kind", "panel")
    words = widgets.text("", "panel-text")
    inside = QVBoxLayout(panel)
    inside.setContentsMargins(*(theme.SPACE[3],) * 4)
    inside.addWidget(words)
    dialog.body.addWidget(panel)

    def preview() -> None:
        label = "Percent of income" if mode.currentData() == "percent" else "Dollars a month"
        value_label.setText(label)
        value.setAccessibleName(label)
        p = views.budget_preview(ctx.snapshot, category.currentData(), mode.currentData(), value.text())
        lines = [f"You've averaged {fmt.money(p.average)} a month here, and earned {fmt.money(p.income)} a month."]
        if p.amount is not None:
            lines.append(f"{value.text().strip().rstrip('%')}% of that income is about {fmt.money(p.amount)} a month.")
        if p.share is not None:
            lines.append(f"That's about {round(p.share * 100)}% of your income.")
        words.setText(" ".join(lines))

    for box in (category, mode):
        box.currentIndexChanged.connect(lambda _: preview())
    value.textChanged.connect(lambda _: preview())
    preview()

    def save():
        def work():
            ok, result = attempt(window.budget.save_budget, category.currentData(), mode.currentData(), value.text())
            if not ok:
                return dialog.show_error(str(result))
            dialog.dismiss()
            window.changed("Budget saved.")
        busy(dialog.main, "Saving...", work)

    dialog.set_buttons([("Cancel", dialog.dismiss, ""), ("Save", save, "primary")])
    dialog.open()
    value.setFocus()
    return dialog


def remove_budget(ctx: Context, category: str) -> Dialog:
    window = ctx.window
    return confirm(window, f"Remove the {category} budget?",
                   "Your transactions aren't affected. You can add the budget again any time.",
                   lambda: attempt(window.budget.delete_budget, category), done=lambda _: window.changed("Removed."))
