"""The Qt window: a sidebar of tabs beside the tab that's showing.

This is the move described in docs/qt-migration.md. Until the move is done the desktop app
still opens the page, and this window opens only from the command line:

    python -m budgetier.ui [--home FOLDER]
"""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QStandardItemModel
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenu,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .. import views
from ..service import Budget, app_version
from . import icons, theme, widgets
from .context import Context
from .tabs import BUILDERS

# The order the sidebar lists them in, as on the page.
TABS = ("Overview", "Spending", "Budgets", "Recurring", "Largest", "Savings", "Transactions", "Rules", "Accounts", "Help")
# Which step of docs/qt-migration.md brings each tab, until it's here.
COMING = {"Transactions": 4, "Rules": 4, "Accounts": 5, "Budgets": 6}
# These cover all of history, so the period and account filters don't apply.
FULL_HISTORY = {"Budgets", "Recurring", "Accounts", "Rules", "Help"}
SIDE_WIDTH = 232
ICON = 18


def _placeholder(tab: str, note: str = "") -> QWidget:
    words = [widgets.text(f"The {tab} tab arrives in step {COMING[tab]} of the move to Qt.", "dim")]
    if note:
        words.append(widgets.text(note, "dim"))
    return widgets.card(*words, title=tab)


class StayOpenMenu(QMenu):
    """Ticking an account shouldn't close the list, so several can be changed at once."""

    def mouseReleaseEvent(self, event):  # noqa: N802 - Qt's name
        action = self.actionAt(event.position().toPoint())
        if action is not None and action.isCheckable():
            action.trigger()
            return
        super().mouseReleaseEvent(event)


class Window(QMainWindow):
    def __init__(self, budget: Budget, look: theme.Look | None = None):
        super().__init__()
        self.budget = budget
        self.look = look or theme.load_look(budget.home)
        self.choice = views.Choice()
        self.options: dict = {}
        self.transactions_asked: dict = {}  # what a drill-down asked Transactions to show
        self._ready = False  # draw nothing until the window is built
        self.setWindowTitle("Budgetier")
        self.resize(1340, 900)
        self.setMinimumSize(900, 620)

        central = QWidget()
        row = QHBoxLayout(central)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        row.addWidget(self._side())
        row.addWidget(self._content(), 1)
        self.setCentralWidget(central)

        hints = QApplication.instance().styleHints()
        hints.colorSchemeChanged.connect(lambda _scheme: self.restyle())
        self.mode = theme.mode_for(self.look, False)
        self.reload()
        self.restyle()
        self._ready = True
        self.show_tab(TABS[0])
        self.stack.setFocus()  # not the first tab's button, which would show a focus ring at once

    # ---- building

    def _side(self) -> QFrame:
        side = QFrame()
        side.setObjectName("side")
        side.setFixedWidth(SIDE_WIDTH)
        column = QVBoxLayout(side)
        column.setContentsMargins(theme.SPACE[3], theme.SPACE[5], theme.SPACE[3], theme.SPACE[4])
        column.setSpacing(2)

        brand = QHBoxLayout()
        brand.setContentsMargins(theme.SPACE[2], 0, theme.SPACE[2], theme.SPACE[5])
        brand.setSpacing(theme.SPACE[2])
        self.brand_mark = QLabel()
        self.brand_mark.setAccessibleName("Budgetier")
        name = QLabel("Budgetier")
        name.setObjectName("brand")
        brand.addWidget(self.brand_mark)
        brand.addWidget(name, 1)
        column.addLayout(brand)

        self.tab_group = QButtonGroup(self)
        self.tab_group.setExclusive(True)
        self.tab_buttons: dict[str, QPushButton] = {}
        for tab in TABS:
            button = QPushButton(tab)
            button.setProperty("kind", "nav")
            button.setCheckable(True)
            button.setIconSize(QSize(ICON, ICON))
            button.setAccessibleName(tab)
            button.setCursor(Qt.PointingHandCursor)
            button.setFocusPolicy(Qt.TabFocus)  # a click shouldn't leave a focus ring, as on the page
            button.clicked.connect(lambda _checked=False, tab=tab: self.show_tab(tab))
            self.tab_group.addButton(button)
            self.tab_buttons[tab] = button
            column.addWidget(button)

        column.addStretch(1)
        self.foot = widgets.text("", wrap=True)
        self.foot.setObjectName("foot")
        column.addWidget(self.foot)
        return side

    def _filters(self) -> QWidget:
        self.range_box = QComboBox()
        self.range_box.setAccessibleName("Period")
        self.range_box.activated.connect(self._range_chosen)
        self.accounts_button = QToolButton()
        self.accounts_button.setProperty("kind", "picker")
        self.accounts_button.setAccessibleName("Accounts")
        self.accounts_button.setPopupMode(QToolButton.InstantPopup)
        self.accounts_menu = StayOpenMenu(self.accounts_button)
        self.accounts_button.setMenu(self.accounts_menu)
        box = widgets.row(self.range_box, self.accounts_button, stretch_last=True)
        box.setObjectName("filters")
        return box

    def _content(self) -> QWidget:
        content = QWidget()
        content.setObjectName("content")
        column = QVBoxLayout(content)
        gutter = theme.SPACE[8]
        column.setContentsMargins(gutter, theme.SPACE[5], gutter, 0)
        column.setSpacing(theme.SPACE[3])

        header = QHBoxLayout()
        words = QVBoxLayout()
        words.setSpacing(2)
        self.title = QLabel()
        self.title.setObjectName("title")
        self.subtitle = widgets.text("")
        self.subtitle.setObjectName("subtitle")
        words.addWidget(self.title)
        words.addWidget(self.subtitle)
        header.addLayout(words, 1)
        self.filters = self._filters()
        header.addWidget(self.filters, 0, Qt.AlignVCenter)
        column.addLayout(header)

        self.stack = QStackedWidget()
        self.stack.setObjectName("view")
        self.stack.setFocusPolicy(Qt.ClickFocus)
        self.pages: dict[str, QScrollArea] = {}
        for tab in TABS:
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.NoFrame)
            self.stack.addWidget(scroll)
            self.pages[tab] = scroll
        column.addWidget(self.stack, 1)
        return content

    # ---- the data and the filters

    def reload(self) -> None:
        """Read the data folder again, after anything changes it."""
        self.snapshot = views.from_budget(self.budget)
        ids = {a.id for a in self.snapshot.accounts}
        if self.choice.accounts is not None:
            kept = self.choice.accounts & ids
            self.choice = views.Choice(self.choice.range, kept if kept != ids else None)
        values = [value for _, value, _ in views.range_options(self.snapshot)]
        if self.choice.range not in values:
            self.choice = views.Choice("12", self.choice.accounts)
        self._fill_filters()
        s = self.snapshot
        through = f"Data through {views.day_name(s.end)}. " if s.txns else ""
        stays = "Stored on this computer." if self.budget.sync.status()["connected"] else "Stays on this computer."
        version = f" Version {app_version()}." if app_version() else ""
        self.foot.setText(through + stays + version)
        if self._ready:
            self.render()

    def _fill_filters(self) -> None:
        box = self.range_box
        box.blockSignals(True)
        box.clear()
        model: QStandardItemModel = box.model()
        group = None
        for name, value, label in views.range_options(self.snapshot):
            if name != group:
                if group is not None:
                    box.insertSeparator(box.count())
                box.addItem(name)
                model.item(box.count() - 1).setEnabled(False)  # a heading, as the page's list had
                group = name
            box.addItem(label, value)
        box.setCurrentIndex(box.findData(self.choice.range))
        box.blockSignals(False)

        menu = self.accounts_menu
        menu.clear()
        self.account_actions = {}
        for account in self.snapshot.accounts:
            action = menu.addAction(account.name)
            action.setCheckable(True)
            action.setChecked(self.choice.has(account.id))
            action.toggled.connect(self._accounts_chosen)
            self.account_actions[account.id] = action
        self._label_accounts()

    def _label_accounts(self) -> None:
        total = len(self.snapshot.accounts)
        chosen = total if self.choice.accounts is None else len(self.choice.accounts)
        self.accounts_button.setText("All accounts" if chosen == total else f"{chosen} of {total} accounts")

    def _range_chosen(self, index: int) -> None:
        value = self.range_box.itemData(index)
        if value:
            self.choose(views.Choice(value, self.choice.accounts))

    def _accounts_chosen(self, _on: bool = False) -> None:
        chosen = frozenset(a for a, action in self.account_actions.items() if action.isChecked())
        self.choose(views.Choice(self.choice.range, None if chosen == frozenset(self.account_actions) else chosen))

    def choose(self, choice: views.Choice) -> None:
        self.choice = choice
        self.range_box.setCurrentIndex(self.range_box.findData(choice.range))
        for account, action in getattr(self, "account_actions", {}).items():
            action.blockSignals(True)
            action.setChecked(choice.has(account))
            action.blockSignals(False)
        self._label_accounts()
        self.render()

    def choose_range(self, value: str) -> None:
        self.choose(views.Choice(value, self.choice.accounts))

    # ---- what the window does

    @property
    def tab(self) -> str:
        return TABS[self.stack.currentIndex()]

    def show_tab(self, tab: str) -> None:
        self.stack.setCurrentWidget(self.pages[tab])
        self.title.setText(tab)
        self.tab_buttons[tab].setChecked(True)
        self.render()

    def open_transactions(self, category: str = "", query: str = "") -> None:
        """A category or merchant selected elsewhere shows its transactions."""
        self.transactions_asked = {"category": category, "query": query}
        self.show_tab("Transactions")

    def context(self) -> Context:
        status = self.budget.updates.status()
        return Context(self.snapshot, self.choice, theme.tokens(self.mode, self.look.palette), self.open_transactions,
                       self.choose_range, self.render, self.options, app_version(),
                       self.budget.sync.status()["connected"], status)

    def render(self) -> None:
        """Draw the tab that's showing, from the data and filters as they are now."""
        if not self._ready:
            return
        tab = self.tab
        full = tab in FULL_HISTORY
        self.filters.setVisible(not full and bool(self.snapshot.txns))
        self.subtitle.setText("All history" if full else views.range_label(self.snapshot, self.choice))
        if tab in BUILDERS:
            body = BUILDERS[tab](self.context())
        else:
            asked = self.transactions_asked if tab == "Transactions" else {}
            note = " and ".join(f"{k} {v!r}" for k, v in asked.items() if v)
            body = _placeholder(tab, f"Asked to show {note}." if note else "")
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, theme.SPACE[2], 0, theme.SPACE[10])
        layout.addWidget(body)
        layout.addStretch(1)
        old = self.pages[tab].takeWidget()
        self.pages[tab].setWidget(page)
        if old is not None:
            old.deleteLater()
        self.setWindowTitle(f"{tab} · Budgetier")

    def restyle(self) -> None:
        """Apply the chosen look, and follow the system when the look says to."""
        self.mode = theme.apply(QApplication.instance(), self.look)
        t = theme.tokens(self.mode, self.look.palette)
        ratio = self.devicePixelRatioF()
        for tab, button in self.tab_buttons.items():
            button.setIcon(icons.tab_icon(tab, t["ink-2"], t["accent"], ICON, ratio))
        self.brand_mark.setPixmap(icons.pixmap(icons.BRAND, t["accent"], 24, ratio, filled=True))
        if self._ready:
            self.render()

    def set_look(self, look: theme.Look) -> None:
        self.look = look
        theme.save_look(self.budget.home, look)
        self.restyle()


def application() -> QApplication:
    app = QApplication.instance() or QApplication(["Budgetier"])
    app.setApplicationName("Budgetier")
    app.setStyle("Fusion")  # the same drawing on every system, under the style sheet
    return app
