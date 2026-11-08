"""Adding files: choose them, check what was read, then save.

Nothing is saved until Add files on the review. Reading happens off the window's thread,
because a PDF statement can take a while.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QGridLayout,
    QLineEdit,
    QRadioButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from . import fmt, theme, widgets
from .dialogs import Dialog, attempt, busy
from .popup import Dropdown

TYPES = (("checking", "Checking"), ("savings", "Savings"), ("credit", "Credit card"))
LIST_HEIGHT = 520  # the review scrolls past this


def field(label: str, editor: QWidget) -> QWidget:
    return widgets.column(widgets.text(label, "field"), editor, spacing=theme.SPACE[1])


def type_box(chosen: str, enabled: bool = True) -> Dropdown:
    box = Dropdown()
    box.setAccessibleName("Type")
    for value, label in TYPES:
        box.addItem(label, value)
    box.setCurrentIndex(max(box.findData(chosen), 0))
    box.setEnabled(enabled)
    return box


def scrolling(column: QWidget) -> QScrollArea:
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.NoFrame)
    scroll.setWidget(column)
    scroll.setMaximumHeight(LIST_HEIGHT)
    scroll.setMinimumHeight(min(LIST_HEIGHT, column.sizeHint().height() + 4))
    return scroll


def done_rows(lines: list[tuple[str, str]]) -> QWidget:
    rows = []
    for name, words in lines:
        line = widgets.row(widgets.text(name, "strong", wrap=False), widgets.text(words, "dim", wrap=False), stretch_last=True)
        line.layout().insertStretch(1, 1)
        rows.append(line)
    return widgets.column(*rows, spacing=theme.SPACE[2])


class FilePanel(QFrame):
    """One account found in a file, with what it needs answered."""

    def __init__(self, item: dict):
        super().__init__()
        self.item = item
        self.setProperty("kind", "panel")
        column = QVBoxLayout(self)
        column.setContentsMargins(*(theme.SPACE[4],) * 4)
        column.setSpacing(theme.SPACE[2])
        column.addWidget(widgets.text(item["file"], "h3"))
        span = f"{fmt.plural(item['count'], 'transaction')}, {fmt.day_name(item['first'])} to {fmt.day_name(item['last'])}"
        known = (f" · adds to {item['accountName']}: {item['new']:,} new, {item['count'] - item['new']:,} already here"
                 if item["known"] else " · new account")
        column.addWidget(widgets.text(span + known, "sub"))
        for note in item["notes"]:
            column.addWidget(widgets.text(note, "sub"))

        self.bank = QLineEdit(item["bank"])
        self.bank.setPlaceholderText("Bank name")
        self.bank.setAccessibleName("Bank")
        self.number = QLineEdit(item["number"])
        self.number.setMaxLength(4)
        self.number.setAccessibleName("Last 4 digits")
        self.type = type_box(item["type"], not item["known"])
        self.balance = None
        grid = QGridLayout()
        grid.setHorizontalSpacing(theme.SPACE[3])
        grid.addWidget(field("Bank", self.bank), 0, 0)
        grid.addWidget(field("Last 4 digits", self.number), 0, 1)
        grid.addWidget(field("Type", self.type), 0, 2)
        if not item["known"] and not item["hasBalance"]:
            self.balance = QLineEdit()
            self.balance.setPlaceholderText("For a card, what you owe")
            self.balance.setAccessibleName("Current balance, optional")
            grid.addWidget(field("Current balance, optional", self.balance), 0, 3)
        column.addLayout(grid)

        self.spent_yes = None
        if item["askSign"]:
            sample = item["sample"]
            column.addWidget(widgets.text(
                f"This file shows {sample['description']} on {fmt.day_name(sample['date'])} as "
                f"{fmt.cents(round(sample['amount'] * 100))}. Was that money you spent?"))
            self.spent_yes, no = QRadioButton("Yes"), QRadioButton("No")
            group = QButtonGroup(self)
            group.addButton(self.spent_yes)
            group.addButton(no)
            (self.spent_yes if item["spent"] else no).setChecked(True)
            column.addWidget(widgets.row(self.spent_yes, no))

    def answer(self) -> dict:
        return {"id": self.item["id"], "bank": self.bank.text(), "number": self.number.text(),
                "type": self.type.currentData(), "balance": self.balance.text() if self.balance else "",
                "spent": self.spent_yes.isChecked() if self.spent_yes else None}


class Importing:
    def __init__(self, window):
        self.window = window
        self.dialog: Dialog | None = None
        self.panels: list[FilePanel] = []

    @property
    def budget(self):
        return self.window.budget

    def add_files(self) -> None:
        paths = self.window.ask_files()
        if not paths:
            return
        reading = "Reading your file..." if len(paths) == 1 else f"Reading {len(paths)} files..."
        self.window.runner.start(self.budget.inspect, (paths,), self._read, reading)

    def _read(self, ok: bool, plan) -> None:
        if not ok:
            self.window.toast.say(str(plan))
            return
        self.review(plan)

    def review(self, plan: dict) -> Dialog:
        n = len(plan["items"])
        dialog = Dialog(self.window, "Review files",
                        "Check the details. Nothing is saved until you choose Add files." if n else "")
        self.dialog = dialog
        for error in plan["errors"]:
            dialog.body.addWidget(widgets.banner("warning", error["file"], f"couldn't be added: {error['error']}",
                                                 self.window.tokens()))
        self.panels = [FilePanel(item) for item in plan["items"]]
        if self.panels:
            dialog.body.addWidget(scrolling(widgets.column(*self.panels, spacing=theme.SPACE[3])))
        dialog.setMinimumWidth(640)
        buttons = [("Cancel" if n else "Close", self._cancel, "")]
        if n:
            buttons.append(("Add files", self._commit, "primary"))
        dialog.set_buttons(buttons)
        dialog.open()
        return dialog

    def _cancel(self) -> None:
        attempt(self.budget.cancel)  # lets go of the copies read for review
        self.dialog.dismiss()

    def _commit(self) -> None:
        dialog = self.dialog

        def work():
            ok, results = attempt(self.budget.commit, [p.answer() for p in self.panels])
            if not ok:
                return dialog.show_error(str(results))
            dialog.dismiss()
            self.done([(r["account"], f"{r['added']:,} new, {r['duplicates']:,} already here") for r in results])
        busy(dialog.main, "Adding...", work)

    def done(self, lines: list[tuple[str, str]]) -> Dialog:
        """What was added, then the window shows it."""
        dialog = Dialog(self.window, "Files added")
        dialog.body.addWidget(done_rows(lines))
        dialog.set_buttons([("Done", lambda: (dialog.dismiss(), self.window.changed()), "primary")])
        dialog.setAttribute(Qt.WA_DeleteOnClose)
        dialog.open()
        self.dialog = dialog
        return dialog
