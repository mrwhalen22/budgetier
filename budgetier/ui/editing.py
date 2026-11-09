"""Changing categories: one transaction, a rule for everything like it, and working through
the merchants that still need one.

Working through a list shouldn't redraw the window per merchant, so the queue keeps the data
it started with, and asks before each merchant whether a rule just saved has covered it.
"""
from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QButtonGroup, QFrame, QGridLayout, QLineEdit, QRadioButton, QVBoxLayout, QWidget

from .. import analyze, views
from . import fmt, theme, widgets
from .dialogs import Dialog, attempt, busy, confirm
from .popup import Dropdown

JUST_THIS = "Changes only this transaction. Rules won't change it again."
EVERYTHING = "Applies to every matching transaction, past and future."
COVERED = "A rule already covers this transaction. Changes apply to everything it matches."
NEW = "__new"
PREVIEW_WAIT = 180  # milliseconds after typing stops


def code_font() -> QFont:
    font = QFont("Cascadia Mono")
    font.setStyleHint(QFont.Monospace)
    return font


class RuleDialog(Dialog):
    """Categorize a merchant or a transaction, or edit a rule. o holds what to start from:
    text, merchant, category, and maybe desc (the bank's wording), tx, line and advanced."""

    def __init__(self, parent: QWidget, editing: Editing):
        super().__init__(parent, "Categorize")
        self.editing = editing
        self.o: dict = {}
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.preview)

        self.scope_box = QWidget()
        self.all = QRadioButton("Everything that matches")
        self.one = QRadioButton("Just this transaction")
        group = QButtonGroup(self.scope_box)
        group.addButton(self.all)
        group.addButton(self.one)
        scope = QVBoxLayout(self.scope_box)
        scope.setContentsMargins(0, 0, 0, 0)
        scope.addWidget(self.all)
        scope.addWidget(self.one)
        self.one.toggled.connect(self._scope)

        self.desc_box = QWidget()
        self.desc = widgets.text("", "code")
        self.desc.setFont(code_font())
        desc = QVBoxLayout(self.desc_box)
        desc.setContentsMargins(0, 0, 0, 0)
        desc.setSpacing(theme.SPACE[1])
        desc.addWidget(widgets.text("The bank's description", "field"))
        desc.addWidget(self.desc)

        self.match = QLineEdit()
        self.match.setAccessibleName("When the bank's description contains")
        self.match.textEdited.connect(lambda _: self.timer.start(PREVIEW_WAIT))
        self.match_box = self._field("When the bank's description contains", self.match)
        self.name = QLineEdit()
        self.name.setPlaceholderText("Name to display")
        self.name.setAccessibleName("Show as")
        self.category = Dropdown()
        self.category.setAccessibleName("Category")
        self.category.activated.connect(self._category_chosen)
        self.new = QLineEdit()
        self.new.setAccessibleName("New category name")
        self.new_box = self._field("New category name", self.new)

        grid = QGridLayout()
        grid.setHorizontalSpacing(theme.SPACE[3])
        grid.setVerticalSpacing(theme.SPACE[2])
        grid.addWidget(self.desc_box, 0, 0, 1, 2)
        grid.addWidget(self.match_box, 1, 0, 1, 2)
        grid.addWidget(self._field("Show as", self.name), 2, 0)
        grid.addWidget(self._field("Category", self.category), 2, 1)
        grid.addWidget(self.new_box, 3, 0, 1, 2)

        self.panel = QFrame()
        self.panel.setProperty("kind", "panel")
        self.panel_words = QVBoxLayout(self.panel)
        self.panel_words.setContentsMargins(*(theme.SPACE[3],) * 4)
        self.panel_words.setSpacing(theme.SPACE[1])

        self.body.addWidget(self.scope_box)
        self.body.addLayout(grid)
        self.body.addWidget(self.panel)

    @staticmethod
    def _field(label: str, field: QWidget) -> QWidget:
        return widgets.column(widgets.text(label, "field"), field, spacing=theme.SPACE[1])

    # ---- filling it in

    def load(self, o: dict, lead: str, buttons: list) -> None:
        self.o = o
        tx, editing_rule = o.get("tx"), o.get("line")
        title = "Edit rule" if editing_rule else "Categorize"
        self.setWindowTitle(title)
        self.heading.setText(title)
        self.scope_box.setVisible(tx is not None)
        (self.one if tx is not None and tx.edited else self.all).setChecked(True)
        self.desc_box.setVisible(bool(o.get("desc")))
        self.desc.setText(o.get("desc", ""))
        self.match.setText(o.get("text", ""))
        self.match.setFont(code_font() if o.get("advanced") else QFont())
        self.name.setText(o.get("merchant", ""))
        names = views.rule_categories(self.editing.snapshot)
        self.category.clear()
        self.category.addItem("Choose...", "")
        for name in names:
            self.category.addItem(name, name)
        self.category.addItem("New category...", NEW)
        chosen = o.get("category", "")
        if chosen and chosen not in names:
            self.category.setCurrentIndex(self.category.findData(NEW))
            self.new.setText(chosen)
        else:
            self.category.setCurrentIndex(max(self.category.findData(chosen), 0))
            self.new.setText("")
        self.new_box.setVisible(self.category.currentData() == NEW)
        self.lead_words = lead
        self.show_error("")
        self.set_buttons(buttons)
        self._scope()
        self.preview()

    def just_this(self) -> bool:
        return self.scope_box.isVisibleTo(self) and self.one.isChecked()

    def _scope(self) -> None:
        alone = self.just_this()
        self.match_box.setVisible(not alone)
        self.panel.setVisible(not alone)
        self.set_lead(JUST_THIS if alone else self.lead_words)

    def _category_chosen(self, _index: int) -> None:
        self.new_box.setVisible(self.category.currentData() == NEW)
        if self.category.currentData() == NEW:
            self.new.setFocus()
        self.preview()

    def chosen_category(self) -> str:
        return self.new.text() if self.category.currentData() == NEW else self.category.currentData() or ""

    # ---- what a rule would match

    def _say(self, *lines: tuple[str, str]) -> None:
        while self.panel_words.count():
            item = self.panel_words.takeAt(0)
            item.widget().deleteLater()
        for words, kind in lines:
            self.panel_words.addWidget(widgets.text(words, kind))
        self.panel.setVisible(bool(lines) and not self.just_this())

    def preview(self) -> None:
        self.timer.stop()
        text = self.match.text()
        if not text.strip():
            self._say()
            return
        ok, found = attempt(self.editing.budget.preview_rule, text, bool(self.o.get("advanced")))
        if not ok:
            self._say((str(found), "panel-text"))
            return
        if not found["count"]:
            self._say(("No transactions match yet.", "b"),
                      ("Rules look for this exact text in the bank's description, which can differ from the name shown. "
                       "Select a row on the Transactions tab to start from the bank's wording.", "panel-text"))
            return
        n = found["count"]
        lines = [(f"{fmt.plural(n, 'transaction')} {'matches' if n == 1 else 'match'}, totalling "
                  f"{fmt.cents(round(found['total'] * 100))}.", "b")]
        if found["share"] > .25:
            lines.append(("That is a lot of your history. Try more specific text.", "warn"))
        if self.chosen_category() == "Transfer":
            lines.append(("Transfers don't count as spending or income.", "warn"))
        lines += [(f"•  {example}", "code") for example in found["examples"]]
        self._say(*lines)


class Editing:
    """The window's changes to categories, and the queue of merchants needing one."""

    def __init__(self, window):
        self.window = window
        self.queue: dict | None = None
        self.dialog: RuleDialog | None = None

    @property
    def budget(self):
        return self.window.budget

    @property
    def snapshot(self) -> views.Snapshot:
        return self.window.snapshot

    def _suggestion(self, merchant: str, description: str) -> dict:
        """The rule already covering this description, or text to start a new one from."""
        wording = list(dict.fromkeys([description] + [t.description for t in self.snapshot.txns if t.merchant == merchant]))
        ok, found = attempt(self.budget.suggest_rule, merchant, wording)
        return found if ok else {}

    # ---- starting

    def categorize(self, tx: views.Tx) -> None:
        found = self._suggestion(tx.merchant, tx.description)
        if found.get("rule"):
            mine = {"merchant": tx.merchant, "category": tx.category} if tx.edited else {}
            self._open({**found["rule"], "desc": tx.description, "tx": tx, **mine})
        else:
            self._open({"text": found.get("text", ""), "merchant": tx.merchant, "desc": tx.description, "tx": tx,
                        "category": "" if tx.category == analyze.UNCATEGORIZED else tx.category})

    def new_rule(self) -> None:
        self._open({"text": "", "merchant": "", "category": ""})

    def edit_rule(self, rule: dict) -> None:
        self._open(dict(rule))

    def remove_rule(self, rule: dict) -> None:
        confirm(self.window, "Remove this rule?",
                f'Transactions matching "{rule["text"]}" go back to their automatic category. You can add the rule again '
                "any time.", lambda: attempt(self.budget.undoable, self.budget.delete_rule, rule["line"]),
                done=lambda _: self.window.changed("Removed.", undo=True))

    def start_queue(self, merchant: str) -> None:
        items = views.uncategorized(self.snapshot)
        at = next((i for i, u in enumerate(items) if u.merchant == merchant), 0)
        self.queue = {"items": items, "at": at, "saved": 0, "note": ""}
        self._next()

    # ---- the dialog

    def _form(self) -> RuleDialog:
        if self.dialog is None:
            self.dialog = RuleDialog(self.window, self)
            self.dialog.finished.connect(self._closed)
        return self.dialog

    def _closed(self, _result: int) -> None:
        self.dialog = None
        self.queue = None

    def _open(self, o: dict) -> None:
        dialog = self._form()
        if o.get("line"):
            lead = COVERED if o.get("desc") else ""
        else:
            lead = EVERYTHING
        if self.queue:
            q = self.queue
            place = f"{q['at'] + 1} of {len(q['items'])}"
            lead = f"{q['note']} {place}." if q["note"] else f"{place}. {lead}"
            more = q["at"] + 1 < len(q["items"])
            buttons = [("Done" if q["saved"] else "Cancel", self._end_queue, ""),
                       *([("Skip", self._skip, "")] if more else []),
                       ("Save and next" if more else "Save", self._save, "primary")]
        else:
            tx = o.get("tx")
            buttons = [("Cancel", dialog.dismiss, ""),
                       *([("Undo change", self._clear_edit, "")] if tx is not None and tx.edited and not tx.split else []),
                       *([("Change split" if tx.split else "Split", lambda: self._split(tx), "")] if tx is not None else []),
                       *([("Edit note" if tx.note or tx.tags else "Add note", lambda: self._note(tx), "")]
                         if tx is not None else []),
                       ("Save", self._save, "primary")]
        dialog.load(o, lead, buttons)
        if not dialog.isVisible():
            dialog.open()
        if self.queue:
            dialog.category.setFocus()

    def _next(self) -> None:
        q = self.queue
        while q["at"] < len(q["items"]):
            item = q["items"][q["at"]]
            found = self._suggestion(item.merchant, item.description)
            if found.get("rule") and q["saved"]:  # a rule just saved covers this one
                q["at"] += 1
                continue
            if found.get("rule"):
                self._open({**found["rule"], "desc": item.description})
            else:
                self._open({"text": found.get("text", ""), "merchant": item.merchant, "category": "",
                            "desc": item.description})
            return
        self._end_queue()

    def _skip(self) -> None:
        self.queue["at"] += 1
        busy(self.dialog.buttons[1], "Skipping...", self._next)

    def _end_queue(self) -> None:
        saved = self.queue["saved"] if self.queue else 0
        self.queue = None
        if self.dialog is not None:
            self.dialog.accept()
        if saved:
            self.window.changed(f"Saved {fmt.plural(saved, 'rule')}.")

    # ---- saving

    def _save(self) -> None:
        dialog = self.dialog
        busy(dialog.main, "Saving...", lambda: self._saving(dialog))

    def _saving(self, dialog: RuleDialog) -> None:
        o, category, merchant = dialog.o, dialog.chosen_category(), dialog.name.text()
        if dialog.just_this():
            ok, result = attempt(self.budget.undoable, self.budget.save_edit, views.edit_target(self.snapshot, o["tx"]),
                                 category, merchant)
            if not ok:
                return dialog.show_error(str(result))
            dialog.accept()
            return self.window.changed("Saved. Nothing else changed.", undo=True)
        ok, result = attempt(self.budget.undoable, self.budget.save_rule, o.get("line") or None, dialog.match.text(),
                             category, merchant, bool(o.get("advanced")))
        if not ok:
            return dialog.show_error(str(result))
        matched = fmt.plural(result["count"], "transaction")
        if not self.queue:
            dialog.accept()
            return self.window.changed(f"Rule saved. It matches {matched}.", undo=True)
        q = self.queue
        q["saved"] += 1
        q["at"] += 1
        q["note"] = f"Saved. That rule matches {matched}."
        self._next()

    def _split(self, tx: views.Tx) -> None:
        """Into parts with their own categories, in a dialog of its own."""
        from .splitting import split
        self.dialog.dismiss()
        split(self.window, tx)

    def _note(self, tx: views.Tx) -> None:
        """A note and tags, in a dialog of their own."""
        from .noting import note
        self.dialog.dismiss()
        note(self.window, tx)

    def _clear_edit(self) -> None:
        dialog = self.dialog

        def work():
            ok, result = attempt(self.budget.undoable, self.budget.clear_edit, views.edit_target(self.snapshot, dialog.o["tx"]))
            if not ok:
                return dialog.show_error(str(result))
            dialog.accept()
            self.window.changed("Change undone.", undo=True)
        busy(dialog.buttons[1], "Working...", work)
