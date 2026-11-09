"""A reminder on the Overview when the numbers are a while out of date."""
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

from budgetier import views
from tests import fake
from tests.qt import QtCase

LINKED = {"connected": True, "linked": ["Chase Card 0002"], "lastSync": "2026-11-01T09:30:00"}


def snapshot(end="2026-10-15"):
    return mock.Mock(txns=[object()], end=end)


class WhenToRemind(unittest.TestCase):
    def test_a_week_without_syncing(self):
        self.assertIsNone(views.reminder(snapshot(), LINKED, datetime(2026, 11, 7, 9)))
        found = views.reminder(snapshot(), LINKED, datetime(2026, 11, 10, 9))
        self.assertEqual((found.title, found.action), ("Last synced 9 days ago", "sync"))

    def test_linked_but_never_synced(self):
        found = views.reminder(snapshot(), {**LINKED, "lastSync": None}, datetime(2026, 11, 1))
        self.assertEqual((found.title, found.action), ("Not synced yet", "sync"))

    def test_connected_with_nothing_linked_isnt_nagged(self):
        self.assertIsNone(views.reminder(snapshot(), {**LINKED, "linked": []}, datetime(2027, 1, 1)))

    def test_files_a_month_behind(self):
        self.assertIsNone(views.reminder(snapshot(), {}, datetime(2026, 11, 10)))
        found = views.reminder(snapshot(), {}, datetime(2026, 11, 20))
        self.assertEqual(found.title, "Your newest transaction is from Oct 15, 2026, 36 days ago")
        self.assertEqual(found.action, "add")

    def test_no_data_has_the_welcome_instead(self):
        empty = mock.Mock(txns=[], end="2026-01-01")
        self.assertIsNone(views.reminder(empty, {}, datetime(2027, 1, 1)))

    def test_a_garbled_last_sync_says_nothing(self):
        self.assertIsNone(views.reminder(snapshot(), {**LINKED, "lastSync": "soon"}, datetime(2027, 1, 1)))


class OnTheOverview(QtCase):
    def banner(self, win):
        from PySide6.QtWidgets import QPushButton
        page = win.pages["Overview"].widget()
        return [b for b in page.findChildren(QPushButton) if b.text() in ("Sync now", "Add files")]

    def test_old_files_offer_to_add_more(self):
        with mock.patch.object(views, "datetime", wraps=datetime) as clock:
            clock.now.return_value = datetime(2026, 12, 31)
            win = self.window()
            [button] = self.banner(win)
        self.assertEqual(button.text(), "Add files")
        with mock.patch.object(win.importing, "add_files") as add:
            button.click()
        add.assert_called_once()

    def test_a_stale_sync_offers_to_sync(self):
        win = self.window(fake.build(Path(self.dir) / "synced"))
        stale = {**LINKED, "lastSync": "2026-01-01T08:00:00"}
        with mock.patch.object(win.budget.sync, "status", return_value=stale):
            win.render()
            [button] = self.banner(win)
            self.assertEqual(button.text(), "Sync now")
            with mock.patch.object(win.banking, "act") as sync:
                button.click()
        sync.assert_called_once()

    def test_up_to_date_says_nothing(self):
        with mock.patch.object(views, "datetime", wraps=datetime) as clock:
            clock.now.return_value = datetime(2026, 10, 20)
            win = self.window()
            self.assertEqual(self.banner(win), [])
