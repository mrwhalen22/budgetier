import unittest
from unittest import mock

from budgetier import app, storage
from tests.support import Tmp


class Desktop(Tmp):
    def test_only_one_copy_can_run(self):
        first = storage.hold_lock(self.dir)
        self.addCleanup(first.close)
        self.assertIsNotNone(first)
        self.assertIsNone(storage.hold_lock(self.dir))

    def test_an_alert_is_a_qt_message_on_every_system(self):
        import tests.qt  # noqa: F401 - draws offscreen
        with mock.patch("PySide6.QtWidgets.QMessageBox.critical") as shown:
            app._alert("Couldn't start")
        self.assertEqual(shown.call_args[0][1:], ("Budgetier", "Couldn't start"))


if __name__ == "__main__":
    unittest.main()
