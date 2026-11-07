"""The Qt window's Budgets tab, updates, Appearance, the tour, and keyboard use."""
import time
import unittest
from pathlib import Path
from unittest import mock

from budgetier import updates
from tests.browser import build
from tests.qt import QtCase


class Window(QtCase):
    def setUp(self):
        super().setUp()
        self.win = self.window()

    def toast(self) -> str:
        return self.win.toast.text() if self.win.toast.isVisible() else ""

    def open_dialog(self):
        from budgetier.ui.dialogs import Dialog
        found = [d for d in self.win.findChildren(Dialog) if d.isVisible()]
        self.assertEqual(len(found), 1, [d.windowTitle() for d in found])
        return found[0]

    def labels(self, widget) -> str:
        from PySide6.QtWidgets import QLabel
        return " ".join(label.text() for label in widget.findChildren(QLabel))

    def page(self, tab):
        self.win.show_tab(tab)
        return self.win.pages[tab].widget()

    def button(self, widget, text):
        from PySide6.QtWidgets import QPushButton
        return next(b for b in widget.findChildren(QPushButton) if b.text() == text)

    def field(self, dialog, name):
        from PySide6.QtWidgets import QComboBox, QLineEdit
        fields = [*dialog.findChildren(QLineEdit), *dialog.findChildren(QComboBox)]
        return next(f for f in fields if f.accessibleName() == name)

    def settle(self, seconds: float) -> None:
        from PySide6.QtCore import QCoreApplication
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            QCoreApplication.processEvents()
            time.sleep(.02)


class Budgets(Window):
    def test_the_month_its_budgets_and_recent_months(self):
        page = self.page("Budgets")
        words = self.labels(page)
        for expected in ("Budgeted", "Spent on budgets", "Not budgeted", "Dining", "$300 a month", "Recent months",
                         "Month in progress"):
            self.assertIn(expected, words)

    def test_another_month(self):
        from PySide6.QtWidgets import QComboBox
        page = self.page("Budgets")
        month = next(b for b in page.findChildren(QComboBox) if b.accessibleName() == "Month")
        month.activated.emit(month.findData("2026-09"))
        self.assertIn("Sep 2026", self.labels(self.win.pages["Budgets"].widget()))
        self.assertNotIn("Month in progress", self.labels(self.win.pages["Budgets"].widget()))

    def test_adding_a_dollar_budget_with_a_preview(self):
        self.button(self.page("Budgets"), "Add budget").click()
        dialog = self.open_dialog()
        category = self.field(dialog, "Category")
        category.setCurrentIndex(category.findData("Groceries"))
        self.field(dialog, "Dollars a month").setText("400")
        self.assertIn("You've averaged", self.labels(dialog))
        self.assertRegex(self.labels(dialog), r"That's about \d+% of your income")
        dialog.main.click()
        self.assertEqual(self.toast(), "Budget saved.")
        self.assertIn("Groceries", [t["category"] for t in self.win.snapshot.budget_targets])

    def test_a_percent_budget(self):
        self.button(self.page("Budgets"), "Add budget").click()
        dialog = self.open_dialog()
        mode = self.field(dialog, "Target type")
        mode.setCurrentIndex(mode.findData("percent"))
        self.field(dialog, "Percent of income").setText("10")
        self.assertIn("10% of that income is about", self.labels(dialog))
        dialog.main.click()
        self.assertIn("10% of income", self.labels(self.win.pages["Budgets"].widget()))

    def test_a_bad_amount_says_so(self):
        self.button(self.page("Budgets"), "Add budget").click()
        dialog = self.open_dialog()
        self.field(dialog, "Dollars a month").setText("lots")
        dialog.main.click()
        self.assertEqual(dialog.error.text(), "Enter a dollar amount above zero.")

    def test_editing_starts_from_the_budget(self):
        self.button(self.page("Budgets"), "Edit").click()
        dialog = self.open_dialog()
        self.assertFalse(self.field(dialog, "Category").isEnabled())
        self.assertEqual(self.field(dialog, "Dollars a month").text(), "300")

    def test_removing_asks_first(self):
        self.button(self.page("Budgets"), "Remove").click()
        ask = self.open_dialog()
        self.assertEqual(ask.windowTitle(), "Remove the Dining budget?")
        ask.buttons[-1].click()
        self.assertEqual(self.toast(), "Removed.")
        self.assertIn("Set your first budget", self.labels(self.win.pages["Budgets"].widget()))


class Updates(Window):
    FOUND = {"available": True, "version": "9.9.9", "reopens": False}

    def supported(self):
        patch = mock.patch.object(updates.Updater, "supported", new_callable=mock.PropertyMock, return_value=True)
        patch.start()
        self.addCleanup(patch.stop)

    def test_checking_by_hand_offers_the_update(self):
        self.supported()
        with mock.patch.object(updates.Updater, "check", return_value=self.FOUND):
            self.button(self.page("Help"), "Check for updates").click()
            self.assertTrue(self.win.runner.wait())
        form = self.open_dialog()
        self.assertEqual(form.windowTitle(), "Update to 9.9.9")
        self.assertTrue(self.win.update_button.isVisibleTo(self.win))
        with mock.patch.object(updates.Updater, "install", return_value={"closing": False}):
            form.main.click()
            self.assertTrue(self.win.runner.wait())
        self.assertEqual(self.open_dialog().windowTitle(), "Almost done")

    def test_nothing_new_says_so(self):
        self.supported()
        with mock.patch.object(updates.Updater, "check", return_value={**self.FOUND, "available": False}):
            self.button(self.page("Help"), "Check for updates").click()
            self.assertTrue(self.win.runner.wait())
        self.assertEqual(self.toast(), "You have the latest version.")

    def test_opening_checks_quietly_when_allowed(self):
        self.supported()
        with mock.patch.object(updates.Updater, "check", return_value=self.FOUND) as check:
            win = self.window()
            self.assertTrue(win.runner.wait())
        check.assert_called_once_with(False)
        self.assertEqual(win.update_button.text(), "Update to 9.9.9")
        self.assertTrue(win.centralWidget().isEnabled())  # a quiet check holds nothing up

    def test_checking_automatically_can_be_turned_off(self):
        self.supported()
        self.button(self.page("Help"), "Stop checking automatically").click()
        self.assertFalse(self.budget.updates.automatic)
        self.button(self.win.pages["Help"].widget(), "Check automatically")

    def test_running_from_source_offers_no_updates(self):
        page = self.page("Help")
        from PySide6.QtWidgets import QPushButton
        self.assertNotIn("Check for updates", [b.text() for b in page.findChildren(QPushButton)])


class Appearance(Window):
    def test_choosing_a_mode_and_theme_is_kept(self):
        from budgetier.ui import look, theme
        dialog = look.appearance(self.win)
        next(b for b in dialog.mode_buttons if b.text() == "Dark").click()
        next(b for b in dialog.palette_buttons if b.text() == "Plum").click()
        self.assertEqual(self.win.look, theme.Look("dark", "plum"))
        self.assertEqual(theme.load_look(self.budget.home), theme.Look("dark", "plum"))
        self.assertIn(theme.tokens("dark", "plum")["page"], self.app.styleSheet())

    def test_it_opens_from_the_sidebar(self):
        self.win.look_button.click()
        self.assertEqual(self.open_dialog().windowTitle(), "Appearance")


class Tour(Window):
    def test_it_starts_the_first_time_there_is_data(self):
        win = self.window(build(Path(self.dir) / "fresh"), toured=False)
        self.settle(.8)
        self.assertIsNotNone(win.tour)
        self.assertEqual(win.tour.title.text(), "Add more history")

    def test_not_without_data_or_once_seen(self):
        empty = self.window(build(Path(self.dir) / "empty", rows=[]), toured=False)
        self.settle(.8)
        self.assertIsNone(empty.tour)
        self.assertIsNone(self.win.tour)

    def test_next_walks_through_and_done_remembers(self):
        from budgetier.ui import tour
        walk = tour.start(self.win)
        titles = []
        for _ in tour.STEPS:
            titles.append(walk.title.text())
            walk.next.click()
        self.assertEqual(titles, [title for _, title, _ in tour.STEPS])
        self.assertIsNone(self.win.tour)
        self.assertTrue(tour.seen(self.budget.home))

    def test_escape_skips(self):
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest

        from budgetier.ui import tour
        walk = tour.start(self.win)
        QTest.keyClick(walk, Qt.Key_Escape)
        self.assertIsNone(self.win.tour)

    def test_help_can_start_it_again(self):
        self.button(self.page("Help"), "Take the tour").click()
        self.assertIsNotNone(self.win.tour)


class Keyboard(Window):
    def test_the_arrow_keys_move_between_tabs(self):
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        button = self.win.tab_buttons["Overview"]
        QTest.keyClick(button, Qt.Key_Down)
        self.assertEqual(self.win.tab, "Spending")
        QTest.keyClick(self.win.tab_buttons["Spending"], Qt.Key_Up)
        QTest.keyClick(self.win.tab_buttons["Overview"], Qt.Key_Up)
        self.assertEqual(self.win.tab, "Help")

    def test_a_note_is_named_for_screen_readers(self):
        self.win.toast.say("Budget saved.")
        self.assertEqual(self.win.toast.accessibleName(), "Budget saved.")


if __name__ == "__main__":
    unittest.main()
