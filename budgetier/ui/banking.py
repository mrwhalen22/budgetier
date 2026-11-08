"""Bank sync through SimpleFIN: connect, choose accounts, sync now, and disconnect.

Anything that talks to SimpleFIN runs off the window's thread. A sync only happens when asked.
"""
from __future__ import annotations

from datetime import datetime

from PySide6.QtWidgets import QFrame, QGridLayout, QLineEdit, QVBoxLayout

from . import fmt, theme, widgets
from .dialogs import Dialog, attempt, busy, confirm
from .importing import done_rows, field, scrolling, type_box
from .popup import Dropdown

NEW, SKIP = "", "skip"


def synced_at(status: dict) -> str:
    """When it last synced, like Nov 7, 3:04 PM."""
    if not status.get("lastSync"):
        return ""
    when = datetime.fromisoformat(status["lastSync"])
    return f"{when:%b} {when.day}, {when:%I:%M %p}".replace(", 0", ", ")


def button_label(status: dict) -> str:
    if not status["connected"]:
        return "Connect SimpleFIN"
    return "Sync now" if status["linked"] else "Choose accounts"


class AccountPanel(QFrame):
    """One account SimpleFIN offers, and where it should go."""

    def __init__(self, account: dict, existing: list[dict]):
        super().__init__()
        self.account = account
        self.setProperty("kind", "panel")
        column = QVBoxLayout(self)
        column.setContentsMargins(*(theme.SPACE[4],) * 4)
        column.setSpacing(theme.SPACE[2])
        column.addWidget(widgets.text(f"{account['bank']}: {account['name']}", "h3"))
        usd = account["currency"] == "USD"
        currency = "" if usd else f" {account['currency']}"
        column.addWidget(widgets.text(f"Balance {fmt.cents(round(account['balance'] * 100))}{currency}, "
                                      f"{account['count']:,} recent transactions", "sub"))
        self.link = None
        if not usd:
            column.addWidget(widgets.text("Only US dollar accounts can sync, so this one is skipped.", "sub"))
            return
        self.link = Dropdown()
        self.link.setAccessibleName("Add to")
        for choice in existing:
            self.link.addItem(choice["name"], choice["id"])
        self.link.addItem("New account", NEW)
        self.link.addItem("Don't sync", SKIP)
        self.link.setCurrentIndex(self.link.findData(SKIP if account["skipped"] else account["account"]))
        column.addWidget(field("Add to", self.link))
        self.bank = QLineEdit(account["bank"])
        self.bank.setAccessibleName("Bank")
        self.number = QLineEdit(account["number"])
        self.number.setMaxLength(4)
        self.number.setAccessibleName("Last 4 digits, optional")
        self.type = type_box(account["type"])
        self.new = QFrame()
        grid = QGridLayout(self.new)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(theme.SPACE[3])
        grid.addWidget(field("Bank", self.bank), 0, 0)
        grid.addWidget(field("Last 4 digits, optional", self.number), 0, 1)
        grid.addWidget(field("Type", self.type), 0, 2)
        column.addWidget(self.new)
        self.link.currentIndexChanged.connect(self._shown)
        self._shown()

    def _shown(self) -> None:
        self.new.setVisible(self.link.currentData() == NEW)

    def choice(self) -> dict:
        a = self.account
        if self.link is None:
            return {"key": a["key"], "name": a["name"], "account": SKIP}
        return {"key": a["key"], "name": a["name"], "account": self.link.currentData(), "bank": self.bank.text(),
                "number": self.number.text(), "type": self.type.currentData()}


class Banking:
    def __init__(self, window):
        self.window = window
        self.dialog: Dialog | None = None
        self.panels: list[AccountPanel] = []

    @property
    def sync(self):
        return self.window.budget.sync

    def status(self) -> dict:
        return self.sync.status()

    def act(self) -> None:
        """What the sidebar's bank button does, by how far along the connection is."""
        s = self.status()
        if not s["connected"]:
            self.connect_form()
        elif s["linked"]:
            self.sync_now()
        else:
            self.choose()

    # ---- connecting

    def connect_form(self) -> Dialog:
        dialog = Dialog(self.window, "Connect SimpleFIN",
                        "Paste the setup token from your SimpleFIN account. It only works once.")
        self.token = QLineEdit()
        self.token.setEchoMode(QLineEdit.Password)
        self.token.setAccessibleName("Setup token")
        dialog.body.addWidget(field("Setup token", self.token))
        dialog.body.addWidget(widgets.text(
            "Budgetier keeps this connection in this computer's secure storage. It can read your transactions and "
            "balances, but can't move money. SimpleFIN and the services behind it will handle your transactions.", "dim"))
        dialog.set_buttons([("Cancel", dialog.dismiss, ""), ("Connect", self._connect, "primary")])
        self.dialog = dialog
        dialog.open()
        self.token.setFocus()
        return dialog

    def _connect(self) -> None:
        dialog = self.dialog
        dialog.main.setEnabled(False)
        dialog.main.setText("Connecting...")

        def answered(ok, plan):
            if not ok:
                dialog.main.setEnabled(True)
                dialog.main.setText("Connect")
                return dialog.show_error(str(plan))
            dialog.dismiss()
            self.window.changed()  # connected, whatever is chosen next
            self.review(plan)
        self.window.runner.start(self.sync.connect, (self.token.text(),), answered, "Connecting...")

    # ---- choosing accounts

    def choose(self) -> None:
        def answered(ok, plan):
            if not ok:
                return self.window.toast.say(str(plan))
            self.review(plan)
        self.window.runner.start(self.sync.review, (), answered, "Checking SimpleFIN...")

    def review(self, plan: dict) -> Dialog:
        accounts = plan["accounts"]
        if accounts:
            lead = ("Match each bank account to one here, or add it as new. History you've already imported stays, and "
                    "syncing adds what's newer." if plan["existing"] else "Check each account, then save. You can change "
                    "this later.")
        else:
            lead = ""
        dialog = Dialog(self.window, "Choose accounts", lead)
        for problem in plan["problems"]:
            dialog.body.addWidget(widgets.banner("warning", "SimpleFIN says", problem, self.window.tokens()))
        if not accounts and not plan["problems"]:
            dialog.body.addWidget(widgets.text("SimpleFIN didn't send any accounts yet. Check the banks connected on your "
                                               "SimpleFIN account."))
        self.panels = [AccountPanel(a, plan["existing"]) for a in accounts]
        if self.panels:
            dialog.body.addWidget(scrolling(widgets.column(*self.panels, spacing=theme.SPACE[3])))
        dialog.setMinimumWidth(640)
        buttons = [("Cancel" if accounts else "Close", dialog.dismiss, "")]
        if accounts:
            buttons.append(("Save", self._link, "primary"))
        dialog.set_buttons(buttons)
        self.dialog = dialog
        dialog.open()
        return dialog

    def _link(self) -> None:
        dialog = self.dialog

        def work():
            ok, done = attempt(self.sync.link, [p.choice() for p in self.panels])
            if not ok:
                return dialog.show_error(str(done))
            dialog.dismiss()
            self._linked(done)
        busy(dialog.main, "Saving...", work)

    def _linked(self, done: dict) -> Dialog:
        lead = ("SimpleFIN usually brings in about the last 90 days. To go further back, add CSV exports. Overlapping days "
                "aren't counted twice." if done["results"] else "")
        dialog = Dialog(self.window, "Accounts saved", lead)
        lines = [(r["account"], f"{r['added']:,} new") for r in done["results"]]
        dialog.body.addWidget(done_rows(lines) if lines else widgets.text("No accounts are syncing."))
        dialog.set_buttons([("Done", lambda: (dialog.dismiss(), self.window.changed()), "primary")])
        self.dialog = dialog
        dialog.open()
        return dialog

    # ---- syncing

    def sync_now(self) -> None:
        def answered(ok, done):
            if not ok:
                return self.window.toast.say(str(done))
            if done.get("skipped"):
                return self.window.toast.say("Synced a moment ago, so there's nothing new yet.")
            if done["added"]:
                note = f"Synced: {fmt.plural(done['added'], 'new transaction')}."
            elif done["problems"] or done["unlinked"]:
                note = "Synced. See Bank sync on the Accounts tab."
            else:
                note = "Everything's up to date."
            self.window.changed(note)
        self.window.runner.start(self.sync.sync, (), answered, "Syncing...")

    def disconnect(self) -> None:
        confirm(self.window, "Disconnect SimpleFIN?",
                "Budgetier stops syncing and forgets the connection. Your transactions stay. To cut off access completely, "
                "disable it on the SimpleFIN site too.", lambda: attempt(self.sync.disconnect), action="Disconnect",
                done=lambda _: self.window.changed("Disconnected."))


def sync_card(window) -> QFrame:
    """Bank sync on the Accounts tab: how it stands, and what can be done."""
    s = window.banking.status()
    t = window.tokens()

    def button(label, run, kind=""):
        from PySide6.QtWidgets import QPushButton
        b = QPushButton(label)
        if kind:
            b.setProperty("kind", kind)
        b.clicked.connect(lambda _=False: run())
        return b

    if not s["connected"]:
        return widgets.card(widgets.row(button("Connect SimpleFIN", window.banking.connect_form)), title="Bank sync",
                            note="Update accounts through SimpleFIN instead of downloading files. SimpleFIN and the "
                                 "services behind it handle your transactions, so they no longer stay only on this computer.")
    when = synced_at(s) or "not yet"
    updating = f" Updating {', '.join(s['linked'])}." if s["linked"] else " No accounts chosen yet."
    parts = [widgets.banner("warning", "SimpleFIN says", p, t) for p in s["problems"]]
    if s["unlinked"]:
        parts.append(widgets.banner("warning", "Not chosen yet",
                                    f"SimpleFIN has {fmt.plural(s['unlinked'], 'account')} you haven't chosen yet.", t))
    linked = bool(s["linked"])
    actions = [button("Sync now", window.banking.sync_now, "primary")] if linked else []
    actions += [button("Choose accounts", window.banking.choose, "" if linked else "primary"),
                button("Disconnect", window.banking.disconnect)]
    return widgets.card(*parts, widgets.row(*actions), title="Bank sync",
                        note=f"Connected through SimpleFIN. Last synced {when}.{updating}")
