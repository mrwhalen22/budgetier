import unittest
from pathlib import Path
from unittest import mock

from budgetier import app, storage
from tests.support import Tmp


class Desktop(Tmp):
    def test_only_one_copy_can_run(self):
        first = storage.hold_lock(self.dir)
        self.addCleanup(first.close)
        self.assertIsNotNone(first)
        self.assertIsNone(storage.hold_lock(self.dir))

    def test_mac_shows_the_folder_in_finder(self):
        with mock.patch.object(app.sys, "platform", "darwin"), mock.patch.object(app.subprocess, "run") as run:
            app._show_folder(Path("/Users/pat/Budgetier"))
        self.assertEqual(run.call_args[0][0], ["open", str(Path("/Users/pat/Budgetier"))])

    def test_mac_alert_passes_the_text_safely(self):
        text = 'A "quoted" problem'
        with mock.patch.object(app.sys, "platform", "darwin"), mock.patch.object(app.subprocess, "run") as run:
            app._alert(text)
        command = run.call_args[0][0]
        self.assertEqual((command[0], command[-1]), ("osascript", text))
        self.assertFalse(any(text in part for part in command[:-1]))


if __name__ == "__main__":
    unittest.main()
