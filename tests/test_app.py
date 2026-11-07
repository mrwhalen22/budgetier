import io
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

    def test_linux_opens_the_folder_with_the_desktop(self):
        with mock.patch.object(app.sys, "platform", "linux"), mock.patch.object(app.subprocess, "run") as run:
            app._show_folder(Path("/home/pat/Budgetier"))
        self.assertEqual(run.call_args[0][0], ["xdg-open", str(Path("/home/pat/Budgetier"))])

    def test_linux_alert_shows_a_dialog_when_it_can(self):
        with mock.patch.object(app.sys, "platform", "linux"), mock.patch.object(app.shutil, "which", return_value="/usr/bin/zenity"), \
                mock.patch.object(app.subprocess, "run") as run:
            app._alert("Couldn't start")
        self.assertEqual((run.call_args[0][0][0], run.call_args[0][0][-1]), ("zenity", "--text=Couldn't start"))

    def test_linux_alert_still_says_something_without_a_dialog(self):
        with mock.patch.object(app.sys, "platform", "linux"), mock.patch.object(app.shutil, "which", return_value=None), \
                mock.patch("sys.stderr", new_callable=io.StringIO) as err:
            app._alert("Couldn't start")
        self.assertIn("Couldn't start", err.getvalue())

    def test_linux_gets_a_window_that_can_open(self):
        with mock.patch.object(app.sys, "platform", "linux"), mock.patch.dict(app.os.environ, clear=True):
            app._prepare_linux_window()
            self.assertEqual(app.os.environ["QT_API"], "pyside6")
            self.assertEqual(app.os.environ["QTWEBENGINE_DISABLE_SANDBOX"], "1")

    def test_mac_alert_passes_the_text_safely(self):
        text = 'A "quoted" problem'
        with mock.patch.object(app.sys, "platform", "darwin"), mock.patch.object(app.subprocess, "run") as run:
            app._alert(text)
        command = run.call_args[0][0]
        self.assertEqual((command[0], command[-1]), ("osascript", text))
        self.assertFalse(any(text in part for part in command[:-1]))


if __name__ == "__main__":
    unittest.main()
