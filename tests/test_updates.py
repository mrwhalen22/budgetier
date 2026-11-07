"""Checking for a new version: quiet when it can't, and strict about what it runs."""
import hashlib
import io
import json
import unittest
import urllib.error
from unittest import mock

from budgetier import service, updates
from tests.support import Tmp

BASE = updates.DOWNLOADS + "v9.0.0/"
NAME = "Budgetier-Windows.exe"
PROGRAM = b"new program"


def feed(version="9.0.0", assets=(NAME, updates.CHECKSUMS), base=BASE):
    return json.dumps({"tag_name": f"v{version}", "assets": [
        {"name": n, "browser_download_url": base + n} for n in assets]}).encode()


def sums(body=PROGRAM, name=NAME, mark=" "):
    return f"{hashlib.sha256(body).hexdigest()} {mark}{name}\n".encode()


def server(pages):
    def fetch(url, timeout=updates.TIMEOUT):
        page = pages[url]
        if isinstance(page, Exception):
            raise page
        return io.BytesIO(page)
    return fetch


class Case(Tmp):
    def setUp(self):
        super().setUp()
        for target, value in (("sys.frozen", True), ("sys.platform", "win32")):
            patcher = mock.patch(f"budgetier.updates.{target}", value, create=True)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.updater = updates.Updater(self.dir, "1.4.0")

    def serve(self, **pages):
        site = {updates.LATEST: feed(), BASE + NAME: PROGRAM, BASE + updates.CHECKSUMS: sums()}
        names = {"latest": updates.LATEST, "program": BASE + NAME, "checksums": BASE + updates.CHECKSUMS}
        site.update({names[k]: v for k, v in pages.items()})
        patcher = mock.patch.object(updates, "_open", side_effect=server(site))
        self.addCleanup(patcher.stop)
        return patcher.start()


class Versions(unittest.TestCase):
    def test_numbers_compare_as_numbers(self):
        self.assertTrue(updates.is_newer("1.10.0", "1.9.9"))
        self.assertTrue(updates.is_newer("v2.0.0", "1.9.9"))
        self.assertFalse(updates.is_newer("1.4.0", "1.4.0"))
        self.assertFalse(updates.is_newer("1.3.9", "1.4.0"))

    def test_an_odd_version_is_never_newer(self):
        for latest, current in (("nightly", "1.0.0"), ("2.0.0-beta", "1.0.0"), ("2.0.0", "")):
            self.assertFalse(updates.is_newer(latest, current))

    def test_checksum_file_formats(self):
        self.assertEqual(updates.checksum_for(sums(mark="*").decode(), NAME), hashlib.sha256(PROGRAM).hexdigest())
        self.assertEqual(updates.checksum_for(sums().decode(), NAME), hashlib.sha256(PROGRAM).hexdigest())
        with self.assertRaises(updates.UpdateError):
            updates.checksum_for(sums(name="Other.exe").decode(), NAME)


class Checking(Case):
    def test_a_newer_release_is_offered(self):
        self.serve()
        self.assertEqual(self.updater.check(), {"available": True, "version": "9.0.0", "reopens": True})

    def test_the_same_version_is_not(self):
        self.serve(latest=feed("1.4.0"))
        self.assertFalse(self.updater.check()["available"])

    def test_a_startup_check_is_quiet_offline(self):
        self.serve(latest=urllib.error.URLError("offline"))
        self.assertFalse(self.updater.check()["available"])

    def test_a_check_by_hand_says_it_failed(self):
        self.serve(latest=urllib.error.URLError("offline"))
        with self.assertRaisesRegex(updates.UpdateError, "Couldn't check"):
            self.updater.check(True)

    def test_a_garbled_reply_is_a_failed_check(self):
        self.serve(latest=b"<html>")
        self.assertFalse(self.updater.check()["available"])

    def test_turned_off_means_no_network_at_startup(self):
        fetch = self.serve()
        self.updater.set_automatic(False)
        self.assertFalse(self.updater.check()["available"])
        fetch.assert_not_called()

    def test_turned_off_still_lets_you_check_by_hand(self):
        self.serve()
        self.updater.set_automatic(False)
        self.assertTrue(self.updater.check(True)["available"])

    def test_running_from_source_never_asks(self):
        fetch = self.serve()
        with mock.patch("budgetier.updates.sys.frozen", False, create=True):
            self.assertFalse(self.updater.check(True)["available"])
        fetch.assert_not_called()

    def test_a_release_missing_this_computers_file_is_skipped(self):
        self.serve(latest=feed(assets=(updates.CHECKSUMS,)))
        self.assertFalse(self.updater.check()["available"])

    def test_files_from_anywhere_else_are_skipped(self):
        self.serve(latest=feed(base="https://example.com/"))
        self.assertFalse(self.updater.check()["available"])

    def test_a_damaged_setting_leaves_it_on(self):
        self.updater.settings_path.write_text("{oops", encoding="utf-8")
        self.assertTrue(self.updater.automatic)


class Installing(Case):
    def install(self, **pages):
        self.serve(**pages)
        self.updater.check()
        with mock.patch.object(updates, "_run_installer") as run:
            try:
                return self.updater.install(), run
            except updates.UpdateError as e:
                e.run = run
                raise

    def test_a_matching_download_runs(self):
        result, run = self.install()
        self.assertEqual(result, {"closing": True})
        path = run.call_args[0][0]
        self.assertEqual(path.read_bytes(), PROGRAM)

    def test_a_damaged_download_never_runs(self):
        with self.assertRaisesRegex(updates.UpdateError, "checksum") as caught:
            self.install(program=b"something else")
        caught.exception.run.assert_not_called()
        self.assertEqual(list(self.updater.folder.iterdir()), [])

    def test_no_checksum_means_no_download(self):
        with self.assertRaisesRegex(updates.UpdateError, "no checksum") as caught:
            self.install(checksums=sums(name="Other.exe"))
        caught.exception.run.assert_not_called()

    def test_a_huge_download_is_stopped(self):
        with mock.patch.object(updates, "MOST_BYTES", 3), self.assertRaisesRegex(updates.UpdateError, "larger"):
            self.install()

    def test_a_dropped_connection_changes_nothing(self):
        with self.assertRaisesRegex(updates.UpdateError, "Couldn't download"):
            self.install(program=urllib.error.URLError("gone"))

    def test_it_only_installs_what_a_check_found(self):
        with self.assertRaisesRegex(updates.UpdateError, "Check for updates"):
            self.updater.install()

    def test_saying_no_to_windows_keeps_the_app_open(self):
        self.serve()
        self.updater.check()
        shell = mock.Mock()
        shell.shell32.ShellExecuteW.return_value = 5
        with mock.patch.object(updates.ctypes, "windll", shell, create=True), \
                self.assertRaisesRegex(updates.UpdateError, "nothing changed"):
            self.updater.install()
        args = shell.shell32.ShellExecuteW.call_args[0]
        self.assertEqual((args[1], args[3]), ("runas", updates.UPDATE_FLAG))

    def test_a_mac_opens_the_download_and_stays_open(self):
        with mock.patch.object(updates.sys, "platform", "darwin"), \
                mock.patch.object(updates.platform, "machine", return_value="arm64"):
            name = "Budgetier-macOS-Apple-Silicon.dmg"
            base = {updates.LATEST: feed(assets=(name, updates.CHECKSUMS)), BASE + name: PROGRAM,
                    BASE + updates.CHECKSUMS: sums(name=name)}
            with mock.patch.object(updates, "_open", side_effect=server(base)), \
                    mock.patch.object(updates.subprocess, "run") as run:
                self.updater.check()
                self.assertEqual(self.updater.install(), {"closing": False})
        self.assertEqual(run.call_args[0][0][0], "open")

    def test_linux_opens_the_download_with_the_desktop(self):
        with mock.patch.object(updates.sys, "platform", "linux"), mock.patch.object(updates.subprocess, "run") as run:
            updates._run_installer(Path("/tmp/Budgetier-Linux.tar.gz"))
        self.assertEqual(run.call_args[0][0], ["xdg-open", str(Path("/tmp/Budgetier-Linux.tar.gz"))])

    def test_an_old_installer_is_cleared_away(self):
        self.install()
        self.updater.clean()
        self.assertFalse(self.updater.folder.exists())

    def test_redirects_must_stay_encrypted(self):
        handler = updates._HttpsOnly()
        with self.assertRaises(updates.UpdateError):
            handler.redirect_request(mock.Mock(), None, 302, "", {}, "http://example.com/x")


class Page(Tmp):
    def test_the_page_is_told_whether_updates_apply(self):
        budget = service.Budget(self.dir / "home")
        self.addCleanup(budget.cancel)
        budget.refresh()
        page = budget.html_path.read_text(encoding="utf-8")
        self.assertIn('"updates":{"supported":false,"automatic":true}', page)


if __name__ == "__main__":
    unittest.main()
