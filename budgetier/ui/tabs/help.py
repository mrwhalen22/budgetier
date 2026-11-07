"""Help: getting started, which banks work, bank sync, tips, and where your data lives."""
from __future__ import annotations

from PySide6.QtWidgets import QPushButton, QWidget

from .. import theme, tour, widgets
from ..context import Context

# Bank, file, and whether it's been tried with real files.
BANKS = [
    ("Fifth Third", "Checking CSV", True), ("Chase", "Credit card CSV", True), ("USAA", "Credit card CSV", True),
    ("Synchrony", "Savings PDF", True), ("Chase", "Checking CSV", False), ("American Express", "Card CSV", False),
    ("Apple Card", "CSV", False), ("Bank of America", "Checking and card CSV", False),
    ("Capital One", "Checking and card CSV", False), ("Citi", "Card CSV", False), ("Discover", "Card CSV", False),
    ("Ally", "CSV", False), ("U.S. Bank", "CSV", False), ("USAA", "Checking CSV", False), ("Wells Fargo", "Checking CSV", False),
]
STEPS = [
    ("Connect or download.", "Connect SimpleFIN to update accounts, or download transaction history from each bank's "
     "website. Look for Download, Export or Statements, choose CSV, and ask for as much history as it offers."),
    ("Add files", "if you downloaded any, and check the review screen. Date ranges can overlap, because repeats are "
     "skipped automatically."),
    ("Tidy up", "on the Rules tab by giving unknown purchases a name and category."),
    ("Set budgets", "on the Budgets tab, as a dollar amount or a percent of income."),
]
TIPS = [
    ("Import every account you pay from", "Paying a card from checking is a transfer, so the purchases only appear once "
     "that card is imported. Until then, the payment counts as estimated spending."),
    ("Export as far back as you can", "Averages skip months before your checking history starts, because those months "
     "have no rent or income in them."),
    ("Enter card balances", "Card exports don't include a balance. Use Edit on the Accounts tab to enter what you owe, "
     "and Budgetier keeps it updated from each import."),
    ("Fix one transaction", "Select a row on the Transactions tab and choose Just this transaction. Rules won't change "
     "that row again, and you can undo it the same way."),
    ("How money is counted", "Expenses and estimates add to spending. Refunds reduce it. Income counts as income. "
     "Transfers between your own accounts count as neither."),
]
SYNC = ("Connect SimpleFIN to update accounts instead of downloading files. Press Sync now whenever you want: each sync "
        "brings in everything since the last one. The first usually brings in about the last 90 days, and pending "
        "transactions wait until they post. Add CSV exports for older history. Overlapping days aren't counted twice, "
        "and accounts it can't reach can still use files.")


def network_note(ctx: Context) -> str:
    if ctx.updates.get("supported") and ctx.updates.get("automatic"):
        return "When it opens, Budgetier asks GitHub whether a new version is out, and no financial data goes with that request."
    return "" if ctx.sync_connected else "Budgetier makes no network requests."


def bank_table(ctx: Context) -> QWidget:
    rows = [[widgets.Cell(bank, bold=True), widgets.Cell(kind, tone="dim"),
             widgets.Cell("Tested with real files" if tested else "Recognized, not yet tested", tone="pos" if tested else "dim")]
            for bank, kind, tested in BANKS]
    rows.append([widgets.Cell("Any other bank", bold=True),
                 widgets.Cell("CSV with date, description and amount columns", tone="dim"),
                 widgets.Cell("Usually works; you confirm on review", tone="dim")])
    return widgets.Table(["Bank", "File", "Status"], rows, ctx.tokens)


def build(ctx: Context) -> QWidget:
    steps = widgets.column(*(widgets.text(f"{i}. {lead} {rest}") for i, (lead, rest) in enumerate(STEPS, 1)))
    tips = widgets.column(*(widgets.column(widgets.text(title, "h3"), widgets.text(words), spacing=2) for title, words in TIPS),
                          spacing=theme.SPACE[3])
    kept = ("Your data is stored on this computer. Bank sync connects to SimpleFIN to fetch transactions, and nothing is "
            "sent to it except that request." if ctx.sync_connected else "Everything stays on this computer.")
    data = " ".join(p for p in (kept, network_note(ctx), "Removing a file keeps any transactions another file also covers. "
                                "Your data is kept apart from the program, so updating doesn't change it.") if p)
    tour_button = QPushButton("Take the tour")
    tour_button.setProperty("kind", "primary")
    tour_button.clicked.connect(lambda: tour.start(ctx.window))
    updates = []
    if ctx.updates.get("supported"):
        check = QPushButton("Check for updates")
        check.clicked.connect(lambda: ctx.window.updating.check_by_hand())
        automatic = ctx.updates.get("automatic")
        toggle = QPushButton("Stop checking automatically" if automatic else "Check automatically")
        toggle.clicked.connect(lambda: ctx.window.updating.set_automatic(not automatic))
        updates = [widgets.row(check, toggle)]
    return widgets.column(
        widgets.card(steps, widgets.row(tour_button) if ctx.snapshot.txns else None, title="Getting started",
                     note="Four steps. With files, repeat the first two whenever you want fresh numbers."),
        widgets.card(bank_table(ctx), title="Which banks work",
                     note="Budgetier reads columns by name, so it isn't limited to this list. If a bank is new to it, the "
                          "review screen asks what it can't tell."),
        widgets.card(widgets.text(SYNC), title="Bank sync"),
        widgets.card(tips, title="Tips for good numbers"),
        widgets.card(widgets.text(data), widgets.text(f"Budgetier version {ctx.version}" if ctx.version else "Budgetier", "dim"),
                     *updates, title="Your data"),
        spacing=theme.SPACE[4])
