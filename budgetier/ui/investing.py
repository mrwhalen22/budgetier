"""Checking what counts as paid into investing and retirement accounts.

Banks word these rows in many ways, so a contribution can be read as Investment Activity, and
then counted as growth. This lists them by name, under each category, and a change saves a
rule matching the bank's own wording, so new rows like it land in the right place too.
"""
from __future__ import annotations

from PySide6.QtWidgets import QWidget

from .. import analyze, views
from . import fmt, theme, widgets
from .dialogs import Dialog, attempt, busy
from .importing import scrolling
from .popup import Dropdown

LABELS = {analyze.CONTRIBUTED: "Paid in", analyze.WITHDRAWN: "Taken out", analyze.ACTIVITY: "Growth: dividends, trades, fees"}
LEAD = ("Paid in and taken out don't count as growth; dividends, trades and fees do. A change saves a rule, so new rows "
        "worded the same way go to the same place.")


SAFE_RULE = 6  # wording shorter than this could match unrelated rows elsewhere: "DIV" is in "DIVINE PIZZA"


def wordings(descriptions: list[str]) -> list[str]:
    """Text for rules covering each of these, in the bank's full wording rather than a name
    alone. Rules apply to every account, and "SCHWAB" alone would catch a Schwab card's
    purchases in checking too."""
    found: list[str] = []
    for description in descriptions:
        if not any(text in description.upper() for text in found):
            words = analyze.match_text("", [description]).split()
            while len(words) > 1 and any(c.isdigit() for c in words[-1]):  # a month or reference changes each time
                words.pop()
            found.append(" ".join(words))
    return found


def change(window, group: views.Grouped, category: str) -> int:
    """Rules for wording long enough to be safe, and the rest changed one row at a time.
    Returns how many rules and rows changed."""
    done = 0
    texts = wordings(group.descriptions)
    for text in (t for t in texts if len(t) >= SAFE_RULE):
        window.budget.save_rule(None, text, category, group.merchant)
        done += 1
    short = [t for t in texts if len(t) < SAFE_RULE]
    for tx in group.txns:
        if any(text in tx.description.upper() for text in short):
            window.budget.save_edit(views.edit_target(window.snapshot, tx), category, "")
            done += 1
    return done


def _choices(current: str) -> Dropdown:
    box = Dropdown()
    for category in analyze.INVESTING_CATEGORIES:
        box.addItem(LABELS[category], category)
    if box.findData(current) < 0:  # changed by hand to something else entirely: shown as it is
        box.addItem(current, current)
    box.setCurrentIndex(box.findData(current))
    return box


def review(window, ids: set[str] | None = None) -> Dialog | None:
    """ids: the accounts to check, or None for every investing and retirement account."""
    groups = views.investing_rows(window.snapshot, ids)
    if not groups:
        window.toast.say("There's nothing in those accounts to check yet.")
        return None
    dialog = Dialog(window, "Check what counts as paid in", LEAD)
    rows: list[tuple[views.Grouped, Dropdown]] = []
    lines: list[QWidget] = []
    heading = None
    for group in groups:
        if group.category != heading:
            heading = group.category
            lines.append(widgets.text(LABELS.get(heading, heading), "h3"))
        box = _choices(group.category)
        box.setAccessibleName(f"Category for {group.merchant}")
        about = widgets.column(widgets.text(group.merchant, "b"),
                               widgets.text(f"{fmt.plural(group.count, 'row')}, {fmt.cents(group.total)} · "
                                            f"{group.descriptions[0]}", "sub", wrap=False), spacing=0)
        line = widgets.row(about, box, spacing=theme.SPACE[3], stretch_last=True)
        line.layout().setStretch(0, 1)
        lines.append(line)
        rows.append((group, box))
    dialog.body.addWidget(scrolling(widgets.column(*lines, spacing=theme.SPACE[2])))
    dialog.rows = rows

    def save():
        changed = [(g, box.currentData()) for g, box in rows if box.currentData() != g.category]
        if not changed:
            dialog.dismiss()
            return

        def rules():
            return sum(change(window, group, category) for group, category in changed)

        def work():
            ok, result = attempt(window.budget.undoable, rules)
            if not ok:
                return dialog.show_error(str(result))
            dialog.dismiss()
            window.changed(f"Saved {fmt.plural(result, 'change')}.", undo=True)
        busy(dialog.main, "Saving...", work)

    dialog.set_buttons([("Cancel", dialog.dismiss, ""), ("Save", save, "primary")])
    dialog.open()
    return dialog
