"""What a tab is drawn from: the data, the chosen period and accounts, the colors, and what it
can ask the window to do."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from .. import views


@dataclass
class Context:
    snapshot: views.Snapshot
    choice: views.Choice
    tokens: dict[str, str]
    open_transactions: Callable[..., None]  # category="", query=""
    choose_range: Callable[[str], None]
    redraw: Callable[[], None]  # draw the tab again, after a toggle on it changes
    options: dict = field(default_factory=dict)  # a tab's own toggles, kept while the window is open
    version: str = ""
    sync_connected: bool = False
    updates: dict = field(default_factory=dict)
    edit: object = None  # the window's Editing: categorize a transaction, start the queue, change rules
    window: object = None  # for changes that open dialogs: adding files, accounts, bank sync

    def color(self, category: str) -> str:
        """The top categories over all history keep one color each, under any filter."""
        colored = self.snapshot.colored
        return self.tokens[f"c{colored.index(category)}"] if category in colored else self.tokens["other"]

    def toggle(self, name: str) -> Callable[[bool], None]:
        def changed(on: bool) -> None:
            self.options[name] = on
            self.redraw()
        return changed
