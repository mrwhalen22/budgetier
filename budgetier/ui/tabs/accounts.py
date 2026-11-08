"""Accounts: balances, bank sync, each account and recent file, and what's worth checking."""
from __future__ import annotations

from datetime import date

from PySide6.QtCore import QDate, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QDateEdit, QGridLayout, QLineEdit, QPushButton, QWidget

from ... import views
from .. import fmt, theme, widgets
from ..banking import sync_card
from ..context import Context
from ..dialogs import Dialog, attempt, busy, confirm
from ..importing import field, type_box

TYPE_NAMES = {"checking": "Checking", "savings": "Savings", "credit": "Credit card"}
TYPE_COLOR = {"checking": "c0", "credit": "c1", "savings": "c2"}


def _button(label: str, run, kind: str = "small") -> QPushButton:
    button = QPushButton(label)
    button.setProperty("kind", kind)
    button.clicked.connect(lambda _=False: run())
    return button


def _actions(*buttons: QPushButton) -> QWidget:
    box = widgets.row(*buttons, spacing=theme.SPACE[1])
    box.layout().setContentsMargins(theme.SPACE[1], 0, theme.SPACE[1], 0)
    return box


def span(first: str, last: str) -> str:
    return f"{fmt.month_name(first[:7])} to {fmt.month_name(last[:7])}"


# ---- what can be done here


def export(window) -> None:
    path = window.ask_save_path()
    if not path:
        return
    ok, result = attempt(window.budget.export_workbook, path)
    window.toast.say(f"Saved {path}" if ok else str(result))


def open_folder(window) -> None:
    QDesktopServices.openUrl(QUrl.fromLocalFile(str(window.budget.home)))


def edit_account(window, account: views.Account) -> Dialog:
    owed = account.type == "credit"
    dialog = Dialog(window, f"Edit {account.name}")
    name = QLineEdit(account.name)
    name.setAccessibleName("Name")
    kind = type_box(account.type)
    grid = QGridLayout()
    grid.setHorizontalSpacing(theme.SPACE[3])
    grid.addWidget(field("Name", name), 0, 0)
    grid.addWidget(field("Type", kind), 0, 1)
    balance = as_of = None
    if account.calculated or account.balance is None:  # an export's own balance column can't be overridden
        current = f"{abs(account.balance) / 100:.2f}" if account.calculated else ""
        balance = QLineEdit(current)
        balance.setPlaceholderText("From the bank's website")
        label = "Amount owed" if owed else "Balance"
        balance.setAccessibleName(label)
        as_of = QDateEdit(QDate.currentDate())
        as_of.setCalendarPopup(True)
        as_of.setAccessibleName("As of")
        grid.addWidget(field(label, balance), 1, 0)
        grid.addWidget(field("As of", as_of), 1, 1)
    dialog.body.addLayout(grid)

    def save():
        def work():
            day = as_of.date().toPython().isoformat() if as_of else date.today().isoformat()
            ok, result = attempt(window.budget.update_account, account.id, name.text(), kind.currentData(),
                                 balance.text() if balance else "", day)
            if not ok:
                return dialog.show_error(str(result))
            dialog.dismiss()
            window.changed("Account saved.")
        busy(dialog.main, "Saving...", work)

    dialog.set_buttons([("Cancel", dialog.dismiss, ""), ("Save", save, "primary")])
    dialog.open()
    return dialog


def remove_account(window, account: views.Account) -> Dialog:
    return confirm(window, f"Remove {account.name}?",
                   f"This deletes its {fmt.plural(account.count, 'transaction')} and saved files from Budgetier. Your "
                   "original files aren't touched, so you can import them again.",
                   lambda: attempt(window.budget.remove_account, account.id), done=lambda _: window.changed("Removed."))


def remove_import(window, entry: dict) -> Dialog:
    return confirm(window, f"Remove {entry['file']}?",
                   f"This file added {fmt.plural(entry['added'], 'transaction')}. Any that another imported file also "
                   "covers will stay. To bring the rest back, import the file again.",
                   lambda: attempt(window.budget.remove_import, entry["key"]), done=lambda _: window.changed("Removed."))


# ---- the tab


def accounts_table(ctx: Context, found: list[views.Account]) -> QWidget:
    w, t = ctx.window, ctx.tokens
    rows = []
    for a in found:
        if a.balance is None:
            balance = widgets.Cell("not set", right=True, tone="dim")
        else:
            tone = fmt.gain(a.balance) if a.type == "credit" else fmt.tone(a.balance)
            balance = widgets.Cell(fmt.cents(a.balance), right=True, tone=tone)
        source = f"{'from your bank' if a.live else 'calculated'}, {fmt.day_name(a.balance_as_of)}" if a.calculated else ""
        rows.append([widgets.Cell(a.name, icon=widgets.mono_icon(a.bank, t[TYPE_COLOR[a.type]]), bold=True),
                     widgets.Cell(TYPE_NAMES[a.type], tone="dim"),
                     widgets.Cell(span(a.first, a.last) if a.first else "No recent activity", tone="dim"),
                     widgets.Cell(f"{a.count:,}", right=True),
                     balance, widgets.Cell(source, tone="dim"), widgets.Cell("")])
    table = widgets.Table(["Account", "Type", "History", "Rows", "Latest balance", "", ""], rows, t,
                          on_row=lambda r: edit_account(w, found[r]), numeric={3, 4})
    for r, a in enumerate(found):
        table.setCellWidget(r, 6, _actions(_button("Edit", lambda a=a: edit_account(w, a)),
                                           _button("Remove", lambda a=a: remove_account(w, a), "small-danger")))
    table.resizeColumnsToContents()
    return table


def imports_table(ctx: Context, entries: list[dict]) -> QWidget:
    if not entries:
        return widgets.empty("No files imported yet.")
    rows = [[widgets.Cell(i["file"], tip=i["file"]), widgets.Cell(i["account"], tone="dim"),
             widgets.Cell(span(i["first"], i["last"]), tone="dim"), widgets.Cell(f"{i['added']:,}", right=True),
             widgets.Cell(f"{i['duplicates']:,}", right=True), widgets.Cell("")] for i in entries]
    table = widgets.Table(["File", "Account", "Covers", "New", "Had", ""], rows, ctx.tokens, numeric={3, 4})
    for r, entry in enumerate(entries):
        table.setCellWidget(r, 5, _actions(_button("Remove", lambda e=entry: remove_import(ctx.window, e), "small-danger")))
    table.resizeColumnsToContents()
    return table


def build(ctx: Context) -> QWidget:
    w = ctx.window
    if not ctx.snapshot.txns:
        from .overview import welcome
        return welcome(ctx)
    a = views.accounts(ctx.snapshot)
    owed = None
    if a.owed:
        sub = f"{fmt.plural(a.owed.missing, 'card')} not set" if a.owed.missing else "calculated from what you entered"
        owed = widgets.tile("Owed on cards", fmt.money(a.owed.owed), sub, fmt.gain(a.owed.owed))
    figures = widgets.tiles(
        widgets.tile("Cash and savings", fmt.money(a.cash), f"{a.cash_accounts} of {a.banked_accounts} accounts",
                     fmt.tone(a.cash)) if a.cash is not None else None,
        owed,
        widgets.tile("Net of cards", fmt.money(a.net), "cash and savings minus cards", fmt.tone(a.net))
        if a.net is not None else None)
    tools = widgets.row(_button("Export workbook", lambda: export(w), ""),
                        _button("Open data folder", lambda: open_folder(w), ""))
    parts = [figures, tools, widgets.notices(a.warnings, ctx.tokens), sync_card(w)]
    if a.accounts:
        parts.append(widgets.Grid([widgets.card(accounts_table(ctx, a.accounts), title="Accounts"),
                                   widgets.card(imports_table(ctx, a.imports), title="Recent imports")], 520, most=2, top=True))
    if a.notes:
        parts.append(widgets.card(*(widgets.banner(c["level"], c["title"], c["detail"], ctx.tokens) for c in a.notes),
                                  title="Worth checking", note="Things that could make the numbers wrong."))
    return widgets.column(*parts, spacing=theme.SPACE[4])
