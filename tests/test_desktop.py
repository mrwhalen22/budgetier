"""The desktop bridge and the Windows installer's steps, without touching the real system."""
import importlib.util
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from budgetier import app
from tests.support import Tmp

if sys.platform == "win32":
    from tests.test_packaging import setup_main

    _spec = importlib.util.spec_from_file_location(
        "uninstall_main", Path(__file__).resolve().parents[1] / "packaging" / "uninstall_main.py")
    uninstall_main = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(uninstall_main)


class Bridge(unittest.TestCase):
    def setUp(self):
        self.budget = mock.Mock(home=Path("home"))
        self.api = app.Api(self.budget)
        self.api._window = mock.Mock()

    def test_each_page_call_reaches_the_budget(self):
        calls = {
            "inspect": (["a.csv"],), "remove_import": ("a.csv",), "remove_account": ("x",),
            "update_account": ("x", "Name", "credit", "", ""), "preview_rule": ("COFFEE", False),
            "suggest_rule": ("Coffee", ["SQ *COFFEE"]),
            "save_rule": (None, "COFFEE", "Dining", "", False), "delete_rule": ("line",),
            "save_budget": ("Dining", "amount", "50"), "delete_budget": ("Dining",),
        }
        for name, args in calls.items():
            getattr(self.budget, name).return_value = {}
            self.assertTrue(getattr(self.api, name)(*args)["ok"], name)
            getattr(self.budget, name).assert_called_once_with(*args)

    def test_a_slow_update_check_does_not_wait_its_turn(self):
        self.budget.updates.check.return_value = {"available": False}
        with self.api._turn:
            self.assertEqual(self.api.check_update(True), {"ok": True, "available": False})
        self.budget.updates.check.assert_called_once_with(True)

    def test_a_failed_update_check_reaches_the_page(self):
        self.budget.updates.check.side_effect = app.BudgetError("offline")
        self.assertEqual(self.api.check_update(True), {"ok": False, "error": "offline"})

    def test_the_window_closes_only_when_the_installer_took_over(self):
        self.budget.updates.install.return_value = {"closing": True}
        with mock.patch.object(app.threading, "Timer") as timer:
            self.assertTrue(self.api.install_update()["closing"])
        timer.assert_called_once_with(.5, self.api._window.destroy)
        timer.return_value.start.assert_called_once()
        self.budget.updates.install.side_effect = app.BudgetError("declined")
        with mock.patch.object(app.threading, "Timer") as timer:
            self.assertFalse(self.api.install_update()["ok"])
        timer.assert_not_called()

    def test_turning_the_check_off_is_saved(self):
        self.assertTrue(self.api.set_update_check(False)["ok"])
        self.budget.updates.set_automatic.assert_called_once_with(False)

    def test_commit_and_cancel(self):
        self.budget.commit.return_value = [{"added": 1}]
        self.assertEqual(self.api.commit([{}]), {"ok": True, "results": [{"added": 1}]})
        self.assertTrue(self.api.cancel()["ok"])

    def test_choosing_no_files_is_an_empty_list(self):
        self.api._window.create_file_dialog.return_value = None
        self.assertEqual(self.api.pick_files(), {"ok": True, "paths": []})

    def test_chosen_files_are_listed(self):
        self.api._window.create_file_dialog.return_value = ("a.csv", "b.pdf")
        self.assertEqual(self.api.pick_files()["paths"], ["a.csv", "b.pdf"])

    def test_cancelling_the_export_saves_nothing(self):
        self.api._window.create_file_dialog.return_value = None
        self.assertEqual(self.api.export_workbook(), {"ok": True, "saved": ""})
        self.budget.export_workbook.assert_not_called()

    def test_export_handles_both_shapes_the_dialog_returns(self):
        for chosen in ("out.xlsx", ("out.xlsx",)):
            self.api._window.create_file_dialog.return_value = chosen
            self.assertEqual(self.api.export_workbook()["saved"], "out.xlsx")

    def test_the_data_folder_opens(self):
        with mock.patch.object(app, "_show_folder") as show:
            self.assertTrue(self.api.open_data_folder()["ok"])
        show.assert_called_once_with(Path("home"))


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
