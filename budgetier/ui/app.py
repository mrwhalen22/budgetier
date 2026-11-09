"""The window: a sidebar of tabs beside the tab that's showing."""
from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from PySide6.QtCore import QByteArray, QEvent, QSize, Qt, QTimer
from PySide6.QtGui import QStandardItemModel
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .. import sample, views
from ..service import Budget, app_version
from . import banking, charts, icons, keys, look, motion, popup, settings, theme, tour, widgets
from .banking import Banking
from .context import Context
from .dialogs import Toast, attempt
from .editing import Editing
from .importing import Importing
from .tabs import BUILDERS, transactions
from .updating import Updating
from .work import Runner

# The order the sidebar lists them in.
TABS = ("Overview", "Spending", "Budgets", "Recurring", "Largest", "Savings", "Investments", "Net worth", "Year in review",
        "Transactions", "Rules", "Accounts", "Help")
# Which step of docs/qt-migration.md brings each tab, until it's here.
COMING: dict[str, int] = {}
# These cover all of history, so the period and account filters don't apply.
FULL_HISTORY = {"Budgets", "Recurring", "Year in review", "Accounts", "Rules", "Help"}
SIDE_WIDTH = 232
ICON = 18
PLACE = "window"  # where the window was left, in settings.json
SEEN = "seen"  # what was here when you last looked, for what's new since
UPDATING_AFTER = 150  # ms: a reload quicker than this never says it's happening


def _placeholder(tab: str) -> QWidget:
    return widgets.card(widgets.text(f"The {tab} tab arrives in step {COMING[tab]} of the move to Qt.", "dim"), title=tab)


class Window(QMainWindow):
    background = True  # read the data again off the window's thread; tests turn it off to check at once

    def __init__(self, budget: Budget, look: theme.Look | None = None):
        super().__init__()
        self.budget = budget
        self.mine = budget  # your own data; budget is the sample's while you look around it
        self.sample_home: Path | None = None
        self.look = look or theme.load_look(budget.home)
        place = _place(settings.load(budget.home).get(PLACE))
        self.choice = place["choice"]
        self.options: dict = {}
        self._ready = False  # draw nothing until the window is built
        self._drawn = ""  # the tab drawn last
        self._viewed = None  # the tab and filters drawn last
        self._loading = False  # reading the data again, off the window's thread
        self._again = False  # and something changed it meanwhile, so read it once more
        motion.load(budget.home)
        QApplication.setEffectEnabled(Qt.UI_FadeTooltip, motion.on())
        self.setWindowTitle("Budgetier")
        self.resize(1340, 900)
        self.setMinimumSize(900, 620)
        if place["geometry"]:
            self.restoreGeometry(place["geometry"])  # Qt moves it onto a screen that's still there

        central = QWidget()
        row = QHBoxLayout(central)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        row.addWidget(self._side())
        row.addWidget(self._content(), 1)
        self.setCentralWidget(central)
        self.toast = Toast(self)
        self.editing = Editing(self)
        self.runner = Runner(self)
        self.importing = Importing(self)
        self.banking = Banking(self)
        self.updating = Updating(self)
        self.tour: tour.Tour | None = None
        self.shortcuts = keys.install(self, TABS)
        self._updating_note = QTimer(self, singleShot=True, interval=UPDATING_AFTER)
        self._updating_note.timeout.connect(lambda: self.busy_note.setVisible(self._loading))

        hints = QApplication.instance().styleHints()
        hints.colorSchemeChanged.connect(lambda _scheme: self.restyle())
        self.mode = theme.mode_for(self.look, False)
        self.reload()
        saved = settings.load(budget.home).get(SEEN)
        self.seen = saved if isinstance(saved, dict) else views.seen(self.snapshot)  # the first time: nothing is news
        self._looked = False  # whether the Overview was shown, so what's new there has been seen
        if not isinstance(saved, dict):
            self._keep_seen()
        self.restyle()
        self._ready = True
        self.show_tab(place["tab"])
        self.stack.setFocus()  # not the first tab's button, which would show a focus ring at once
        updates = self.updating.status()
        if updates["supported"] and updates["automatic"]:
            self.updating.check_quietly()
        tour.maybe_start(self)

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

        self.add_button = QPushButton("Add files")
        self.add_button.setProperty("kind", "primary")
        self.add_button.clicked.connect(lambda: self.importing.add_files())
        self.bank_button = QPushButton()
        self.bank_button.clicked.connect(lambda: self.banking.act())
        actions = QVBoxLayout()
        actions.setSpacing(theme.SPACE[2])
        actions.setContentsMargins(0, 0, 0, theme.SPACE[4])
        self.update_button = QPushButton()
        self.update_button.clicked.connect(lambda: self.updating.form())
        self.update_button.hide()  # until an update is found
        actions.addWidget(self.add_button)
        actions.addWidget(self.bank_button)
        actions.addWidget(self.update_button)
        column.addLayout(actions)

        numbered = keys.tab_keys(TABS)
        self.add_button.setToolTip(keys.shown("Ctrl+I"))
        self.bank_button.setToolTip(keys.shown("Ctrl+R"))
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
            button.setFocusPolicy(Qt.TabFocus)  # a click shouldn't leave a focus ring
            button.clicked.connect(lambda _checked=False, tab=tab: self.show_tab(tab))
            if tab in numbered:
                button.setToolTip(keys.shown(numbered[tab]))
            button.installEventFilter(self)  # the arrow keys move between tabs
            self.tab_group.addButton(button)
            self.tab_buttons[tab] = button
            column.addWidget(button)

        column.addStretch(1)
        self.look_button = QPushButton("Appearance")
        self.look_button.setProperty("kind", "nav-link")
        self.look_button.setIconSize(QSize(ICON, ICON))
        self.look_button.setFocusPolicy(Qt.TabFocus)
        self.look_button.clicked.connect(lambda: look.appearance(self))
        column.addWidget(self.look_button)
        self.foot = widgets.text("", wrap=True)
        self.foot.setObjectName("foot")
        column.addWidget(self.foot)
        return side

    def _filters(self) -> QWidget:
        self.range_box = popup.Dropdown()
        self.range_box.setAccessibleName("Period")
        self.range_box.activated.connect(self._range_chosen)
        self.accounts_button = popup.Picker()
        self.accounts_button.setProperty("kind", "picker")
        self.accounts_button.setAccessibleName("Accounts")
        self.accounts_button.setPopupMode(QToolButton.InstantPopup)
        self.accounts_menu = popup.Menu(self.accounts_button)
        self.accounts_button.setMenu(self.accounts_menu)
        box = widgets.row(self.range_box, self.accounts_button, stretch_last=True)
        box.setObjectName("filters")
        return box

    def _content(self) -> QWidget:
        content = QWidget()
        content.setObjectName("content")
        column = QVBoxLayout(content)
        gutter = theme.SPACE[8]
        column.setContentsMargins(gutter, theme.SPACE[5], gutter - SCROLL_ROOM, 0)  # the scroll bar sits in the gutter
        column.setSpacing(theme.SPACE[3])

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, SCROLL_ROOM, 0)
        words = QVBoxLayout()
        words.setSpacing(2)
        self.title = QLabel()
        self.title.setObjectName("title")
        self.subtitle = widgets.text("")
        self.subtitle.setObjectName("subtitle")
        self.busy_note = widgets.text("Updating...", "dim", wrap=False)
        self.busy_note.setAccessibleName("Updating")
        self.busy_note.hide()
        title_row = QHBoxLayout()
        title_row.setSpacing(theme.SPACE[3])
        title_row.addWidget(self.title)
        title_row.addWidget(self.busy_note, 0, Qt.AlignBottom)
        title_row.addStretch(1)
        words.addLayout(title_row)
        words.addWidget(self.subtitle)
        header.addLayout(words, 1)
        self.filters = self._filters()
        header.addWidget(self.filters, 0, Qt.AlignVCenter)
        self.sample_bar = widgets.banner(
            "info", "You're looking at sample data",
            "None of it is real, and changes to it are thrown away. Your own data is untouched.", theme.current(),
            self._leave_button())
        self.sample_bar.hide()
        bar = QHBoxLayout()
        bar.setContentsMargins(0, 0, SCROLL_ROOM, 0)  # lined up with the header, clear of the scroll bar's gutter
        bar.addWidget(self.sample_bar)
        column.addLayout(bar)
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
        """Read the data folder again, after anything changes it.

        Once the window is up this happens off its thread, since a long history takes a
        moment: you can keep reading the numbers as they were, and they're redrawn when
        the new ones are ready. Changes made meanwhile are read together in one more go.
        The first read happens here, before the window shows, so a damaged file stops
        the app opening as it always has."""
        if not (self._ready and self.background):
            self._show(views.from_budget(self.budget))
            return
        if self._loading:
            self._again = True
            return
        self._loading, self._again = True, False
        self._updating_note.start()
        self.runner.quietly(views.from_budget, (self.budget,), self._loaded)

    def _loaded(self, ok: bool, snapshot) -> None:
        self._loading = False
        if self._again:  # what was read is already out of date
            self.reload()
            return
        self._updating_note.stop()
        self.busy_note.hide()
        # Something changing the data as it was read can trip the read up: then read it here,
        # where a real problem shows as it always has.
        self._show(snapshot if ok else views.from_budget(self.budget))

    def reload_now(self) -> None:
        """Read the data again here and now, for a step that needs the new numbers at once."""
        self._again = self._again or self._loading  # one still being read is out of date
        self._show(views.from_budget(self.budget))

    @property
    def loading(self) -> bool:
        return self._loading

    def _show(self, snapshot: views.Snapshot) -> None:
        self.snapshot = snapshot
        ids = {a.id for a in self.snapshot.accounts}
        if self.choice.accounts is not None:
            kept = self.choice.accounts & ids
            self.choice = views.Choice(self.choice.range, kept if kept and kept != ids else None)  # none left: all
        values = [value for _, value, _ in views.range_options(self.snapshot)]
        if self.choice.range not in values:
            self.choice = views.Choice("12", self.choice.accounts)
        self._fill_filters()
        status = self.banking.status()
        self.bank_button.setText(banking.button_label(status))
        self.bank_button.setToolTip(f"Last synced {banking.synced_at(status)}" if banking.synced_at(status) else "")
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
                model.item(box.count() - 1).setEnabled(False)  # a heading, not a choice
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

    def eventFilter(self, watched, event):  # noqa: N802 - Qt's name
        """Up and Down on a tab's button show the tab above or below, as in a list of tabs."""
        if event.type() == QEvent.KeyPress and event.key() in (Qt.Key_Up, Qt.Key_Down):
            tab = next((t for t, b in self.tab_buttons.items() if b is watched), None)
            if tab is not None:
                step = -1 if event.key() == Qt.Key_Up else 1
                chosen = TABS[(TABS.index(tab) + step) % len(TABS)]
                self.show_tab(chosen)
                self.tab_buttons[chosen].setFocus(Qt.TabFocusReason)
                return True
        return super().eventFilter(watched, event)

    def show_tab(self, tab: str) -> None:
        self.stack.setCurrentWidget(self.pages[tab])
        self.title.setText(tab)
        self.tab_buttons[tab].setChecked(True)
        self.render()

    def open_transactions(self, category: str = "", query: str = "") -> None:
        """A category or merchant selected elsewhere shows its transactions."""
        self.options["transactions"] = {**transactions.fresh(), "category": category, "query": query}
        self.show_tab("Transactions")

    def tokens(self) -> dict[str, str]:
        return theme.tokens(self.mode, self.look.palette)

    def hold(self, on: bool, note: str = "") -> None:
        """Hold the window still while slow work runs, saying what it is."""
        self.centralWidget().setEnabled(not on)
        if on:
            self.toast.stay(note)
        else:
            self.toast.hide()

    def ask_files(self) -> list[str]:
        """Bank files to add. Tests replace this, since a real file dialog needs a person."""
        paths, _ = QFileDialog.getOpenFileNames(self, "Add files", "", "Bank files (*.csv *.pdf);;All files (*)")
        return paths

    def ask_save_path(self) -> str:
        path, _ = QFileDialog.getSaveFileName(self, "Export workbook", str(Path.home() / "Budgetier.xlsx"),
                                              "Excel workbook (*.xlsx)")
        return path

    def ask_csv_path(self, name: str) -> str:
        """Where to save a CSV. Tests replace this, since a real file dialog needs a person."""
        path, _ = QFileDialog.getSaveFileName(self, "Export CSV", str(Path.home() / name), "CSV file (*.csv)")
        return path

    def changed(self, note: str = "", undo: bool = False) -> None:
        """After a change to the data: read it again, redraw where you were, and say what happened.
        undo: the change can be undone, from the note or with Ctrl+Z."""
        self.reload()
        self.toast.say(note, ("Undo", self.undo) if undo and self.budget.can_undo() else None)

    def undo(self) -> None:
        """Put back what the last small change replaced: a category, a rule, a budget, an account's details."""
        if not self.budget.can_undo():
            self.toast.say("There's nothing to undo.")
            return
        ok, result = attempt(self.budget.undo)
        if ok:
            self.changed("Undone.")
        else:
            self.reload()  # what can't be undone is no longer offered
            self.toast.say(str(result))

    def context(self) -> Context:
        status, sync = self.budget.updates.status(), self.budget.sync.status()
        return Context(self.snapshot, self.choice, theme.tokens(self.mode, self.look.palette), self.open_transactions,
                       self.choose_range, self.render, self.options, app_version(),
                       sync["connected"], status, self.editing, self, sync)

    def render(self) -> None:
        """Draw the tab that's showing, from the data and filters as they are now."""
        if not self._ready:
            return
        tab = self.tab
        self._looked = self._looked or tab == "Overview"
        full = tab in FULL_HISTORY
        self.filters.setVisible(not full and bool(self.snapshot.txns))
        subtitle = "All history" if full else views.range_label(self.snapshot, self.choice)
        self.subtitle.setText(subtitle if self.snapshot.txns or tab == "Help" else "")  # no data: just the welcome
        view = (tab, self.choice)
        charts.grow_next = view != self._viewed  # bars grow in for a new tab or period, not after each change
        self._viewed = view
        body = BUILDERS[tab](self.context()) if tab in BUILDERS else _placeholder(tab)
        charts.grow_next = False
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, theme.SPACE[2], SCROLL_ROOM - SCROLL_BAR, theme.SPACE[10])
        layout.addWidget(body)
        layout.addStretch(1)
        scroll = self.pages[tab]
        again = tab == self._drawn  # the same tab redrawn after a change keeps its place
        at = scroll.verticalScrollBar().value() if again else 0
        old = scroll.takeWidget()
        scroll.setWidget(page)
        if old is not None:
            old.deleteLater()
        if not again:
            motion.reveal(page)
            self._drop(self._drawn)
        self._drawn = tab
        if at:
            QTimer.singleShot(0, lambda: scroll.verticalScrollBar().setValue(at))
        self.setWindowTitle(f"{tab} · Budgetier")

    def _drop(self, tab: str | None) -> None:
        """Let go of a tab that's no longer showing. It's drawn again whenever it's shown, and
        every widget kept alive makes a change of look slower, since Qt restyles them all."""
        if tab in self.pages and self.pages[tab] is not self.stack.currentWidget():
            old = self.pages[tab].takeWidget()
            if old is not None:
                old.deleteLater()

    def restyle(self) -> None:
        """Apply the chosen look, and follow the system when the look says to."""
        self.mode = theme.apply(QApplication.instance(), self.look)
        t = theme.tokens(self.mode, self.look.palette)
        ratio = self.devicePixelRatioF()
        for tab, button in self.tab_buttons.items():
            button.setIcon(icons.tab_icon(tab, t["ink-2"], t["accent"], ICON, ratio))
        self.brand_mark.setPixmap(icons.pixmap(icons.BRAND, t["accent"], 24, ratio, filled=True))
        self.look_button.setIcon(icons.icon(icons.SUN, t["ink-2"], ICON, ratio))
        if self._ready:
            self.render()

    def resizeEvent(self, event):  # noqa: N802 - Qt's name
        super().resizeEvent(event)
        self.toast.follow()

    def mark_seen(self) -> None:
        """What's new has been seen: the Overview stops showing it."""
        self.seen = views.seen(self.snapshot)
        self._keep_seen()
        self.render()

    def _keep_seen(self) -> None:
        if self.sample_home:
            return  # what you saw in the sample isn't what's new in yours
        try:
            settings.save(self.mine.home, **{SEEN: self.seen})
        except OSError:
            pass  # it shows again next time, which is no harm

    def closeEvent(self, event):  # noqa: N802 - Qt's name
        """Remember where you were, to open there next time, and that you saw what was new."""
        if self.sample_home:
            self.leave_sample()
        if self._looked:
            self.seen = views.seen(self.snapshot)
            self._keep_seen()
        accounts = None if self.choice.accounts is None else sorted(self.choice.accounts)
        try:
            settings.save(self.mine.home, **{PLACE: {"geometry": bytes(self.saveGeometry().toBase64()).decode("ascii"),
                                                       "tab": self.tab, "range": self.choice.range, "accounts": accounts}})
        except OSError:
            pass  # not being able to remember this is no reason to stop closing
        super().closeEvent(event)

    # ---- sample data

    def _leave_button(self) -> QPushButton:
        button = QPushButton("Leave sample data")
        button.clicked.connect(lambda _=False: self.leave_sample())
        return button

    def try_sample(self) -> None:
        """Look around made-up data, kept in a folder of its own and thrown away afterwards."""
        if self.sample_home:
            return
        folder = Path(tempfile.mkdtemp(prefix="budgetier-sample-"))
        try:
            budget = sample.build(folder / "home")
        except Exception:
            shutil.rmtree(folder, ignore_errors=True)
            raise
        self.sample_home, self.budget = folder, budget
        self.choice = views.Choice()
        self.sample_bar.show()
        self.reload_now()
        self.show_tab(TABS[0])
        self.toast.say("Here's some sample data to look around.")

    def leave_sample(self) -> None:
        folder = self.sample_home
        if folder is None:
            return
        self.sample_home, self.budget = None, self.mine
        self.choice = views.Choice()
        self.sample_bar.hide()
        self.reload_now()
        self.show_tab(TABS[0])
        shutil.rmtree(folder, ignore_errors=True)

    def blocked_by_sample(self) -> bool:
        """Files and bank connections are for your own data: say so while the sample is up."""
        if self.sample_home:
            self.toast.say("Leave the sample data first, so this goes into your own.")
            return True
        return False

    # ---- what the keyboard shortcuts do

    def find(self) -> None:
        self.show_tab("Transactions")
        found = self.pages["Transactions"].widget().findChildren(QLineEdit, "search")
        if found:
            found[0].setFocus(Qt.ShortcutFocusReason)
            found[0].selectAll()

    def add_files(self) -> None:
        self.importing.add_files()

    def sync(self) -> None:
        self.banking.act()

    def appearance(self) -> None:
        look.appearance(self)

    def help(self) -> None:
        self.show_tab("Help")

    def set_motion(self, on: bool) -> None:
        motion.set_on(on)
        settings.save(self.mine.home, reduce_motion=not on)
        QApplication.setEffectEnabled(Qt.UI_FadeTooltip, on)

    def set_look(self, look: theme.Look) -> None:
        self.look = look
        theme.save_look(self.mine.home, look)
        self.restyle()


SCROLL_ROOM = 14  # a scroll bar and a little air, kept clear at the right of each tab
SCROLL_BAR = 10  # as wide as the style sheet draws it


def _place(saved) -> dict:
    """Where the window was left. Anything that can't be read starts as a new window would;
    the period and accounts are checked against the data once it's read."""
    saved = saved if isinstance(saved, dict) else {}
    tab = saved.get("tab") if saved.get("tab") in TABS else TABS[0]
    period = saved.get("range") if isinstance(saved.get("range"), str) and saved.get("range") else "12"
    accounts = saved.get("accounts")
    chosen = frozenset(a for a in accounts if isinstance(a, str)) if isinstance(accounts, list) and accounts else None
    geometry = saved.get("geometry")
    geometry = QByteArray.fromBase64(geometry.encode("ascii")) if isinstance(geometry, str) and geometry.isascii() else None
    return {"tab": tab, "choice": views.Choice(period, chosen), "geometry": geometry if geometry else None}


def application() -> QApplication:
    app = QApplication.instance() or QApplication(["Budgetier"])
    app.setApplicationName("Budgetier")
    app.setStyle("Fusion")  # the same drawing on every system, under the style sheet
    return app
