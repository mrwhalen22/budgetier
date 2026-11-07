import importlib.util
import io
import re
import subprocess
import sys
import time
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from tests.support import Tmp

if sys.platform == "win32":  # the installer talks to the Windows registry
    _spec = importlib.util.spec_from_file_location(
        "setup_main", Path(__file__).resolve().parents[1] / "packaging" / "setup_main.py")
    setup_main = importlib.util.module_from_spec(_spec)
    sys.modules["setup_main"] = setup_main
    _spec.loader.exec_module(setup_main)


_build = importlib.util.spec_from_file_location(
    "build_installer", Path(__file__).resolve().parents[1] / "packaging" / "build_installer.py")


build_installer = importlib.util.module_from_spec(_build)


_build.loader.exec_module(build_installer)


class MacImage(Tmp):
    def test_each_kind_of_mac_gets_its_own_name(self):
        self.assertEqual(build_installer.MAC_NAMES["arm64"], "Budgetier-macOS-Apple-Silicon.dmg")
        self.assertEqual(build_installer.MAC_NAMES["x86_64"], "Budgetier-macOS-Intel.dmg")

    def test_a_busy_disk_is_tried_again(self):
        results = [mock.Mock(returncode=1), mock.Mock(returncode=0)]
        with mock.patch.object(build_installer.subprocess, "run", side_effect=results) as run, \
                mock.patch.object(build_installer.time, "sleep"):
            build_installer.disk_image(self.dir, self.dir / "x.dmg")
        self.assertEqual(run.call_count, 2)

    def test_a_disk_that_stays_busy_stops_the_build(self):
        with mock.patch.object(build_installer.subprocess, "run", return_value=mock.Mock(returncode=1)), \
                mock.patch.object(build_installer.time, "sleep"), self.assertRaises(SystemExit):
            build_installer.disk_image(self.dir, self.dir / "x.dmg")


_bump = importlib.util.spec_from_file_location(
    "bump_version", Path(__file__).resolve().parents[1] / "packaging" / "bump_version.py")


bump_version = importlib.util.module_from_spec(_bump)


_bump.loader.exec_module(bump_version)


class UpdateNames(unittest.TestCase):
    def test_the_app_looks_for_the_files_a_release_publishes(self):
        from budgetier import updates
        with mock.patch.object(updates.sys, "platform", "darwin"):
            for machine, name in build_installer.MAC_NAMES.items():
                with mock.patch.object(updates.platform, "machine", return_value=machine):
                    self.assertEqual(updates.installer_name(), name)
        workflow = (Path(__file__).resolve().parents[1] / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
        self.assertIn(updates.CHECKSUMS, workflow)

    def test_mac_ci_only_watches_files_that_exist(self):
        root = Path(__file__).resolve().parents[1]
        text = (root / ".github" / "workflows" / "mac-ci.yml").read_text(encoding="utf-8")
        watched = re.findall(r"^      - ([^\s*]+)$", text, re.M)
        self.assertIn("budgetier/app.py", watched)
        self.assertEqual([name for name in watched if not (root / name).exists()], [])

    def test_mac_builds_keep_the_windows_checksum(self):
        from budgetier import updates
        workflow = (Path(__file__).resolve().parents[1] / ".github" / "workflows" / "mac-builds.yml").read_text(encoding="utf-8")
        self.assertIn(updates.CHECKSUMS, workflow)
        self.assertIn("grep -v", workflow)


class Versioning(Tmp):
    def test_each_part_raises_and_resets_what_follows(self):
        for part, want in (("patch", "1.2.4"), ("minor", "1.3.0"), ("major", "2.0.0")):
            self.assertEqual(bump_version.bump("1.2.3", part), want)

    def test_numbers_are_not_compared_as_text(self):
        self.assertEqual(bump_version.bump("1.9.9", "patch"), "1.9.10")

    def test_bad_input_is_refused(self):
        for version, part in (("1.2", "patch"), ("v1.2.3", "patch"), ("1.2.3", "huge")):
            with self.assertRaises(ValueError):
                bump_version.bump(version, part)

    def test_file_is_rewritten_with_only_the_new_number(self):
        version = self.dir / "VERSION"
        version.write_bytes(b"\xef\xbb\xbf1.2.3\r\n")
        with mock.patch.object(bump_version, "VERSION_FILE", version), \
                mock.patch.object(sys, "argv", ["bump_version.py", "minor"]), \
                mock.patch("sys.stdout", io.StringIO()) as out:
            self.assertEqual(bump_version.main(), 0)
        self.assertEqual(version.read_bytes(), b"1.3.0\n")
        self.assertEqual(out.getvalue().strip(), "1.3.0")


@unittest.skipUnless(sys.platform == "win32", "the Windows installer")
class Updating(Tmp):
    """The app starts the installer and closes, so the installer has to finish the job."""

    def run_update(self, running=(False,), failure=None):
        exe = self.dir / "Budgetier.exe"
        exe.write_text("x")
        with mock.patch.object(setup_main, "app_is_running", side_effect=[*running, False, False]), \
                mock.patch.object(setup_main, "installed_location", return_value=self.dir), \
                mock.patch.object(setup_main, "shortcut_state", return_value=(False, True)), \
                mock.patch.object(setup_main, "install", side_effect=failure, return_value=self.dir) as install, \
                mock.patch.object(setup_main, "launch") as launch, \
                mock.patch.object(setup_main.time, "sleep"), \
                mock.patch.object(setup_main.ctypes, "windll", create=True) as windll:
            code = setup_main.update()
        return code, install, launch, windll

    def test_it_waits_for_the_app_and_keeps_your_shortcuts(self):
        code, install, launch, _ = self.run_update(running=(True, True, False))
        self.assertEqual(code, 0)
        options = install.call_args[0][0]
        self.assertEqual((options.desktop, options.start_menu), (False, True))
        launch.assert_called_once_with(self.dir)

    def test_a_failed_update_says_so_and_reopens_the_app(self):
        code, _, launch, windll = self.run_update(failure=setup_main.SetupError("disk full"))
        self.assertEqual(code, 1)
        self.assertIn("disk full", windll.user32.MessageBoxW.call_args[0][1])
        launch.assert_called_once_with(self.dir)

    def test_the_flag_matches_what_the_app_sends(self):
        from budgetier import updates
        with mock.patch.object(setup_main, "update", return_value=0) as update, \
                mock.patch.object(setup_main, "start_log"), mock.patch.object(setup_main, "window") as window, \
                mock.patch.object(setup_main.sys, "argv", ["setup", updates.UPDATE_FLAG]):
            setup_main.main()
        update.assert_called_once()
        window.assert_not_called()


@unittest.skipUnless(sys.platform == "win32", "the Windows installer")
class Installer(Tmp):
    def payload(self, files, name="payload.zip"):
        path = self.dir / name
        with zipfile.ZipFile(path, "w") as z:
            for file, text in files.items():
                z.writestr(file, text)
        return path

    def setUp(self):
        super().setUp()
        self.target = self.dir / "Programs" / "Budgetier"

    def test_version_comes_from_the_version_file(self):
        root = Path(setup_main.__file__).resolve().parents[1]
        self.assertEqual(setup_main.VERSION, (root / "VERSION").read_text(encoding="utf-8").strip())
        self.assertRegex(setup_main.VERSION, r"^\d+\.\d+\.\d+$")

    def test_version_file_saved_by_notepad_still_reads(self):
        (self.dir / "VERSION").write_bytes(b"\xef\xbb\xbf2.3.4\r\n")
        with mock.patch.object(setup_main.sys, "_MEIPASS", str(self.dir), create=True):
            self.assertEqual(setup_main.read_version(), "2.3.4")

    def test_fresh_install_unpacks_nested_files(self):
        shares = []
        setup_main.unpack(self.payload({"Budgetier.exe": "x", "_internal/a.dll": "y"}), self.target, shares.append)
        self.assertEqual((self.target / "_internal" / "a.dll").read_text(), "y")
        self.assertEqual(shares[-1], 1)

    def test_update_replaces_old_files_and_leaves_no_leftovers(self):
        setup_main.unpack(self.payload({"Budgetier.exe": "old", "gone.dll": "x"}), self.target)
        setup_main.unpack(self.payload({"Budgetier.exe": "new"}), self.target)
        self.assertEqual((self.target / "Budgetier.exe").read_text(), "new")
        self.assertFalse((self.target / "gone.dll").exists())
        self.assertEqual([p.name for p in self.target.parent.iterdir()], ["Budgetier"])

    def test_damaged_payload_keeps_the_working_install(self):
        setup_main.unpack(self.payload({"Budgetier.exe": "old"}), self.target)
        bad = self.dir / "bad.zip"
        bad.write_bytes(b"not a zip")
        with self.assertRaisesRegex(setup_main.SetupError, "damaged"):
            setup_main.unpack(bad, self.target)
        self.assertEqual((self.target / "Budgetier.exe").read_text(), "old")

    def test_payload_without_the_app_keeps_the_working_install(self):
        setup_main.unpack(self.payload({"Budgetier.exe": "old"}), self.target)
        with self.assertRaisesRegex(setup_main.SetupError, "damaged"):
            setup_main.unpack(self.payload({"readme.txt": "x"}), self.target)
        self.assertEqual((self.target / "Budgetier.exe").read_text(), "old")
        self.assertEqual([p.name for p in self.target.parent.iterdir()], ["Budgetier"])

    def test_interrupted_earlier_update_is_cleaned_up(self):
        (self.target.parent / "Budgetier.new").mkdir(parents=True)
        (self.target.parent / "Budgetier.old").mkdir()
        setup_main.unpack(self.payload({"Budgetier.exe": "x"}), self.target)
        self.assertEqual([p.name for p in self.target.parent.iterdir()], ["Budgetier"])

    def test_refuses_while_the_app_is_open(self):
        with mock.patch.object(setup_main, "app_is_running", return_value=True), \
                mock.patch.object(setup_main, "unpack") as unpack:
            with self.assertRaisesRegex(setup_main.SetupError, "Close it"):
                setup_main.install(setup_main.Options(self.target))
        unpack.assert_not_called()

    def test_a_plain_folder_gets_its_own_budgetier_subfolder(self):
        docs = self.dir / "Documents"
        docs.mkdir()
        (docs / "taxes.pdf").write_text("mine")
        self.assertEqual(setup_main.resolve_target(docs), docs / "Budgetier")

    def test_folder_named_budgetier_is_used_as_is(self):
        self.assertEqual(setup_main.resolve_target(self.target), self.target)

    def test_refuses_a_budgetier_folder_holding_other_files(self):
        self.target.mkdir(parents=True)
        (self.target / "mine.txt").write_text("x")
        with self.assertRaisesRegex(setup_main.SetupError, "other files"):
            setup_main.resolve_target(self.target)

    def test_existing_install_is_allowed(self):
        self.target.mkdir(parents=True)
        (self.target / "Budgetier.exe").write_text("x")
        self.assertEqual(setup_main.resolve_target(self.target), self.target)

    def test_blank_and_relative_locations_are_refused(self):
        for bad in ("", "  ", "apps\\here"):
            with self.assertRaises(setup_main.SetupError):
                setup_main.resolve_target(bad)

    def test_moved_install_clears_the_old_copy_only_if_ours(self):
        old = self.dir / "old"
        old.mkdir()
        (old / "keep.txt").write_text("x")
        setup_main.remove_moved_install(old, self.target)
        self.assertTrue(old.exists())
        (old / "Budgetier.exe").write_text("x")
        setup_main.remove_moved_install(old, self.target)
        self.assertFalse(old.exists())
        self.target.mkdir(parents=True)
        (self.target / "Budgetier.exe").write_text("x")
        setup_main.remove_moved_install(self.target, self.target)
        self.assertTrue(self.target.exists())

    def test_writable_check_finds_nearest_existing_parent(self):
        setup_main.check_writable(self.dir / "a" / "b" / "Budgetier")

    def test_folder_that_refuses_writes_gets_a_clear_message(self):
        with mock.patch.object(Path, "touch", side_effect=PermissionError):
            with self.assertRaisesRegex(setup_main.SetupError, "can.t write"):
                setup_main.check_writable(self.dir / "Budgetier")

    def test_default_location_is_program_files(self):
        with mock.patch.dict("os.environ", {"ProgramW6432": "C:\\Program Files"}):
            self.assertEqual(setup_main.default_target(), Path("C:\\Program Files\\Budgetier"))

    def test_entry_is_registered_for_the_whole_pc_with_the_uninstaller(self):
        self.target.mkdir(parents=True)
        (self.target / "Budgetier.exe").write_text("x")
        written = {}
        key = mock.MagicMock()
        key.__enter__.return_value = key
        with mock.patch.object(setup_main.winreg, "CreateKey", return_value=key) as create, \
                mock.patch.object(setup_main.winreg, "SetValueEx",
                                  side_effect=lambda k, name, _, kind, value: written.__setitem__(name, value)):
            setup_main.register(self.target)
        self.assertEqual(create.call_args[0][0], setup_main.winreg.HKEY_LOCAL_MACHINE)
        self.assertEqual(written["DisplayName"], "Budgetier")
        self.assertEqual(written["UninstallString"], f'"{self.target / "uninstall.exe"}"')
        self.assertTrue(written["QuietUninstallString"].endswith("--silent"))

    def test_uninstall_refuses_a_folder_that_is_not_budgetier(self):
        (self.dir / "mine.txt").write_text("x")
        with mock.patch.object(setup_main.subprocess, "Popen") as popen:
            with self.assertRaisesRegex(setup_main.SetupError, "nothing was removed"):
                setup_main.uninstall(self.dir)
        popen.assert_not_called()
        self.assertTrue((self.dir / "mine.txt").exists())

    def test_uninstall_refuses_while_the_app_is_open(self):
        (self.dir / "Budgetier.exe").write_text("x")
        with mock.patch.object(setup_main, "app_is_running", return_value=True), \
                mock.patch.object(setup_main.subprocess, "Popen") as popen:
            with self.assertRaisesRegex(setup_main.SetupError, "Close it"):
                setup_main.uninstall(self.dir)
        popen.assert_not_called()

    def fake_install(self):
        self.target.mkdir(parents=True)
        (self.target / "_internal").mkdir()
        (self.target / "_internal" / "lib.dll").write_text("x")
        (self.target / "Budgetier.exe").write_text("x")
        (self.target / "uninstall.exe").write_text("x")

    def test_uninstall_clears_shortcuts_entries_and_program_at_once(self):
        self.fake_install()
        links = self.dir / "links"
        links.mkdir()
        (links / "Budgetier.lnk").write_text("x")
        with mock.patch.object(setup_main, "app_is_running", return_value=False), \
                mock.patch.object(setup_main, "_shell_folders", return_value=(links,)), \
                mock.patch.object(setup_main.winreg, "DeleteKey") as delete, \
                mock.patch.object(setup_main, "finish_removal") as finish:
            setup_main.uninstall(self.target)
        self.assertFalse((links / "Budgetier.lnk").exists())
        self.assertEqual({c.args[0] for c in delete.call_args_list},
                         {setup_main.winreg.HKEY_LOCAL_MACHINE, setup_main.winreg.HKEY_CURRENT_USER})
        self.assertEqual([p.name for p in self.target.iterdir()], ["uninstall.exe"])
        finish.assert_called_once()

    def test_reinstall_works_over_what_an_uninstall_leaves(self):
        self.fake_install()
        setup_main.remove_program(self.target)
        self.assertEqual(setup_main.resolve_target(self.target), self.target)
        setup_main.unpack(self.payload({"Budgetier.exe": "new"}), self.target)
        self.assertEqual((self.target / "Budgetier.exe").read_text(), "new")

    def test_half_removed_program_folder_counts_as_ours(self):
        self.fake_install()
        (self.target / "Budgetier.exe").unlink()
        self.assertEqual(setup_main.resolve_target(self.target), self.target)

    def test_final_cleanup_waits_for_the_uninstaller_then_removes_the_folder(self):
        self.target.mkdir(parents=True)
        (self.target / "uninstall.exe").write_text("x")
        running = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
        self.addCleanup(running.kill)
        cleanup = setup_main.finish_removal(self.target, [running.pid])
        time.sleep(1.5)
        self.assertTrue(self.target.exists())
        running.kill()
        running.wait()
        cleanup.wait(timeout=20)
        self.assertFalse(self.target.exists())

    def test_cleanup_copes_with_an_apostrophe_in_the_path(self):
        odd = self.dir / "Mat's Apps" / "Budgetier"
        odd.mkdir(parents=True)
        setup_main.finish_removal(odd, [999999]).wait(timeout=20)
        self.assertFalse(odd.exists())

    def test_old_per_user_copy_is_found_even_with_the_new_entry_present(self):
        old = self.dir / "old"
        old.mkdir()
        (old / "Budgetier.exe").write_text("x")
        with mock.patch.object(setup_main, "app_is_running", return_value=False), \
                mock.patch.object(setup_main, "resolve_target", return_value=self.target), \
                mock.patch.object(setup_main, "check_writable"), \
                mock.patch.object(setup_main, "installed_location", return_value=self.target), \
                mock.patch.object(setup_main, "user_install_location", return_value=old), \
                mock.patch.object(setup_main, "unpack"), mock.patch.object(setup_main, "set_shortcuts"), \
                mock.patch.object(setup_main, "register"), \
                mock.patch.object(setup_main, "forget_user_registration") as forget:
            setup_main.install(setup_main.Options(self.target))
        self.assertFalse(old.exists())
        forget.assert_called_once()

    def test_app_is_started_as_the_signed_in_user_not_as_admin(self):
        with mock.patch.object(setup_main.subprocess, "Popen") as popen:
            setup_main.launch(self.target)
        self.assertEqual(popen.call_args[0][0], ["explorer.exe", str(self.target / "Budgetier.exe")])


if __name__ == "__main__":
    unittest.main()
