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

from tests.browser import build
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

    def window(self, **options):
        from budgetier.ui.app import Window
        window = Window(self.budget, **options)
        self.addCleanup(window.deleteLater)
        self.addCleanup(window.close)
        window.show()
        self.app.processEvents()
        return window
