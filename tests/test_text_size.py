"""Text size, chosen under Appearance: the style sheet and the widgets that draw their own text follow it."""
import unittest

from tests.qt import QtCase
from tests.support import Tmp


class Saved(Tmp):
    def test_it_is_kept_with_the_look(self):
        from budgetier.ui import theme
        theme.save_look(self.dir, theme.Look("dark", "plum", "large"))
        self.assertEqual(theme.load_look(self.dir), theme.Look("dark", "plum", "large"))

    def test_an_unknown_size_is_the_default(self):
        from budgetier.ui import settings, theme
        settings.save(self.dir, look={"mode": "dark", "palette": "plum", "size": "gigantic"})
        self.assertEqual(theme.load_look(self.dir).size, "default")


class Scaled(unittest.TestCase):
    def test_the_style_sheet_scales_every_text_size(self):
        from budgetier.ui import theme
        t = theme.tokens("light", "pine")
        plain, big = theme.style_sheet(t), theme.style_sheet(t, 1.3)
        self.assertIn(f"font-size: {theme.TEXT['sm']}px", plain)
        self.assertIn(f"font-size: {round(theme.TEXT['sm'] * 1.3)}px", big)
        self.assertIn(f"font-size: {round(theme.TEXT['4xl'] * 1.3)}px", big)  # 68: no default size is that big
        self.assertNotIn(f"font-size: {theme.TEXT['4xl']}px", big)

    def test_every_size_has_a_scale(self):
        from budgetier.ui import theme
        self.assertEqual([theme.scale_for(name) for name, _, _ in theme.SIZES], [.9, 1.0, 1.15, 1.3])
        self.assertEqual(theme.scale_for("nonsense"), 1.0)


class InTheWindow(QtCase):
    def tearDown(self):
        from budgetier.ui import theme
        theme._scale = 1.0  # the next test's window starts at the default
        super().tearDown()

    def test_choosing_a_size_restyles_and_keeps_the_rest_of_the_look(self):
        from budgetier.ui import look, theme
        win = self.window()
        win.set_look(theme.Look("dark", "ocean"))
        dialog = look.appearance(win)
        [largest] = [b for b in dialog.size_buttons if b.text() == "Largest"]
        largest.click()
        self.assertEqual(win.look, theme.Look("dark", "ocean", "larger"))
        self.assertEqual(theme.load_look(self.budget.home).size, "larger")
        self.assertEqual(theme.px("sm"), round(theme.TEXT["sm"] * 1.3))
        self.assertIn(f"font-size: {round(theme.TEXT['sm'] * 1.3)}px", self.app.styleSheet())
        [light] = [b for b in dialog.mode_buttons if b.text() == "Light"]
        light.click()
        self.assertEqual(win.look.size, "larger")  # changing the mode keeps the size
        dialog.dismiss()

    def test_charts_make_room_for_bigger_labels(self):
        from budgetier.ui import theme
        from budgetier.ui.charts import LEFT, Chart
        win = self.window()
        win.set_look(theme.Look("light", "pine", "larger"))
        win.show_tab("Spending")
        chart = win.pages["Spending"].widget().findChildren(Chart)[0]
        self.assertEqual(chart.left, round(LEFT * 1.3))
