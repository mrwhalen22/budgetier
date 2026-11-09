"""The Qt window: its tabs, its look, and how it opens. See docs/qt-migration.md."""
import json
import re
import unittest
from pathlib import Path
from unittest import mock

from budgetier import storage
from tests.qt import QtCase
from tests.support import Tmp

ROOT = Path(__file__).resolve().parents[1]


class Theme(Tmp):
    def setUp(self):
        super().setUp()
        from budgetier.ui import theme  # needs no Qt until it styles a window
        self.theme = theme

    def test_every_look_has_every_token(self):
        names = None
        for mode in ("light", "dark"):
            for palette, _ in self.theme.PALETTES:
                found = set(self.theme.tokens(mode, palette))
                names = names or found
                self.assertEqual(found, names, (mode, palette))

    def test_the_style_sheet_has_only_real_colors(self):
        for mode in ("light", "dark"):
            sheet = self.theme.style_sheet(self.theme.tokens(mode, "pine"))
            self.assertNotIn("var(", sheet)
            self.assertNotRegex(sheet, r"\{[A-Za-z_]+\[")  # a value the f-string left unfilled
            for alpha in re.findall(r"rgba\(\d+, \d+, \d+, ([^)]+)\)", sheet):
                self.assertTrue(alpha.isdigit() and 0 <= int(alpha) <= 255, alpha)

    def test_the_look_starts_as_the_system_in_pine(self):
        self.assertEqual(self.theme.load_look(self.dir), self.theme.Look("system", "pine"))

    def test_a_chosen_look_is_kept_with_other_settings(self):
        (self.dir / "settings.json").write_text(json.dumps({"other": 1}), encoding="utf-8")
        self.theme.save_look(self.dir, self.theme.Look("dark", "plum"))
        self.assertEqual(self.theme.load_look(self.dir), self.theme.Look("dark", "plum"))
        self.assertEqual(json.loads((self.dir / "settings.json").read_text(encoding="utf-8"))["other"], 1)

    def test_a_damaged_or_odd_look_falls_back(self):
        for saved in ("{not json", json.dumps([1]), json.dumps({"look": "dark"}),
                      json.dumps({"look": {"mode": "neon", "palette": "plum"}})):
            with self.subTest(saved):
                (self.dir / "settings.json").write_text(saved, encoding="utf-8")
                look = self.theme.load_look(self.dir)
                self.assertIn(look.mode, self.theme.MODES)
                self.assertIn(look.palette, dict(self.theme.PALETTES))

    def test_system_follows_the_system(self):
        look = self.theme.Look("system", "pine")
        self.assertEqual(self.theme.mode_for(look, True), "dark")
        self.assertEqual(self.theme.mode_for(look, False), "light")
        self.assertEqual(self.theme.mode_for(self.theme.Look("light", "pine"), True), "light")


class Window(QtCase):
    def test_the_sidebar_lists_every_tab_in_order(self):
        from budgetier.ui.app import TABS
        window = self.window()
        self.assertEqual([b.text() for b in window.tab_group.buttons()], list(TABS))

    def test_it_opens_on_the_overview(self):
        window = self.window()
        self.assertEqual(window.tab, "Overview")
        self.assertEqual(window.title.text(), "Overview")

    def test_each_tab_opens_by_its_button(self):
        from budgetier.ui.app import TABS
        window = self.window()
        for tab in [t for t in TABS if window.offered(t)]:
            window.tab_buttons[tab].click()
            self.assertEqual(window.tab, tab)
            self.assertEqual(window.title.text(), tab)
            self.assertEqual([t for t, b in window.tab_buttons.items() if b.isChecked()], [tab])

    def test_every_tab_draws_in_every_look(self):
        from budgetier.ui import theme
        from budgetier.ui.app import TABS
        window = self.window()
        for palette, _ in theme.PALETTES:
            for mode in ("light", "dark"):
                window.set_look(theme.Look(mode, palette))
                self.assertEqual(window.mode, mode)
                for tab in TABS:
                    window.show_tab(tab)
                    self.assertFalse(window.grab().isNull(), (palette, mode, tab))

    def test_a_chosen_look_is_saved_in_the_data_folder(self):
        from budgetier.ui import theme
        window = self.window()
        window.set_look(theme.Look("dark", "ocean"))
        self.assertEqual(theme.load_look(self.budget.home), theme.Look("dark", "ocean"))
        self.assertIn("#0a1016", self.app.styleSheet())  # ocean's dark page

    def test_the_window_has_room_for_the_tabs(self):
        window = self.window()
        self.assertGreaterEqual(window.minimumWidth(), 900)
        self.assertGreaterEqual(window.minimumHeight(), 620)


class BankText(QtCase):
    """Bank text is whatever the bank sent, so it must only ever show as text."""

    def test_hostile_descriptions_show_as_plain_text(self):
        from PySide6.QtCore import Qt

        from budgetier.ui import widgets
        for value in ("<b>bold</b>", "<img src=x>", '<a href="https://example.com">pay here</a>', "<!-- <script>", "&amp;"):
            with self.subTest(value):
                label = widgets.text(value)
                self.assertEqual(label.textFormat(), Qt.PlainText)
                self.assertEqual(label.text(), value)
                self.assertFalse(label.openExternalLinks())


class Opening(QtCase):
    def test_a_folder_already_open_is_refused(self):
        from budgetier.ui import __main__ as entry
        home = self.dir / "open"
        home.mkdir()
        held = storage.hold_lock(home)
        self.addCleanup(held.close)
        with mock.patch("budgetier.app._alert") as alert, mock.patch("budgetier.app.logging.basicConfig"), \
                mock.patch("budgetier.app.logging.handlers.RotatingFileHandler"):
            self.assertEqual(entry.main(["--home", str(home)]), 1)
        self.assertIn("already open", alert.call_args[0][0])

    def test_it_opens_the_folder_it_is_given(self):
        from budgetier.ui import __main__ as entry
        home = self.dir / "chosen"
        with mock.patch("budgetier.ui.app.QApplication.exec", return_value=0), mock.patch("budgetier.app.logging.basicConfig"), \
                mock.patch("budgetier.app.logging.handlers.RotatingFileHandler"):
            self.assertEqual(entry.main(["--home", str(home)]), 0)
        self.assertTrue((home / "rules.csv").exists())
        again = storage.hold_lock(home)  # it let go when it closed
        self.assertIsNotNone(again)
        again.close()


if __name__ == "__main__":
    unittest.main()
