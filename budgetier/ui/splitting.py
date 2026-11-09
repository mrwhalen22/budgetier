"""Splitting one transaction into parts with their own categories: a Costco trip that was part
groceries and part household, say. The parts must add up to the whole."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLineEdit, QPushButton, QVBoxLayout, QWidget

from .. import views
from ..parse import parse_money
from . import fmt, theme, widgets
from .dialogs import Dialog, attempt, busy
from .popup import Dropdown

MOST = 8  # parts in one split


class Part(QWidget):
    def __init__(self, categories: list[str], color, category: str = "", amount: str = "", removed=None):
        super().__init__()
        self.category = Dropdown(dot_for=lambda name: color(name) if name else None)
        self.category.setAccessibleName("Category")
        self.category.addItem("Choose a category", "")
        for name in categories:
            self.category.addItem(name, name)
        if category and self.category.findData(category) < 0:
            self.category.addItem(category, category)
        self.category.setCurrentIndex(max(self.category.findData(category), 0))
        self.amount = QLineEdit(amount)
        self.amount.setAccessibleName("Amount")
        self.amount.setPlaceholderText("0.00")
        self.amount.setAlignment(Qt.AlignRight)
        self.amount.setMaximumWidth(140)
        self.remove = QPushButton("Remove")
        self.remove.setProperty("kind", "small")
        self.remove.clicked.connect(lambda _=False: removed(self))
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(theme.SPACE[2])
        layout.addWidget(self.category, 1)
        layout.addWidget(self.amount)
        layout.addWidget(self.remove)

    def value(self) -> dict:
        return {"category": self.category.currentData() or "", "amount": self.amount.text()}


def split(window, tx: views.Tx) -> Dialog:
    s = window.snapshot
    whole = abs(tx.whole)
    dialog = Dialog(window, "Split this transaction",
                    f"{tx.merchant} on {fmt.day_name(tx.date)}, {fmt.cents(whole)}. Give each part a category and an "
                    "amount; together they need to come to the whole.")
    categories = views.rule_categories(s)
    color = window.context().color
    parts_box = QVBoxLayout()
    parts_box.setSpacing(theme.SPACE[2])
    holder = QWidget()
    holder.setLayout(parts_box)
    left = widgets.text("", "sub", wrap=False)
    add = QPushButton("Add a part")
    add.setProperty("kind", "small")
    parts: list[Part] = []

    def remaining() -> int | None:
        total = 0
        for part in parts:
            text = part.amount.text().strip()
            if text:
                cents = parse_money(text)
                if cents is None:
                    return None
                total += cents
        return whole - total

    def refresh() -> None:
        gap = remaining()
        if gap is None:
            left.setText("One of the amounts isn't a number yet.")
        elif gap == 0:
            left.setText("The parts come to the whole.")
        else:
            left.setText(f"{fmt.cents(abs(gap))} {'still to assign' if gap > 0 else 'more than the whole'}.")
        for part in parts:
            part.remove.setVisible(len(parts) > 2)  # a split needs two parts at least
        add.setEnabled(len(parts) < MOST)

    def removed(part: Part) -> None:
        parts.remove(part)
        parts_box.removeWidget(part)
        part.deleteLater()
        refresh()

    def new_part(category: str = "", amount: str = "") -> Part:
        part = Part(categories, color, category, amount, removed)
        part.amount.textChanged.connect(lambda _text: refresh())
        parts.append(part)
        parts_box.addWidget(part)
        return part

    def add_part() -> None:
        gap = remaining()
        part = new_part("", f"{gap / 100:.2f}" if gap and gap > 0 else "")
        part.category.setFocus()
        refresh()

    existing = [t for t in s.txns if tx.key and t.key == tx.key and t.split]
    if existing:
        for t in existing:
            new_part(t.category, f"{abs(t.cents) / 100:.2f}")
    else:
        new_part(tx.category, f"{whole / 100:.2f}")
        new_part("", "")
    add.clicked.connect(lambda _=False: add_part())
    dialog.body.addWidget(holder)
    dialog.body.addWidget(widgets.row(add, left, spacing=theme.SPACE[3]))
    dialog.parts = parts
    refresh()

    def save() -> None:
        def work():
            target = views.edit_target(s, tx)
            ok, result = attempt(window.budget.undoable, window.budget.save_split, target, tx.whole,
                                 [p.value() for p in parts])
            if not ok:
                return dialog.show_error(str(result))
            dialog.dismiss()
            window.changed(f"Split into {len([p for p in parts if p.value()['category']])} parts.", undo=True)
        busy(dialog.main, "Saving...", work)

    def unsplit() -> None:
        ok, result = attempt(window.budget.undoable, window.budget.clear_split, views.edit_target(s, tx))
        if not ok:
            return dialog.show_error(str(result))
        dialog.dismiss()
        window.changed("It's one transaction again.", undo=True)

    dialog.set_buttons([("Cancel", dialog.dismiss, ""), *([("Undo split", unsplit, "")] if existing else []),
                        ("Save", save, "primary")])
    dialog.open()
    return dialog
