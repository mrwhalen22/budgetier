"""Sample data to look around with: kept apart from yours, and thrown away afterwards."""
from datetime import date
from pathlib import Path

from budgetier import sample, views
from tests import fake
from tests.qt import QtCase
from tests.support import Tmp


class TheSample(Tmp):
    def test_it_comes_out_the_same_each_time(self):
        a, _ = sample.rows(date(2026, 11, 8))
        b, _ = sample.rows(date(2026, 11, 8))
        self.assertEqual(a, b)

    def test_it_reads_like_a_real_budget(self):
        budget = sample.build(Path(self.dir) / "sample", date(2026, 11, 8))
        s = views.from_budget(budget)
        self.assertEqual({a.type for a in s.accounts}, {"checking", "credit", "savings", "retirement"})
        self.assertGreaterEqual(len(s.months), 18)
        self.assertEqual([c for c in s.checks if c["level"] == "warning"], [])  # nothing for a newcomer to puzzle over
        o = views.overview(s, views.Choice("12"))
        self.assertGreater(o.income, o.spending)
        self.assertIn("Netflix", [r.merchant for r in s.recurring])
        self.assertIsNotNone(views.investments(s, views.Choice("12")).growth)


class LookingAround(QtCase):
    def setUp(self):
        super().setUp()
        self.mine = fake.build(Path(self.dir) / "mine", rows=[])
        self.win = self.window(self.mine)

    def button(self, words):
        from PySide6.QtWidgets import QPushButton
        found = [b for b in self.win.findChildren(QPushButton) if b.text() == words and b.isVisibleTo(self.win)]
        self.assertTrue(found, words)
        return found[0]

    def test_the_welcome_offers_it_and_your_data_stays_as_it_was(self):
        self.button("Try it with sample data").click()
        folder = self.win.sample_home
        self.assertTrue(folder.exists())
        self.assertTrue(self.win.snapshot.txns)
        self.assertTrue(self.win.sample_bar.isVisibleTo(self.win))
        self.assertTrue(str(self.win.budget.home).startswith(str(folder)))
        from budgetier.ledger import Ledger
        self.assertEqual(Ledger(self.mine.home).rows, [])  # read back from your own folder: nothing came in

    def test_changes_go_to_the_sample_and_are_thrown_away(self):
        self.win.try_sample()
        folder = self.win.sample_home
        self.win.budget.undoable(self.win.budget.save_budget, "Shopping", "amount", "100")
        self.win.changed("Budget saved.", undo=True)
        self.assertNotIn("Shopping", self.mine.budgets())
        self.button("Leave sample data").click()
        self.assertIsNone(self.win.sample_home)
        self.assertFalse(folder.exists())
        self.assertIs(self.win.budget, self.mine)
        self.assertFalse(self.win.snapshot.txns)
        self.assertFalse(self.win.sample_bar.isVisibleTo(self.win))

    def test_files_and_banks_wait_until_you_leave(self):
        from unittest import mock
        self.win.try_sample()
        with mock.patch.object(self.win, "ask_files") as ask:
            self.win.add_files()
        ask.assert_not_called()
        self.assertEqual(self.win.toast.words, "Leave the sample data first, so this goes into your own.")
        self.assertIsNone(self.win.banking.connect_form())

    def test_your_look_and_place_are_kept_in_your_own_folder(self):
        from budgetier.ui import settings, theme
        self.win.try_sample()
        self.win.set_look(theme.Look("dark", "plum"))
        self.assertEqual(theme.load_look(self.mine.home), theme.Look("dark", "plum"))
        folder = self.win.sample_home
        self.win.close()
        self.assertFalse(folder.exists())  # closing leaves the sample too
        self.assertIn("window", settings.load(self.mine.home))

    def test_whats_new_isnt_shown_for_the_sample(self):
        from PySide6.QtWidgets import QFrame
        self.win.try_sample()
        self.assertIsNone(self.win.pages["Overview"].widget().findChild(QFrame, "whatsNew"))
