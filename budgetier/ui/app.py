"""The Qt window: a sidebar of tabs beside the tab that's showing.

This is the start of the move described in docs/qt-migration.md. Until the move is done the
desktop app still opens the page, and this window opens only from the command line:

    python -m budgetier.ui [--home FOLDER]
"""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ..service import Budget, app_version
from . import icons, theme, widgets

# The order the sidebar lists them in, as on the page.
TABS = ("Overview", "Spending", "Budgets", "Recurring", "Largest", "Savings", "Transactions", "Rules", "Accounts", "Help")
# Which step of docs/qt-migration.md brings each tab, until it's here.
COMING = {"Overview": 3, "Spending": 3, "Recurring": 3, "Largest": 3, "Savings": 3, "Help": 3,
          "Transactions": 4, "Rules": 4, "Accounts": 5, "Budgets": 6}
SIDE_WIDTH = 232
ICON = 18


def _placeholder(tab: str) -> QWidget:
    note = widgets.text(f"The {tab} tab arrives in step {COMING[tab]} of the move to Qt.", "dim")
    return widgets.card(note, title=tab)


class Window(QMainWindow):
    def __init__(self, budget: Budget, look: theme.Look | None = None):
        super().__init__()
        self.budget = budget
        self.look = look or theme.load_look(budget.home)
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
        self.restyle()
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
        foot = widgets.text(f"Version {app_version()}" if app_version() else "", wrap=True)
        foot.setObjectName("foot")
        column.addWidget(foot)
        return side

    def _content(self) -> QWidget:
        content = QWidget()
        content.setObjectName("content")
        column = QVBoxLayout(content)
        gutter = theme.SPACE[8]
        column.setContentsMargins(gutter, theme.SPACE[5], gutter, 0)
        column.setSpacing(theme.SPACE[3])

        header = QVBoxLayout()
        header.setSpacing(2)
        self.title = QLabel()
        self.title.setObjectName("title")
        self.subtitle = widgets.text("")
        self.subtitle.setObjectName("subtitle")
        header.addWidget(self.title)
        header.addWidget(self.subtitle)
        column.addLayout(header)

        self.stack = QStackedWidget()
        self.stack.setObjectName("view")
        self.stack.setFocusPolicy(Qt.ClickFocus)
        self.pages: dict[str, QWidget] = {}
        for tab in TABS:
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.NoFrame)
            body = QWidget()
            layout = QVBoxLayout(body)
            layout.setContentsMargins(0, theme.SPACE[2], 0, theme.SPACE[10])
            layout.addWidget(_placeholder(tab))
            layout.addStretch(1)
            scroll.setWidget(body)
            self.stack.addWidget(scroll)
            self.pages[tab] = scroll
        column.addWidget(self.stack, 1)
        return content

    # ---- what the window does

    @property
    def tab(self) -> str:
        return TABS[self.stack.currentIndex()]

    def show_tab(self, tab: str) -> None:
        self.stack.setCurrentWidget(self.pages[tab])
        self.title.setText(tab)
        self.tab_buttons[tab].setChecked(True)

    def restyle(self) -> None:
        """Apply the chosen look, and follow the system when the look says to."""
        mode = theme.apply(QApplication.instance(), self.look)
        t = theme.tokens(mode, self.look.palette)
        ratio = self.devicePixelRatioF()
        for tab, button in self.tab_buttons.items():
            button.setIcon(icons.tab_icon(tab, t["ink-2"], t["accent"], ICON, ratio))
        self.brand_mark.setPixmap(icons.pixmap(icons.BRAND, t["accent"], 24, ratio, filled=True))
        self.mode = mode

    def set_look(self, look: theme.Look) -> None:
        self.look = look
        theme.save_look(self.budget.home, look)
        self.restyle()


def application() -> QApplication:
    app = QApplication.instance() or QApplication(["Budgetier"])
    app.setApplicationName("Budgetier")
    app.setStyle("Fusion")  # the same drawing on every system, under the style sheet
    return app
