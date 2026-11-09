"""Overview: this month so far, the average month, and where the money went."""
from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QFrame, QGridLayout, QPushButton, QVBoxLayout, QWidget

from ... import views
from .. import fmt, theme, widgets
from ..charts import PICK, Chart, Series
from ..context import Context


def period_note(p: views.Period) -> str:
    if p.months == 1:
        return ""
    note = f"average of {fmt.plural(p.complete, 'complete month')}"
    return note + (f"; {p.early} earlier skipped, no checking history" if p.early else "")


def owed_tile(owed: views.Owed | None):
    if owed is None:
        return None
    sub = f"{fmt.plural(owed.missing, 'card')} not set" if owed.missing else "calculated from what you entered"
    return widgets.tile("Owed on cards", fmt.money(owed.owed), sub, fmt.gain(owed.owed))


def welcome(ctx: Context) -> QWidget:
    """Before there's any data: the two ways to bring it in."""
    w = ctx.window
    if ctx.sync_connected:
        from ..banking import sync_card
        start = sync_card(w)
    else:
        connect = QPushButton("Connect SimpleFIN")
        connect.setProperty("kind", "primary")
        connect.clicked.connect(lambda: w.banking.connect_form())
        add = QPushButton("Add files")
        add.clicked.connect(lambda: w.importing.add_files())
        start = widgets.Grid([
            widgets.card(widgets.row(connect), title="Connect your banks",
                         note="Updates through SimpleFIN, a paid service that handles your transactions. Usually brings "
                              "in about the last 90 days."),
            widgets.card(widgets.row(add), title="Add files",
                         note="Download CSV exports from each bank, for as much history as you like. Everything stays on "
                              "this computer.")], 300, most=2)
    banks = QPushButton("See which banks work")
    banks.clicked.connect(lambda: w.show_tab("Help"))
    try_it = QPushButton("Try it with sample data")
    try_it.setToolTip("Look around made-up data first. It's kept apart from yours and thrown away afterwards.")
    try_it.clicked.connect(lambda: w.try_sample())
    return widgets.column(widgets.text("Welcome to Budgetier", "h1"),
                          widgets.text("See where your money goes. Start by bringing in your accounts.", "dim"),
                          start, widgets.row(banks, try_it), spacing=theme.SPACE[4])


def stat(key: str, value: str, sub: str = "", tone: str = "") -> QWidget:
    big = widgets.text(value, "v")
    big.setProperty("tone", tone)
    return widgets.column(widgets.text(key, "k"), big, widgets.text(sub, "s") if sub else None, spacing=theme.SPACE[1])


def this_month(ctx: Context, now: views.ThisMonth | None) -> QWidget | None:
    if now is None:
        return None
    stats = [stat("Spent so far" if now.open else "Spent", fmt.money(now.spent)),
             stat("Income so far" if now.open else "Income", fmt.money(now.income), "", fmt.gain(now.income))]
    if now.compared_with:
        stats.append(stat(f"Compared with {fmt.month_name(now.compared_with, False)}",
                          f"{fmt.money(abs(now.gap))} {'more' if now.gap > 0 else 'less'}", f"by day {now.day} of the month"))
    if now.due_count:
        stats.append(stat("Bills still to come", fmt.money(now.due), f"{now.due_count} expected this month"))
    if now.budget_left is not None:
        stats.append(stat("Over budget" if now.budget_left < 0 else "Left in budgets", fmt.money(abs(now.budget_left)),
                          fmt.plural(now.budget_count, "budget"), "neg" if now.budget_left < 0 else "pos"))
    see = QPushButton("See this month")
    see.setProperty("kind", "small")
    see.clicked.connect(lambda: ctx.choose_range(now.month))
    head = widgets.row(widgets.column(widgets.text(fmt.month_name(now.month) + (" so far" if now.open else ""), "h2"),
                                      widgets.text(f"Data through {fmt.day_name(ctx.snapshot.end)}.", "dim", wrap=False),
                                      spacing=2),
                       see, stretch_last=True)
    head.layout().insertStretch(1, 1)
    frame = widgets.card(head, widgets.Grid(stats, 150, most=6, top=True))
    frame.setObjectName("thisMonth")
    return frame


class Spark(QWidget):
    """Spending in each recent month, as small bars. Months averages skip are grey."""

    def __init__(self, spark: list[tuple[str, float, bool]], tokens: dict[str, str]):
        super().__init__()
        self.spark, self.tokens = spark, tokens
        self.setFixedHeight(104)
        self.setToolTip("Spending in recent months")

    def paintEvent(self, _event):  # noqa: N802 - Qt's name
        if len(self.spark) < 2:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        gap, n = theme.SPACE[1], len(self.spark)
        width = min(26, max(3, (self.width() - gap * (n - 1)) / n))
        x = self.width() - n * width - (n - 1) * gap
        for _, height, done in self.spark:
            h = height * self.height()
            painter.setBrush(QColor(self.tokens["accent" if done else "line"]))
            painter.drawRoundedRect(QRectF(x, self.height() - h, width, h), 3, 3)
            x += width + gap


class Flow(QWidget):
    """Of every dollar earned, how much went out and how much stayed."""

    def __init__(self, spent: float, kept: bool, tokens: dict[str, str]):
        super().__init__()
        self.spent, self.kept, self.tokens = spent, kept, tokens
        self.setFixedHeight(8)

    def paintEvent(self, _event):  # noqa: N802 - Qt's name
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        w = self.width()
        spent_width = w * self.spent if self.kept else w
        painter.setBrush(QColor(self.tokens["accent"]))
        painter.drawRoundedRect(QRectF(0, 0, max(spent_width - (3 if self.kept else 0), 2), 8), 4, 4)
        if self.kept:
            painter.setBrush(QColor(self.tokens["income"]))
            painter.drawRoundedRect(QRectF(spent_width, 0, max(w - spent_width, 2), 8), 4, 4)


def hero(ctx: Context, o: views.Overview) -> QFrame:
    frame = QFrame()
    frame.setProperty("kind", "hero")
    grid = QGridLayout(frame)
    grid.setContentsMargins(*(theme.SPACE[6],) * 4)
    grid.setHorizontalSpacing(theme.SPACE[6])
    grid.setVerticalSpacing(theme.SPACE[4])
    note = period_note(o.period)
    words = ((f"Includes {fmt.money(o.estimated)} estimated from card payments. " if o.estimated > 0 else "")
             + (note[0].upper() + note[1:] + "." if note else ""))
    grid.addWidget(widgets.column(widgets.text("Spending" if o.one else "Avg. monthly spending", "k"),
                                  widgets.text(fmt.money(o.spending), "big"),
                                  widgets.text(words, "s") if words else None, spacing=theme.SPACE[2]), 0, 0)
    if not o.one:
        grid.addWidget(Spark(o.spark, ctx.tokens), 0, 1, Qt.AlignBottom)
    spent = round(o.spent_share * 100)
    share = f"{spent}% spent" + (f"  ·  {100 - spent}% kept" if o.kept > 0 else "")
    key = widgets.row(widgets.text("Of every dollar earned", "flow", wrap=False), widgets.text(share, "flow-share", wrap=False),
                      stretch_last=True)
    key.layout().insertStretch(1, 1)
    grid.addWidget(widgets.column(Flow(o.spent_share, o.kept > 0, ctx.tokens), key, spacing=theme.SPACE[2]), 1, 0, 1, 2)
    grid.setColumnStretch(0, 1)
    grid.setColumnStretch(1, 1)
    return frame


def whats_new(ctx: Context) -> QWidget | None:
    """What came in since you last looked: new transactions, newly recurring payments, price changes."""
    window = ctx.window
    if getattr(window, "sample_home", None):
        return None  # what's new is about your own data
    found = views.news(ctx.snapshot, getattr(window, "seen", None))
    if found is None:
        return None
    lines = []
    if found.count:
        money = [m for m in (f"{fmt.money(found.spent)} spent" if found.spent else "",
                             f"{fmt.money(found.received)} in" if found.received else "") if m]
        lines.append(widgets.text(fmt.plural(found.count, "new transaction") + (": " + ", ".join(money) if money else ".")))
    for r in found.subscriptions:
        lines.append(widgets.text(f"Newly recurring: {r.merchant}, {fmt.cents(r.amount)} {r.cadence.lower()}"))
    for r in found.prices:
        went = "up" if r.price_change > 0 else "down"
        lines.append(widgets.text(f"{r.merchant} went {went} {fmt.cents(abs(r.price_change))}, to {fmt.cents(r.amount)}"))
    see = QPushButton("See transactions")
    see.setProperty("kind", "small")
    see.clicked.connect(lambda _=False: ctx.open_transactions())
    done = QPushButton("Got it")
    done.setProperty("kind", "small")
    done.clicked.connect(lambda _=False: window.mark_seen())
    frame = widgets.card(widgets.column(*lines, spacing=theme.SPACE[1]),
                         widgets.row(see if found.count else None, done),
                         title="New since you last looked", note=f"After {fmt.day_name(found.since)}, the newest day you'd seen.")
    frame.setObjectName("whatsNew")
    return frame


def reminder(ctx: Context) -> QWidget | None:
    """When the numbers are a while out of date: sync, or add recent files."""
    found = views.reminder(ctx.snapshot, ctx.sync)
    if found is None or ctx.window is None:
        return None
    go = QPushButton("Sync now" if found.action == "sync" else "Add files")
    go.setProperty("kind", "primary")
    go.clicked.connect(lambda _=False: ctx.window.sync() if found.action == "sync" else ctx.window.add_files())
    return widgets.banner("info", found.title, found.detail, ctx.tokens, go)


def running_short(ctx: Context) -> QWidget | None:
    """When the bills ahead would take checking below zero, before payday does."""
    f = views.forecast(ctx.snapshot)
    if not f.short:
        return None
    go = QPushButton("See what's due")
    go.setProperty("kind", "small")
    go.clicked.connect(lambda _=False: ctx.window.show_tab("Recurring"))
    return widgets.banner("warning", f"Checking could run short around {fmt.day_name(f.low_day)}",
                          f"The bills and card payments due before then would take it to {fmt.money(f.low)}, from "
                          f"{fmt.money(f.balance)} on {fmt.day_name(f.start)}.", ctx.tokens,
                          go if ctx.window is not None else None)


def build(ctx: Context) -> QWidget:
    s, t = ctx.snapshot, ctx.tokens
    if not s.txns:
        return welcome(ctx)
    o = views.overview(s, ctx.choice)
    average = "" if o.one else "Avg. monthly "
    rate = "n/a" if o.rate is None else f"{round(o.rate * 100)}%"
    figures = widgets.tiles(
        widgets.tile(f"{average}income" if average else "Income", fmt.money(o.income),
                     "" if o.one else "same months as spending", "pos"),
        widgets.tile("Savings rate", rate, fmt.money(o.kept) + (" kept" if o.one else " kept per month"), fmt.tone(o.kept)),
        widgets.tile("Recurring bills", fmt.money(o.recurring) + "/mo", f"{o.recurring_count} active"),
        owed_tile(o.owed))
    chart = widgets.card(widgets.legend([("Income", t["income"]), ("Spending", t["spending"])]),
                         Chart(o.months, [Series("Income", o.chart_income, t["income"]),
                                          Series("Spending", o.chart_spending, t["spending"])], t,
                               partial_month=s.partial_month, on_pick=ctx.choose_range),
                         title="Income and spending", note=PICK)
    if o.categories:
        went = widgets.hbars([(c, v, ctx.color(c), lambda c=c: ctx.open_transactions(category=c)) for c, v in o.categories],
                             fmt.money, t)
    else:
        went = widgets.empty("No spending in this period.")
    where = widgets.card(went, title="Where it went", note="Select a category to see its transactions.")
    split = QWidget()
    layout = QGridLayout(split)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(theme.SPACE[4])
    layout.addWidget(chart, 0, 0)
    layout.addWidget(where, 0, 1)
    layout.setColumnStretch(0, 155)
    layout.setColumnStretch(1, 100)
    page = QWidget()
    column = QVBoxLayout(page)
    column.setContentsMargins(0, 0, 0, 0)
    column.setSpacing(theme.SPACE[4])
    parts = (reminder(ctx), running_short(ctx), whats_new(ctx), widgets.notices(o.warnings, t),
             this_month(ctx, o.this_month), hero(ctx, o),
             figures, split)
    for part in parts:
        if part is not None:
            column.addWidget(part)
    return page
