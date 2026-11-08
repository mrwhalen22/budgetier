"""How the window looks and moves: dropdowns, menus, the chart's note, the axis, motion."""
from tests.qt import QtCase

try:
    from PySide6.QtCore import QPoint, QRect, QSize, Qt
except ImportError:  # the tests skip themselves without Qt
    pass


class Dropdowns(QtCase):
    def setUp(self):
        super().setUp()
        from budgetier.ui import motion
        self.win = self.window()
        motion.set_on(False)  # read where the list ends up, not where it is mid-slide
        self.box = self.win.range_box

    def tearDown(self):
        from budgetier.ui import motion
        self.box.hidePopup()
        motion.set_on(True)
        super().tearDown()

    def test_it_opens_its_own_list_under_the_field(self):
        from budgetier.ui.popup import SHADOW
        self.box.showPopup()
        popup = self.box.popup()
        self.assertTrue(popup.isVisible())
        field = self.box.mapToGlobal(QPoint(0, 0))
        below = popup.y() + SHADOW > field.y() + self.box.height()
        above = popup.y() + popup.height() - SHADOW < field.y()
        self.assertTrue(below or above)

    def test_choosing_a_row_sets_it_and_says_so(self):
        chosen = []
        self.box.activated.connect(chosen.append)
        self.box.showPopup()
        row = self.box.findData("all")
        self.box.popup().choose(row)
        self.assertEqual(chosen, [row])
        self.assertEqual(self.win.choice.range, "all")
        self.assertIsNone(self.box.popup())

    def test_headings_and_lines_cant_be_chosen(self):
        self.box.showPopup()
        before = self.box.currentIndex()
        self.box.popup().choose(0)  # "Recent", a heading
        self.assertEqual(self.box.currentIndex(), before)
        self.assertTrue(self.box.popup().isVisible())

    def test_escape_closes_the_list_and_changes_nothing(self):
        from PySide6.QtTest import QTest
        before = self.win.choice
        self.box.showPopup()
        QTest.keyClick(self.box.popup().list, Qt.Key_Escape)
        self.assertIsNone(self.box.popup())
        self.assertEqual(self.win.choice, before)

    def test_the_keyboard_picks_a_row(self):
        from PySide6.QtTest import QTest
        self.box.showPopup()
        listing = self.box.popup().list
        QTest.keyClick(listing, Qt.Key_Down)
        QTest.keyClick(listing, Qt.Key_Return)
        self.assertEqual(self.win.choice.range, "6")

    def test_scrolling_past_one_leaves_it_alone(self):
        from PySide6.QtCore import QPointF
        from PySide6.QtGui import QWheelEvent
        self.win.stack.setFocus()
        before = self.box.currentIndex()
        wheel = QWheelEvent(QPointF(5, 5), QPointF(5, 5), QPoint(0, 0), QPoint(0, -120), Qt.NoButton, Qt.NoModifier,
                            Qt.NoScrollPhase, False)
        self.app.sendEvent(self.box, wheel)
        self.assertEqual(self.box.currentIndex(), before)

    def test_a_long_list_scrolls_instead_of_filling_the_screen(self):
        from budgetier.ui.popup import MOST, SHADOW
        self.box.showPopup()
        self.assertLessEqual(self.box.popup().height() - 2 * SHADOW, MOST + 16)

    def test_every_dropdown_in_the_window_is_one(self):
        from PySide6.QtWidgets import QComboBox

        from budgetier.ui.popup import Dropdown
        for tab in ("Transactions", "Budgets"):
            self.win.show_tab(tab)
            boxes = self.win.findChildren(QComboBox)
            self.assertTrue(boxes)
            self.assertTrue(all(isinstance(b, Dropdown) for b in boxes))


class Placing(QtCase):
    def test_a_panel_goes_under_its_field_or_over_it_near_the_bottom(self):
        from budgetier.ui.popup import GAP, SHADOW, place
        screen = QRect(0, 0, 1000, 800)
        under = place(QSize(200, 300), QRect(100, 100, 150, 36), screen)
        self.assertEqual((under.x() + SHADOW, under.y() + SHADOW), (100, 136 + GAP))
        over = place(QSize(200, 300), QRect(100, 700, 150, 36), screen)
        self.assertEqual(over.y() + SHADOW + 300, 700 - GAP)

    def test_it_stays_on_the_screen_and_can_line_up_on_the_right(self):
        from budgetier.ui.popup import SHADOW, place
        screen = QRect(0, 0, 1000, 800)
        edge = place(QSize(300, 100), QRect(900, 100, 80, 36), screen)
        self.assertLessEqual(edge.x() + SHADOW + 300, 1000 - SHADOW)
        right = place(QSize(200, 100), QRect(500, 100, 120, 36), screen, right=True)
        self.assertEqual(right.x() + SHADOW + 200, 620)


class AccountsMenu(QtCase):
    def test_ticking_an_account_keeps_the_menu_open(self):
        win = self.window()
        menu = win.accounts_menu
        menu.popup(win.accounts_button.mapToGlobal(QPoint(0, win.accounts_button.height())))
        action = next(iter(win.account_actions.values()))
        from PySide6.QtTest import QTest
        QTest.mouseClick(menu, Qt.LeftButton, pos=menu.actionGeometry(action).center())
        self.assertTrue(menu.isVisible())
        self.assertFalse(action.isChecked())
        menu.hide()


class Axis(QtCase):
    def test_every_label_on_the_axis_is_round(self):
        from budgetier.ui import fmt
        from budgetier.ui.charts import scale
        for hi in (90_00, 499_999, 5_000_00, 12_345_67, 87_000_00):
            bottom, top, step = scale(0, hi)
            self.assertGreaterEqual(top, hi)
            labels = [fmt.short(bottom + k * step) for k in range(round((top - bottom) / step) + 1)]
            self.assertTrue(all("." not in label or len(label.split(".")[1].rstrip("k")) == 1 for label in labels), labels)
            self.assertNotIn("$1.3k", labels)
            self.assertNotIn("$3.8k", labels)

    def test_below_zero_gets_whole_steps_too(self):
        from budgetier.ui.charts import scale
        bottom, top, step = scale(-150_00, 400_00)
        self.assertEqual(step, 100_00)
        self.assertEqual((bottom, top), (-200_00, 400_00))


class ChartNote(QtCase):
    def setUp(self):
        super().setUp()
        self.win = self.window()
        self.win.show_tab("Spending")
        from budgetier.ui.charts import Chart
        self.chart = self.win.pages["Spending"].widget().findChildren(Chart)[0]

    def test_it_sits_above_the_month_and_inside_the_window(self):
        chart = self.chart
        chart._read(3)
        note = chart.note
        self.assertTrue(note.isVisible())
        from budgetier.ui.popup import SHADOW
        window = QRect(self.win.mapToGlobal(QPoint(0, 0)), self.win.size())
        panel = QRect(note.pos() + QPoint(SHADOW, SHADOW), note.panel())
        self.assertTrue(window.contains(panel), (window, panel))

    def test_it_stays_up_while_reading_and_goes_when_the_mouse_leaves(self):
        self.chart._read(2)
        self.chart._read(3)
        self.assertTrue(self.chart.note.isVisible())
        self.assertTrue(self.chart.note.title)
        self.chart._read(-1)
        self.assertFalse(self.chart.note.isVisible())

    def test_a_stacked_month_ends_with_its_total(self):
        self.chart._read(1)
        name, _, color = self.chart.note.rows[-1]
        self.assertEqual((name, color), ("Total", ""))


class Motion(QtCase):
    def tearDown(self):
        from budgetier.ui import motion
        motion.set_on(True)
        super().tearDown()

    def test_reduce_motion_is_kept_and_read_back(self):
        from budgetier.ui import look, motion, settings
        win = self.window()
        dialog = look.appearance(win)
        dialog.motion.setChecked(True)
        self.assertFalse(motion.on())
        self.assertTrue(settings.load(self.budget.home)["reduce_motion"])
        dialog.dismiss()
        motion.set_on(True)
        self.assertFalse(motion.load(self.budget.home))

    def test_without_motion_charts_are_drawn_whole_at_once(self):
        from budgetier.ui import motion
        from budgetier.ui.charts import Chart
        win = self.window()
        motion.set_on(False)
        win.show_tab("Spending")
        charts = win.pages["Spending"].widget().findChildren(Chart)
        self.assertTrue(charts)
        self.assertTrue(all(c.grown == 1 for c in charts))

    def test_bars_grow_for_a_new_tab_but_not_after_a_change(self):
        from budgetier.ui.charts import Chart
        win = self.window()
        win.show_tab("Spending")
        first = win.pages["Spending"].widget().findChildren(Chart)[0]
        self.assertLess(first.grown, 1)
        win.changed("Saved.")
        again = win.pages["Spending"].widget().findChildren(Chart)[0]
        self.assertEqual(again.grown, 1)

    def test_the_note_at_the_bottom_shows_at_once_and_follows_the_window(self):
        win = self.window()
        win.toast.say("Saved.")
        self.assertTrue(win.toast.isVisible())
        win.resize(win.width() + 100, win.height())
        from PySide6.QtTest import QTest
        QTest.qWait(200)  # let the slide that say() started run out, as it does on a slow machine
        self.assertEqual(win.toast.x(), (win.width() - win.toast.width()) // 2)


class Buttons(QtCase):
    def test_a_disabled_main_button_looks_disabled(self):
        from budgetier.ui import theme
        for mode in ("light", "dark"):
            sheet = theme.style_sheet(theme.tokens(mode, "pine"))
            rule = sheet.split('QPushButton[kind="primary"]:disabled, QPushButton[kind="danger"]:disabled')[1].split("}")[0]
            self.assertNotIn(theme.tokens(mode, "pine")["accent"], rule)

    def test_chart_colors_are_all_different(self):
        from budgetier.ui import theme
        for mode in ("light", "dark"):
            t = theme.tokens(mode, "pine")
            colors = [t[f"c{i}"] for i in range(8)]
            self.assertEqual(len(set(colors)), 8)
            self.assertNotIn(t["spending"], colors)
            self.assertNotIn(t["income"], colors)
