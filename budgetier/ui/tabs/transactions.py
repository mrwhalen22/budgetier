"""Transactions: search, filter and sort everything in the period. Select a row to change it."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLineEdit, QPushButton, QVBoxLayout, QWidget

from ... import export, views
from .. import fmt, theme, widgets
from ..context import Context
from ..popup import Dropdown

FIRST, MORE = 200, 500  # rows shown at first, and added by Show more
COLUMNS = (("date", "Date"), ("merchant", "Merchant"), ("category", "Category"), ("account", "Account"), ("amount", "Amount"))


def fresh() -> dict:
    return {"query": "", "category": "", "kind": "", "sort": "date", "descending": True, "shown": FIRST}


class Transactions(QWidget):
    def __init__(self, ctx: Context):
        super().__init__()
        self.ctx = ctx
        self.state = ctx.options.setdefault("transactions", fresh())
        s = ctx.snapshot

        self.query = QLineEdit(self.state["query"])
        self.query.setPlaceholderText("Search merchant or description")
        self.query.setAccessibleName("Search transactions")
        self.query.setObjectName("search")  # Ctrl+F comes here
        self.query.setClearButtonEnabled(True)
        self.query.textChanged.connect(lambda words: self._change(query=words))
        self.category = Dropdown(dot_for=lambda name: ctx.color(name) if name else None)
        self.category.setAccessibleName("Category")
        self.category.addItem("All categories", "")
        for name in views.category_filter(s):
            self.category.addItem(name, name)
        if self.category.findData(self.state["category"]) < 0:  # asked for from elsewhere, with nothing in it yet
            self.category.addItem(self.state["category"], self.state["category"])
        self.category.setCurrentIndex(self.category.findData(self.state["category"]))
        self.category.activated.connect(lambda i: self._change(category=self.category.itemData(i)))
        self.kind = Dropdown()
        self.kind.setAccessibleName("Kind")
        for value, label in views.KINDS:
            self.kind.addItem(label, value)
        self.kind.setCurrentIndex(self.kind.findData(self.state["kind"]))
        self.kind.activated.connect(lambda i: self._change(kind=self.kind.itemData(i)))
        self.clear = QPushButton("Clear filters")
        self.clear.clicked.connect(self._clear)
        self.export = QPushButton("Export CSV")
        self.export.setToolTip("Save the transactions listed here, all of them, as a CSV file")
        self.export.clicked.connect(self._export)
        controls = widgets.row(self.query, self.category, self.kind, self.clear, self.export, stretch_last=True)
        controls.layout().setStretch(0, 1)

        self.count = widgets.text("", "dim")
        hint = widgets.text("Select a row to change it, or everything like it.", "sub")
        self.listing = QVBoxLayout()
        self.listing.setContentsMargins(0, 0, 0, 0)
        holder = QWidget()
        holder.setLayout(self.listing)
        self.more = QPushButton("Show more")
        self.more.clicked.connect(lambda: self._change(shown=self.state["shown"] + MORE, keep_shown=True))
        column = QVBoxLayout(self)
        column.setContentsMargins(0, 0, 0, 0)
        column.addWidget(widgets.card(controls, self.count, hint, holder, self.more))
        self.table: widgets.Table | None = None
        self.refresh()

    # ---- the filters

    def _change(self, keep_shown: bool = False, **changes) -> None:
        self.state.update(changes)
        if not keep_shown:
            self.state["shown"] = FIRST
        self.refresh()

    def _clear(self) -> None:
        self.state.update(fresh())
        self.query.blockSignals(True)
        self.query.setText("")
        self.query.blockSignals(False)
        self.category.setCurrentIndex(0)
        self.kind.setCurrentIndex(0)
        self.refresh()

    def _export(self) -> None:
        """What's listed, with every filter applied, not only the rows shown so far."""
        window = self.ctx.window
        path = window.ask_csv_path(f"Budgetier {views.range_label(self.ctx.snapshot, self.ctx.choice)}.csv")
        if not path:
            return
        names = {a.id: a.name for a in self.ctx.snapshot.accounts}
        try:
            export.write_csv(Path(path), self.found, names)
        except PermissionError:
            window.toast.say("That file is open in another program. Close it and try again.")
            return
        except OSError as e:
            window.toast.say(f"That file couldn't be saved: {e.strerror or e}.")
            return
        window.toast.say(f"Saved {fmt.plural(len(self.found), 'transaction')} to {Path(path).name}.")

    def _sort(self, column: int) -> None:
        key = COLUMNS[column][0]
        if self.state["sort"] == key:
            self.state["descending"] = not self.state["descending"]
        else:
            self.state.update(sort=key, descending=key == "date")
        self.refresh()
        self.table.horizontalHeader().setFocus()

    # ---- the list

    def refresh(self) -> None:
        st, ctx = self.state, self.ctx
        found = views.transactions(ctx.snapshot, ctx.choice, st["query"], st["category"], st["kind"], st["sort"],
                                   st["descending"])
        self.found = found.txns
        self.count.setText(f"{len(found.txns):,} transactions, net {fmt.cents(found.net)}")
        self.clear.setVisible(bool(st["query"] or st["category"] or st["kind"]))
        names = {a.id: a.name for a in ctx.snapshot.accounts}
        shown = found.txns[:st["shown"]]
        rows = [[widgets.Cell(fmt.day_name(t.date), tone="dim", tip=t.description),
                 widgets.Cell(t.merchant, icon=widgets.mono_icon(t.merchant, ctx.color(t.category)), tip=t.description,
                              bold=True),
                 widgets.Cell(t.category + ("  ·  edited" if t.edited else ""), icon=widgets.dot_icon(ctx.color(t.category))),
                 widgets.Cell(names.get(t.account, ""), tone="dim"),
                 widgets.Cell(("+" if t.cents > 0 else "") + fmt.cents(t.cents), right=True, tone=fmt.gain(t.cents))]
                for t in shown]
        if self.table is not None:
            self.listing.removeWidget(self.table)
            self.table.deleteLater()
        self.table = widgets.Table([label for _, label in COLUMNS], rows, ctx.tokens,
                                   on_row=lambda r: ctx.edit.categorize(self.found[r]), numeric={4})
        self.table.setAccessibleName("Transactions")
        header = self.table.horizontalHeader()
        header.setSectionsClickable(True)
        header.setSortIndicatorShown(True)
        column = [key for key, _ in COLUMNS].index(st["sort"])
        header.setSortIndicator(column, Qt.DescendingOrder if st["descending"] else Qt.AscendingOrder)
        header.sectionClicked.connect(self._sort)
        self.listing.addWidget(self.table)
        if not found.txns:
            self.table.hide()
        self.empty = getattr(self, "empty", None)
        if self.empty is None:
            self.empty = widgets.empty("No transactions match.")
            self.listing.addWidget(self.empty)
        self.empty.setVisible(not found.txns)
        self.more.setVisible(len(found.txns) > st["shown"])


def build(ctx: Context) -> QWidget:
    if not ctx.snapshot.txns:
        from .overview import welcome
        return welcome(ctx)
    page = Transactions(ctx)
    page.layout().setSpacing(theme.SPACE[4])
    return page
