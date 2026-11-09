"""Choosing a month on a chart shows just that month."""
from tests.qt import QtCase

try:
    from PySide6.QtCore import QPoint, Qt
except ImportError:  # the tests skip themselves without Qt
    pass


class Picking(QtCase):
    def setUp(self):
        super().setUp()
        self.win = self.window()

    def chart(self, tab: str):
        from budgetier.ui.charts import Chart
        self.win.show_tab(tab)
        return self.win.pages[tab].widget().findChildren(Chart)[0]

    def settle(self):
        from PySide6.QtTest import QTest
        QTest.qWait(20)  # the choice is made once the click is over

    def middle(self, chart, i):
        _, height, _, _, _, band, x, _ = chart.frame()
        return QPoint(int(x(i) + band / 2), height // 2)

    def test_clicking_a_month_on_the_overview_shows_it(self):
        from PySide6.QtTest import QTest
        chart = self.chart("Overview")
        i = len(chart.months) - 3
        QTest.mouseClick(chart, Qt.LeftButton, pos=self.middle(chart, i))
        self.settle()
        self.assertEqual(self.win.choice.range, chart.months[i])
        self.assertEqual(self.win.tab, "Overview")

    def test_enter_chooses_the_month_being_read(self):
        from PySide6.QtTest import QTest
        chart = self.chart("Spending")
        months = list(chart.months)
        chart.setFocus()
        QTest.keyClick(chart, Qt.Key_Left)  # from the end: the newest month
        QTest.keyClick(chart, Qt.Key_Left)
        QTest.keyClick(chart, Qt.Key_Return)
        self.settle()
        self.assertEqual(self.win.choice.range, months[-2])

    def test_enter_with_no_month_read_does_nothing(self):
        from PySide6.QtTest import QTest
        chart = self.chart("Savings")
        QTest.keyClick(chart, Qt.Key_Return)
        self.settle()
        self.assertEqual(self.win.choice.range, "12")

    def test_charts_that_arent_of_months_cant_be_picked(self):
        from budgetier.ui import theme
        from budgetier.ui.charts import Chart, Series
        chart = Chart(["35", "36"], [Series("Balance", [1, 2], "#123456")], theme.tokens("light", "pine"),
                      labels=["35", "36"], titles=["Age 35", "Age 36"])
        self.addCleanup(chart.deleteLater)
        self.assertIsNone(chart.on_pick)
        chart.pick(0)  # nothing to do it with: no error
