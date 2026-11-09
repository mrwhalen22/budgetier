"""Encrypting the data folder: nothing about your money is readable on the disk without the
passcode or the recovery key, and every way in and out of it keeps the data whole."""
from pathlib import Path
from unittest import mock

from budgetier import storage, vault, views
from budgetier.service import Budget
from budgetier.storage import DataError, Locked
from budgetier.ui import locking, settings
from tests import fake
from tests.qt import QtCase
from tests.support import AppCase, Tmp

CODE = "correct horse"
PLAIN_NAMES = {"vault.json", "app.lock", "updates.json"}


def sealed(home: Path) -> Budget:
    """A made-up budget, then encrypted: its files, its backups, everything."""
    budget = fake.build(home)
    budget.ledger.save()  # leaves .bak copies beside the ledger's files
    settings.save(home, look={"mode": "dark", "palette": "plum"})
    locking.encrypt(home, CODE, 15, {"mode": "dark"})
    return budget


def readable(home: Path, words: bytes) -> list[str]:
    """Files on the disk where these words can be read as they are."""
    return [str(p.relative_to(home)) for p in home.rglob("*") if p.is_file() and words in p.read_bytes()]


class TheVault(Tmp):
    def setUp(self):
        super().setUp()
        self.addCleanup(storage.use_vault, None)

    def test_the_passcode_or_the_recovery_key_opens_it(self):
        opened, recovery = vault.create(self.dir, CODE)
        data = opened.encrypt(b"KROGER -45.00")
        self.assertTrue(data.startswith(vault.MAGIC))
        self.assertNotIn(b"KROGER", data)
        self.assertEqual(vault.open_with(self.dir, CODE).decrypt(data), b"KROGER -45.00")
        self.assertEqual(vault.open_with_recovery(self.dir, recovery.lower().replace("-", " ")).decrypt(data),
                         b"KROGER -45.00")
        for wrong in ("correct horsE", ""):
            with self.assertRaises(vault.WrongKey):
                vault.open_with(self.dir, wrong)
        with self.assertRaises(vault.WrongKey):
            vault.open_with_recovery(self.dir, "AAAAA-AAAAA-AAAAA-AAAAA-AAAAA")
        self.assertNotIn(CODE, vault.header_path(self.dir).read_text(encoding="utf-8"))

    def test_a_new_passcode_or_recovery_key_rewrites_nothing_and_retires_the_old(self):
        opened, recovery = vault.create(self.dir, CODE)
        data = opened.encrypt(b"x")
        opened.change_passcode("new passcode")
        self.assertFalse(vault.check(self.dir, CODE))
        self.assertEqual(vault.open_with(self.dir, "new passcode").decrypt(data), b"x")
        fresh = opened.new_recovery_key()
        with self.assertRaises(vault.WrongKey):
            vault.open_with_recovery(self.dir, recovery)
        self.assertEqual(vault.open_with_recovery(self.dir, fresh).decrypt(data), b"x")

    def test_a_changed_file_is_refused_not_misread(self):
        opened, _ = vault.create(self.dir, CODE)
        storage.use_vault(opened)
        path = self.dir / "budgets.json"
        storage.write_files({path: '{"Dining": 1}'})
        raw = bytearray(path.read_bytes())
        raw[-1] ^= 1
        path.write_bytes(bytes(raw))
        with self.assertRaises(DataError):
            storage.read_text(path)

    def test_what_stays_readable(self):
        opened, _ = vault.create(self.dir, CODE)
        for name in ("vault.json", "app.lock", "updates.json", "logs/app.log", "inbox/new.csv", "output/x.xlsx", "a.tmp"):
            self.assertFalse(opened.covers(self.dir / name), name)
        for name in ("data/ledger.csv", "settings.json", "imported/chase.csv", "data/ledger.csv.bak", "notes.json"):
            self.assertTrue(opened.covers(self.dir / name), name)
        self.assertFalse(opened.covers(Path(self.dir).parent / "elsewhere.csv"))

    def test_the_packaged_app_can_check_it(self):
        self.assertTrue(vault.self_test())


class AFolder(Tmp):
    def setUp(self):
        super().setUp()
        self.addCleanup(storage.use_vault, None)
        self.home = Path(self.dir) / "home"
        self.budget = sealed(self.home)
        self.before = views.from_budget(self.budget)

    def test_nothing_about_your_money_can_be_read_on_the_disk(self):
        for words in (b"KROGER", b"LAKESIDE", b"Groceries", b"Dining", b"plum", b"Bank Checking"):
            self.assertEqual(readable(self.home, words), [], words)
        names = {p.name for p in self.home.rglob("*") if p.is_file() and not p.read_bytes().startswith(vault.MAGIC)}
        self.assertLessEqual(names, PLAIN_NAMES)

    def test_it_opens_the_same_with_the_passcode_and_not_at_all_without(self):
        storage.use_vault(None)
        with self.assertRaises(Locked):
            Budget(self.home)
        storage.use_vault(vault.open_with(self.home, CODE))
        after = views.from_budget(Budget(self.home))
        self.assertEqual(after.txns, self.before.txns)
        self.assertEqual(after.budget_targets, self.before.budget_targets)
        self.assertEqual(settings.load(self.home)["look"]["palette"], "plum")

    def test_changes_are_saved_encrypted_and_can_be_undone(self):
        budget = Budget(self.home)
        budget.undoable(budget.save_budget, "Shopping", "amount", "100")
        self.assertTrue(budget.budgets_path.read_bytes().startswith(vault.MAGIC))
        self.assertIn("Shopping", Budget(self.home).budgets())
        budget.undo()
        self.assertNotIn("Shopping", Budget(self.home).budgets())

    def test_stopping_partway_still_opens_and_finishing_picks_up(self):
        opened = storage.open_vault()
        ledger = self.home / "data" / "ledger.csv"
        ledger.write_bytes(opened.decrypt(ledger.read_bytes()))  # as if it stopped before this one
        self.assertEqual(views.from_budget(Budget(self.home)).txns, self.before.txns)
        self.assertEqual(storage.seal_folder(opened), 1)
        self.assertTrue(ledger.read_bytes().startswith(vault.MAGIC))

    def test_turned_off_everything_is_plain_again(self):
        locking.decrypt(self.home)
        self.assertIsNone(storage.open_vault())
        self.assertFalse(vault.header_path(self.home).exists())
        self.assertEqual([p for p in self.home.rglob("*") if p.is_file() and p.read_bytes().startswith(vault.MAGIC)], [])
        self.assertEqual(views.from_budget(Budget(self.home)).txns, self.before.txns)


class Importing(AppCase):
    def test_a_kept_copy_is_encrypted_and_still_rebuilds_an_account(self):
        self.addCleanup(storage.use_vault, None)
        locking.encrypt(self.budget.home, CODE, 0, {})
        self.add(self.chase("first.csv", [1, 2, 3]))
        self.add(self.chase("second.csv", [3, 4, 5]))
        kept = list((self.budget.home / "imported").iterdir())
        self.assertTrue(kept and all(p.read_bytes().startswith(vault.MAGIC) for p in kept))
        self.assertEqual(readable(self.budget.home, b"SHOP 4"), [])
        key = next(i for i in self.budget.ledger.imports if i["file"] == "second.csv")
        self.budget.remove_import(key.get("stored") or key["file"])  # replays first.csv from its encrypted copy
        self.assertEqual(self.rows(), ["SHOP 1", "SHOP 2", "SHOP 3"])


class TheCommandLine(Tmp):
    def test_it_asks_for_the_passcode(self):
        from budgetier import cli
        self.addCleanup(storage.use_vault, None)
        home = Path(self.dir) / "home"
        sealed(home)
        storage.use_vault(None)
        with mock.patch("getpass.getpass", side_effect=["nope", CODE]), mock.patch("builtins.print"):
            self.assertTrue(cli._unlock(home))
        self.assertIsNotNone(storage.open_vault())
        storage.use_vault(None)
        with mock.patch("getpass.getpass", side_effect=["a", "b", "c"]), mock.patch("builtins.print"):
            self.assertFalse(cli._unlock(home))


class InTheWindow(QtCase):
    def setUp(self):
        super().setUp()
        self.addCleanup(storage.use_vault, None)

    def test_turning_it_on_shows_the_recovery_key_until_its_saved(self):
        from budgetier.ui.dialogs import Dialog
        win = self.window()
        dialog = locking.setup(win)
        f = dialog.fields
        f["new"].setText("short")
        f["again"].setText("short")
        dialog.main.click()
        self.assertIn("at least", dialog.error.text())
        f["new"].setText(CODE)
        f["again"].setText(CODE)
        dialog.main.click()
        self.assertTrue(win.runner.wait())
        self.assertIsNotNone(locking.saved(self.budget.home))
        self.assertTrue((self.budget.home / "data" / "ledger.csv").read_bytes().startswith(vault.MAGIC))
        [shown] = [d for d in win.findChildren(Dialog) if d.isVisible() and d.windowTitle() == "Save your recovery key"]
        self.assertFalse(shown.main.isEnabled())
        shown.kept.setChecked(True)
        self.assertTrue(shown.main.isEnabled())
        self.assertTrue(win.away.timer.isActive())

    def test_time_away_locks_and_only_the_passcode_unlocks(self):
        locking.encrypt(self.budget.home, CODE, 5, {})
        win = self.window()
        win.lock()
        self.assertTrue(win.locked)
        self.assertFalse(win.centralWidget().isVisibleTo(win))
        win.lock_screen.code.setText("wrong one")
        win.lock_screen.attempt()
        self.assertTrue(win.locked)
        win.lock_screen.code.setText(CODE)
        win.lock_screen.attempt()
        self.assertFalse(win.locked)
        self.assertEqual(win.away.timer.interval(), 5 * 60_000)

    def test_changing_the_passcode_and_turning_it_off(self):
        locking.encrypt(self.budget.home, CODE, 15, {})
        win = self.window()
        dialog = locking.setup(win)
        f = dialog.fields
        f["current"].setText(CODE)
        f["new"].setText("another passcode")
        f["again"].setText("another passcode")
        dialog.main.click()
        self.assertTrue(vault.check(self.budget.home, "another passcode"))
        dialog = locking.setup(win)
        dialog.fields["current"].setText("another passcode")
        [off] = [b for b in dialog.buttons if b.text() == "Turn off"]
        off.click()
        from budgetier.ui.dialogs import Dialog
        [sure] = [d for d in win.findChildren(Dialog) if d.isVisible() and d.windowTitle() == "Turn off encryption?"]
        sure.main.click()
        self.assertTrue(win.runner.wait())
        self.assertIsNone(locking.saved(self.budget.home))
        self.assertFalse((self.budget.home / "data" / "ledger.csv").read_bytes().startswith(vault.MAGIC))


class WhenItOpens(QtCase):
    def setUp(self):
        super().setUp()
        self.addCleanup(storage.use_vault, None)
        locking.encrypt(self.budget.home, CODE, 15, {})
        self.recovery = None
        storage.use_vault(None)

    def test_the_passcode(self):
        ask = locking.Unlock(self.budget.home)
        ask.code.setText("nope")
        ask.attempt()
        self.assertIsNone(ask.opened)
        self.assertEqual(ask.said.text(), "That isn't it. Try again.")
        ask.code.setText(CODE)
        ask.attempt()
        self.assertIsNotNone(ask.opened)

    def test_the_recovery_key_then_a_new_passcode(self):
        opened = vault.open_with(self.budget.home, CODE)
        key = opened.new_recovery_key()
        ask = locking.Unlock(self.budget.home)
        ask.use_recovery(True)
        ask.code.setText(key)
        ask.attempt()
        choose = locking.NewPasscode(ask.opened)
        choose.new.setText("brand new one")
        choose.again.setText("brand new one")
        choose.save()
        self.assertTrue(vault.check(self.budget.home, "brand new one"))
        self.assertFalse(vault.check(self.budget.home, CODE))

    def test_quitting_opens_nothing(self):
        from PySide6.QtWidgets import QDialog
        with mock.patch.object(locking.Unlock, "exec", return_value=QDialog.Rejected):
            self.assertFalse(locking.unlock_at_start(self.budget.home))
        self.assertIsNone(storage.open_vault())
