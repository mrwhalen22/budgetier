"""Test the Qt window without a screen: Qt draws offscreen, here and on CI alike.

These need PySide6, and are skipped without it unless BUDGETIER_QT=required, which CI sets
so that they can't quietly stop running.
"""
import os
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")  # before Qt starts

try:
    from PySide6.QtWidgets import QApplication
except ImportError:
    QApplication = None

from tests.fake import build
from tests.support import Tmp

REQUIRED = os.environ.get("BUDGETIER_QT") == "required"


def application():
    from budgetier.ui.app import application as start
    return start()


@unittest.skipUnless(QApplication or REQUIRED, "needs PySide6")
class QtCase(Tmp):
    """Each test gets a window on made-up data in its own folder."""

    def setUp(self):
        super().setUp()
        self.app = application()
        self.budget = build(Path(self.dir) / "home")

    def window(self, budget=None, toured=True, background=False, **options):
        """toured: whether the tour has been seen, so it doesn't start by itself mid-test.
        background: read the data again off the window's thread after a change, as the app
        does. Off, a test can check the window straight after changing something."""
        from budgetier.ui import settings
        from budgetier.ui.app import Window
        budget = budget or self.budget
        if toured:
            settings.save(budget.home, toured=True)
        window = Window(budget, **options)
        window.background = background
        self.addCleanup(self.gone, window)
        window.show()
        self.app.processEvents()
        return window

    def gone(self, window) -> None:
        """Delete it now, not whenever Qt gets to it: windows left over slow every later test."""
        from PySide6.QtCore import QCoreApplication, QEvent
        window.close()
        window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
