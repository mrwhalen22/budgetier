"""The Windows installer's steps, without touching the real system."""
import importlib.util
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from tests.support import Tmp

if sys.platform == "win32":
    from tests.test_packaging import setup_main

    _spec = importlib.util.spec_from_file_location(
        "uninstall_main", Path(__file__).resolve().parents[1] / "packaging" / "uninstall_main.py")
    uninstall_main = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(uninstall_main)


@unittest.skipUnless(sys.platform == "win32", "the installer is Windows only")
class InstallerSteps(Tmp):
    def test_a_running_app_is_noticed(self):
        with mock.patch.object(setup_main.subprocess, "run") as run:
            run.return_value = SimpleNamespace(stdout="Budgetier.exe  123 Console")
            self.assertTrue(setup_main.app_is_running())
            run.return_value = SimpleNamespace(stdout="INFO: No tasks are running")
            self.assertFalse(setup_main.app_is_running())

    def registry(self, value):
        reg = mock.MagicMock(HKEY_LOCAL_MACHINE="machine", HKEY_CURRENT_USER="user")
        reg.QueryValueEx.return_value = (value,)
        return mock.patch.object(setup_main, "winreg", reg), reg

    def test_installed_details_come_from_the_registry(self):
        patch, _ = self.registry(r"C:\Apps\Budgetier")
        with patch:
            self.assertEqual(setup_main.installed_location(), Path(r"C:\Apps\Budgetier"))

    def test_old_per_user_installs_are_found_second(self):
        patch, reg = self.registry("1.1.0")
        reg.OpenKey.side_effect = [OSError(), mock.MagicMock()]
        with patch:
            self.assertEqual(setup_main.installed_version(), "1.1.0")

    def test_nothing_installed_means_no_details(self):
        patch, reg = self.registry("")
        reg.OpenKey.side_effect = OSError()
        with patch:
            self.assertIsNone(setup_main.installed_version())
            self.assertIsNone(setup_main.installed_location())
            self.assertIsNone(setup_main.user_install_location())

    def test_registering_lists_the_app_and_its_uninstaller(self):
        (self.dir / "Budgetier.exe").write_bytes(b"x" * 2048)
        patch, reg = self.registry("")
        with patch:
            setup_main.register(self.dir)
        written = {c.args[1]: c.args[4] for c in reg.SetValueEx.call_args_list}
        self.assertEqual(written["DisplayVersion"], setup_main.VERSION)
        self.assertEqual(written["QuietUninstallString"], f'"{self.dir / "uninstall.exe"}" --silent')
        self.assertEqual(written["EstimatedSize"], 2)

    def test_the_old_per_user_entry_is_forgotten_quietly(self):
        for failure in (None, FileNotFoundError(), PermissionError()):
            patch, reg = self.registry("")
            reg.DeleteKey.side_effect = failure
            with patch:
                setup_main.forget_user_registration()
            reg.DeleteKey.assert_called_once()

    def folders(self):
        made = [self.dir / n for n in ("common desktop", "common programs", "desktop", "programs")]
        for folder in made:
            folder.mkdir()
        return made

    def test_shell_folders_are_read_in_order(self):
        output = "A\r\nB\r\nC\r\nD\r\n"
        with mock.patch.object(setup_main.subprocess, "run", return_value=SimpleNamespace(stdout=output)):
            self.assertEqual(setup_main._shell_folders(), tuple(map(Path, "ABCD")))

    def test_a_first_install_offers_both_shortcuts(self):
        with mock.patch.object(setup_main, "installed_version", return_value=None):
            self.assertEqual(setup_main.shortcut_state(), (True, True))

    def test_an_update_keeps_the_shortcuts_you_chose(self):
        made = self.folders()
        (made[3] / "Budgetier.lnk").write_text("", encoding="utf-8")
        with mock.patch.object(setup_main, "installed_version", return_value="1.0.0"), \
                mock.patch.object(setup_main, "_shell_folders", return_value=tuple(made)):
            self.assertEqual(setup_main.shortcut_state(), (False, True))

    def test_if_folders_cant_be_found_both_shortcuts_are_offered(self):
        with mock.patch.object(setup_main, "installed_version", return_value="1.0.0"), \
                mock.patch.object(setup_main, "_shell_folders", side_effect=OSError()):
            self.assertEqual(setup_main.shortcut_state(), (True, True))

    def test_unwanted_shortcuts_are_removed_and_wanted_ones_made(self):
        common_desktop, common_programs, desktop, programs = made = self.folders()
        for link in (common_desktop, desktop, programs):
            (link / "Budgetier.lnk").write_text("", encoding="utf-8")
        with mock.patch.object(setup_main, "_shell_folders", return_value=tuple(made)), \
                mock.patch.object(setup_main.subprocess, "run") as run:
            setup_main.set_shortcuts(self.dir, False, True)
        env = run.call_args.kwargs["env"]
        self.assertEqual(env["BUDGETIER_LINKS"], str(common_programs / "Budgetier.lnk"))
        self.assertFalse(any((f / "Budgetier.lnk").exists() for f in (common_desktop, desktop, programs)))

    def test_no_shortcuts_wanted_runs_nothing(self):
        with mock.patch.object(setup_main, "_shell_folders", return_value=tuple(self.folders())), \
                mock.patch.object(setup_main.subprocess, "run") as run:
            setup_main.set_shortcuts(self.dir, False, False)
        run.assert_not_called()

    def test_removal_spares_the_running_uninstaller(self):
        (self.dir / "_internal").mkdir()
        (self.dir / "_internal" / "a.dll").write_text("", encoding="utf-8")
        (self.dir / "Budgetier.exe").write_text("", encoding="utf-8")
        (self.dir / "uninstall.exe").write_text("", encoding="utf-8")
        setup_main.remove_program(self.dir)
        self.assertEqual([p.name for p in self.dir.iterdir()], ["uninstall.exe"])

    def test_the_last_step_quotes_the_folder_and_waits(self):
        with mock.patch.object(setup_main.subprocess, "Popen") as popen:
            setup_main.finish_removal(Path(r"C:\Bob's Apps"), [12, 34])
        script = popen.call_args[0][0][-1]
        self.assertIn("-Id 12,34", script)
        self.assertIn(r"'C:\Bob''s Apps'", script)

    def test_launching_goes_through_explorer_so_it_isnt_admin(self):
        with mock.patch.object(setup_main.subprocess, "Popen") as popen:
            setup_main.launch(self.dir)
        self.assertEqual(popen.call_args[0][0], ["explorer.exe", str(self.dir / "Budgetier.exe")])


@unittest.skipUnless(sys.platform == "win32", "the installer is Windows only")
class Uninstaller(unittest.TestCase):
    def run_it(self, *argv, answer=uninstall_main.YES if sys.platform == "win32" else 0, failure=None):
        with mock.patch.object(uninstall_main.sys, "argv", ["uninstall.exe", *argv]), \
                mock.patch.object(uninstall_main, "ask", return_value=answer) as ask, \
                mock.patch.object(uninstall_main.setup_main, "start_log"), \
                mock.patch.object(uninstall_main.setup_main, "uninstall", side_effect=failure) as remove:
            return uninstall_main.main(), ask, remove

    def test_saying_no_removes_nothing(self):
        code, _, remove = self.run_it(answer=0)
        self.assertEqual(code, 1)
        remove.assert_not_called()

    def test_saying_yes_removes_it_and_confirms(self):
        code, ask, remove = self.run_it()
        self.assertEqual(code, 0)
        remove.assert_called_once()
        self.assertEqual(ask.call_args[0][0], "Budgetier was removed.")

    def test_silent_never_asks(self):
        code, ask, _ = self.run_it("--silent")
        self.assertEqual(code, 0)
        ask.assert_not_called()

    def test_a_failure_is_shown(self):
        code, ask, _ = self.run_it(failure=setup_main.SetupError("Close Budgetier first."))
        self.assertEqual(code, 1)
        self.assertEqual(ask.call_args[0][0], "Close Budgetier first.")


if __name__ == "__main__":
    unittest.main()
