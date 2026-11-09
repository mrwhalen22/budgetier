"""Net worth, on the Savings tab: everything you have, less everything you owe, and how that's changed."""
from __future__ import annotations

from PySide6.QtWidgets import QPushButton, QWidget

from ... import views
from .. import fmt, widgets
from ..charts import Chart, Series
from ..context import Context
from .accounts import TYPE_COLOR, TYPE_NAMES, edit_account


def holdings(ctx: Context, found: list[views.Holding], empty: str) -> QWidget:
    if not found:
        return widgets.empty(empty)
    t = ctx.tokens
    rows = [[widgets.Cell(h.account.name, icon=widgets.mono_icon(h.account.bank, t[TYPE_COLOR[h.account.type]]), bold=True),
             widgets.Cell(TYPE_NAMES[h.account.type], tone="dim"),
             widgets.Cell(fmt.cents(h.balance) if h.balance is not None else "not set", right=True,
                          tone="" if h.balance is not None else "dim"),
             widgets.Cell(("+" if h.change > 0 else "") + fmt.cents(h.change) if h.change is not None else "", right=True,
                          tone=fmt.tone(h.change) if h.change else "dim")]
            for h in found]
    window = ctx.window
    # The name gives way in a narrow card, rather than the table scrolling sideways.
    return widgets.Table(["Account", "Type", "Balance", "Change"], rows, t, numeric={2, 3}, stretch=0,
                         on_row=(lambda r: edit_account(window, found[r].account)) if window is not None else None)


def figures(ctx: Context, v: views.NetWorth) -> list[QWidget]:
    """Net worth now, and how it changed over the period."""
    period = views.range_label(ctx.snapshot, ctx.choice).lower()
    return [widgets.tile("Net worth", fmt.money(v.now) if v.now is not None else "n/a",
                         "what you have, less what you owe" if v.now is not None else "needs an account balance",
                         fmt.tone(v.now or 0)),
            widgets.tile("Net worth change", fmt.money(v.change) if v.change is not None else "n/a",
                         period if v.change is not None else "needs balances in two months", fmt.tone(v.change or 0))]


def missing(ctx: Context, v: views.NetWorth) -> QWidget | None:
    """Accounts left out of net worth until they have a balance."""
    t = ctx.tokens
    if v.missing:
        go = QPushButton("Open Accounts")
        go.setProperty("kind", "small")
        go.clicked.connect(lambda _=False: ctx.window.show_tab("Accounts"))
        names = ", ".join(a.name for a in v.missing[:3]) + (" and others" if len(v.missing) > 3 else "")
        return widgets.banner(
            "info", f"{fmt.plural(len(v.missing), 'account')} without a balance",
            f"{names} {'is' if len(v.missing) == 1 else 'are'} left out until a balance is set: choose Edit on the "
            "Accounts tab, or link it through bank sync.", t, action=go if ctx.window is not None else None)
    return None


def sections(ctx: Context, v: views.NetWorth) -> list[QWidget | None]:
    """Net worth over time, what's paid toward loans, and each account on either side."""
    t = ctx.tokens
    period = views.range_label(ctx.snapshot, ctx.choice).lower()
    have, owe = (next((x for x in reversed(line) if x is not None), None) for line in (v.assets, v.debts))
    parts: list[QWidget | None] = []
    if any(n is not None for n in v.net):
        parts.append(widgets.card(
            widgets.legend([("Net worth", t["accent"]), ("You have", t["c2"]), ("You owe", t["c1"])]),
            Chart(v.months, [Series("Net worth", v.net, t["accent"]), Series("You have", v.assets, t["c2"]),
                             Series("You owe", v.debts, t["c1"])], t, kind="lines"),
            title="Net worth over time",
            note="Each month's end. An account counts from its first known balance, so one added partway through "
                 "shows as a step."))
    if v.loan_paid or v.loan_interest:
        parts.append(widgets.tiles(
            widgets.tile("Paid toward loans", fmt.money(v.loan_paid), period),
            widgets.tile("Loan interest", fmt.money(-v.loan_interest), "counted as spending"),
            widgets.tile("Paid off the balance", fmt.money(v.loan_paid + v.loan_interest), "after interest")
            if v.loan_paid else None))
    parts.append(widgets.Grid([
        widgets.card(holdings(ctx, v.have, "No bank, savings or investing accounts with a balance."),
                     title=f"What you have: {fmt.money(have or 0)}"),
        widgets.card(holdings(ctx, v.owe, "No cards or loans with a balance."), title=f"What you owe: {fmt.owed(owe or 0)}",
                     note="Add a mortgage, car or student loan as a Loan, so its payments count as paying it down.")],
        460, most=2, top=True))
    return parts
