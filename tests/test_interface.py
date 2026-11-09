"""How amounts read on screen: what's owed without a minus sign, and colors that mean one thing."""
from budgetier.ui import fmt
from tests.qt import QtCase


class Owed(QtCase):
    def test_owed_reads_as_an_amount_owed(self):
        self.assertEqual(fmt.owed(-61250), "$613")
        self.assertEqual(fmt.owed(5000), "-$50")  # a card in credit
        self.assertEqual(fmt.owed(0), "$0")


class Bars(QtCase):
    def test_a_bar_list_can_leave_out_each_share(self):
        from PySide6.QtWidgets import QLabel

        from budgetier.ui import theme, widgets
        bars = widgets.hbars([("Dining", 5600, None, lambda: None)], fmt.money, theme.current(), shares=False)
        words = [label.text() for label in bars.findChildren(QLabel)]
        self.assertNotIn("100%", words)
        self.assertIn("$56", words)
