"""A note on one transaction, and tags that gather it with others: "reimbursed by work" on a
hotel bill, or "Japan trip" on everything a trip cost, whatever its category."""
from __future__ import annotations

from PySide6.QtWidgets import QLineEdit, QPlainTextEdit, QPushButton

from .. import analyze, views
from . import fmt, theme, widgets
from .dialogs import Dialog, attempt, busy
from .importing import field

SUGGESTED = 8  # tags used before, shown to pick from


def note(window, tx: views.Tx) -> Dialog:
    s = window.snapshot
    dialog = Dialog(window, "Note and tags",
                    f"{tx.merchant} on {fmt.day_name(tx.date)}, {fmt.cents(tx.whole)}. Tags gather transactions across "
                    "categories, so you can see what a trip or a project cost. Search #tag on Transactions to list them.")
    words = QPlainTextEdit(tx.note)
    words.setAccessibleName("Note")
    words.setPlaceholderText("Reimbursed by work")
    words.setFixedHeight(theme.px(72))
    tags = QLineEdit(", ".join(tx.tags))
    tags.setAccessibleName("Tags")
    tags.setPlaceholderText("Japan trip, Kitchen remodel")
    dialog.body.addWidget(field("Note", words))
    dialog.body.addWidget(field("Tags, separated by commas", tags))
    used = [t for t in views.all_tags(s) if t.lower() not in {x.lower() for x in tx.tags}][:SUGGESTED]
    if used:
        def add(tag: str) -> None:
            have = analyze.read_tags(tags.text())
            tags.setText(", ".join([*have, tag]))
        buttons = []
        for tag in used:
            button = QPushButton(tag)
            button.setProperty("kind", "small")
            button.clicked.connect(lambda _=False, tag=tag: add(tag))
            buttons.append(button)
        dialog.body.addWidget(widgets.column(widgets.text("Used before", "field"),
                                             widgets.row(*buttons, spacing=theme.SPACE[1]), spacing=theme.SPACE[1]))
    dialog.note_fields = {"note": words, "tags": tags}

    def save() -> None:
        def work():
            ok, result = attempt(window.budget.undoable, window.budget.save_note, views.edit_target(s, tx),
                                 words.toPlainText(), tags.text())
            if not ok:
                return dialog.show_error(str(result))
            dialog.dismiss()
            cleared = not words.toPlainText().strip() and not analyze.read_tags(tags.text())
            window.changed("Note removed." if cleared else "Note saved.", undo=True)
        busy(dialog.main, "Saving...", work)

    dialog.set_buttons([("Cancel", dialog.dismiss, ""), ("Save", save, "primary")])
    dialog.open()
    words.setFocus()
    return dialog
