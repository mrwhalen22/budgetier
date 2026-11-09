"""Investments: what investing and retirement accounts hold, how they've grown beyond what was
paid in, and an estimate of what retirement accounts could become."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QDoubleValidator, QIntValidator
from PySide6.QtWidgets import QLineEdit, QPushButton, QVBoxLayout, QWidget

from ... import views
from ...parse import parse_money
from .. import fmt, investing, settings, theme, widgets
from ..charts import Chart, Series
from ..context import Context
from ..importing import field
from .overview import welcome

SAVED_AS = "retirement"  # the plan's key in settings.json
DISCLAIMER = ("An estimate from the numbers you enter, not advice. Real returns go up and down from year to year, "
              "and rates here are after inflation, so amounts are in today's dollars.")


def _percent(rate: float | None) -> str:
    return "" if rate is None else f"{rate * 100:+.1f}% on what was invested"


def empty(ctx: Context) -> QWidget:
    go = QPushButton("Open Accounts")
    go.setProperty("kind", "primary")
    go.clicked.connect(lambda _=False: ctx.window.show_tab("Accounts"))
    return widgets.card(
        widgets.text("Mark an account as Investing or Retirement on the Accounts tab: choose Edit, then its type. "
                     "Accounts named like 401(k), IRA or Brokerage are marked when you link them through bank sync."),
        widgets.row(go), title="No investing or retirement accounts yet",
        note="Their balances, what you've paid in, and how they've grown show here.")


def build(ctx: Context) -> QWidget:
    s, t = ctx.snapshot, ctx.tokens
    if not s.txns and not any(a.type in views.INVESTED for a in s.accounts):
        return welcome(ctx)
    if not any(a.type in views.INVESTED for a in s.accounts):
        return empty(ctx)
    v = views.investments(s, ctx.choice)
    parts: list[QWidget | None] = []
    since = f"since {views.day_name(v.tracked_from)}" if v.tracked_from else ""
    parts.append(widgets.tiles(
        widgets.tile("Invested now", fmt.money(v.total), f"{fmt.plural(len(v.accounts), 'account')}"),
        # Only when it says something new: with every account for retirement, it's the same number again.
        widgets.tile("In retirement accounts", fmt.money(v.retirement), "")
        if v.retirement is not None and v.retirement != v.total else None,
        widgets.tile("Paid in this period", fmt.money(v.contributed), "net of withdrawals", fmt.tone(v.contributed)),
        widgets.tile("Growth this period", fmt.money(v.growth) if v.growth is not None else "n/a",
                     _percent(v.growth_rate) if v.growth is not None else "needs two balances a while apart",
                     fmt.tone(v.growth or 0))))
    check = None
    if views.investing_rows(s, {a.id for a in v.accounts}) and ctx.window is not None:
        check = QPushButton("Check what counts as paid in")
        check.setProperty("kind", "small")
        check.clicked.connect(lambda _=False: investing.review(ctx.window, {a.id for a in v.accounts}))
        check = widgets.row(check)
    checking = " Growth leaves out what was paid in, so it's worth checking which rows are which." if check else ""
    if any(b is not None for b in v.balance):
        parts.append(widgets.card(
            widgets.legend([("Balance", t["accent"]), ("Paid in", t["muted"])]),
            Chart(v.months, [Series("Balance", v.balance, t["accent"]), Series("Paid in", v.paid_in, t["muted"])], t,
                  kind="lines"),
            check,
            title="Balance and what was paid in",
            note="The gap between the lines is growth: markets, dividends and fees. Each bank sync keeps that day's "
                 f"balance, so growth is seen {since or 'from your next sync'}.{checking}"))
    elif check:
        parts.append(widgets.card(check, title="What was paid in", note=checking.strip()))
    if len(v.lines) > 1:
        colors = [t[f"c{i}"] for i in range(len(v.lines))]
        parts.append(widgets.card(
            widgets.legend([(name, colors[i]) for i, (name, _) in enumerate(v.lines)]),
            Chart(v.months, [Series(name, values, colors[i]) for i, (name, values) in enumerate(v.lines)], t, kind="lines"),
            title="Each account", note="The last balance known at the end of each month."))
    parts.append(Estimate(ctx))
    return widgets.column(*parts, spacing=theme.SPACE[4])


class Estimate(QWidget):
    """The retirement estimate. It redraws itself as the numbers change, so typing in one
    field doesn't rebuild the tab and lose your place."""

    def __init__(self, ctx: Context):
        super().__init__()
        self.ctx = ctx
        self.home = ctx.window.budget.home if ctx.window is not None else None
        self.plan = views.Plan.from_saved(settings.load(self.home).get(SAVED_AS)) if self.home else views.Plan()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        p = self.plan
        self.age = self._number(str(p.age), QIntValidator(16, 100), "Your age")
        self.retire_at = self._number(str(p.retire_at), QIntValidator(16, 110), "Retire at")
        self.monthly = self._number("" if p.monthly is None else f"{p.monthly / 100:.0f}", None, "Paid in a month")
        self.growth = self._number(f"{p.growth:g}", QDoubleValidator(-10, 20, 1), "Growth a year, %")
        self.withdraw = self._number(f"{p.withdraw:g}", QDoubleValidator(0.5, 15, 1), "Drawn a year, %")
        self.include = widgets.check("Count investing accounts too", p.include_investing, lambda _on: self.changed())
        self.include.setVisible(any(a.type == "investment" for a in ctx.snapshot.accounts))
        inputs = widgets.Grid([field("Your age", self.age), field("Retire at", self.retire_at),
                               field("Paid in a month", self.monthly), field("Growth a year, after inflation (%)", self.growth),
                               field("Drawn a year once retired (%)", self.withdraw)], 150, most=5)
        self.results = QVBoxLayout()
        self.results.setContentsMargins(0, 0, 0, 0)
        holder = QWidget()
        holder.setLayout(self.results)
        layout.addWidget(widgets.card(inputs, self.include, holder, title="Retirement estimate", note=DISCLAIMER))
        self.draw()

    def _number(self, value: str, validator, name: str) -> QLineEdit:
        edit = QLineEdit(value)
        edit.setAccessibleName(name)
        edit.setAlignment(Qt.AlignRight)
        if validator is not None:
            edit.setValidator(validator)
        edit.textChanged.connect(lambda _text: self.changed())
        return edit

    def read(self) -> views.Plan | None:
        """The plan in the fields, or None while one of them isn't a number yet."""
        try:
            age, retire_at = int(self.age.text()), int(self.retire_at.text())
            growth, withdraw = float(self.growth.text()), float(self.withdraw.text())
        except ValueError:
            return None
        typed = self.monthly.text().strip()
        monthly = parse_money(typed) if typed else None
        if typed and (monthly is None or monthly < 0):
            return None
        return views.Plan.from_saved({"age": age, "retire_at": retire_at, "monthly": monthly, "growth": growth,
                                      "withdraw": withdraw, "include_investing": self.include.isChecked()})

    def changed(self) -> None:
        plan = self.read()
        if plan is None:
            return
        self.plan = plan
        if self.home:
            settings.save(self.home, **{SAVED_AS: plan.saved()})
        self.draw()

    def draw(self) -> None:
        while self.results.count():
            old = self.results.takeAt(0).widget()
            if old is not None:
                old.deleteLater()
        t, plan = self.ctx.tokens, self.plan
        p = views.retirement(self.ctx.snapshot, plan)
        if p is None:
            self.results.addWidget(widgets.text("Mark a retirement account on the Accounts tab, or count investing "
                                                "accounts too, to see an estimate.", "dim"))
            return
        self.monthly.setPlaceholderText(f"{p.monthly / 100:.0f}" if plan.monthly is None else "")
        if p.years == 0:
            self.results.addWidget(widgets.text("Choose a retirement age after your age.", "dim"))
            return
        paid = "what you've paid in lately" if plan.monthly is None else "what you entered"
        self.results.addWidget(widgets.tiles(
            widgets.tile("Today", fmt.money(p.balance), "counted toward retirement"),
            widgets.tile(f"At {plan.retire_at}", fmt.money(p.at_retirement), f"in {fmt.plural(p.years, 'year')}", "pos"),
            widgets.tile("A month after that", fmt.money(p.income), f"drawing {plan.withdraw:g}% a year"),
            widgets.tile("Paid in a month", fmt.money(p.monthly), paid)))
        self.results.addWidget(widgets.legend([("Estimated balance", t["accent"]), ("Paid in", t["muted"])]))
        ages = p.ages
        self.results.addWidget(Chart(ages, [Series("Estimated balance", p.path, t["accent"]),
                                            Series("Paid in", p.paid, t["muted"])], t, kind="lines",
                                     labels=ages, titles=[f"Age {a}" for a in ages]))
