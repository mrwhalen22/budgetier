"""The design system stays one system: every look comes from tokens, and every theme reads."""
import re
import unittest

from budgetier import report_html

PAGE = report_html.page()
STYLE = PAGE[PAGE.index("<style>") + 7:PAGE.index("</style>")]
TEMPLATES = PAGE[PAGE.index("</style>"):]
CSS = re.sub(r"/\*.*?\*/", "", STYLE, flags=re.S)
TOKENS_END = CSS.index("* { box-sizing")
TOKENS, RULES = CSS[:TOKENS_END], CSS[TOKENS_END:]
PALETTES, MODES = ("pine", "ocean", "plum"), ("light", "dark")

# (text, background, smallest contrast). 4.5 is the WCAG AA level for text, 3 for large marks.
PAIRS = [("ink", "page", 4.5), ("ink", "surface", 4.5), ("ink", "raised", 4.5), ("ink", "nav", 4.5),
         ("ink-2", "page", 4.5), ("ink-2", "surface", 4.5), ("ink-2", "raised", 4.5), ("ink-2", "nav", 4.5),
         ("muted", "page", 4.5), ("muted", "surface", 4.5), ("muted", "raised", 4.5), ("muted", "nav", 4.5),
         ("on-accent", "accent", 4.5), ("ink", "accent-soft", 4.5), ("accent", "surface", 3), ("accent", "nav", 3),
         ("good", "surface", 4.5), ("good", "raised", 4.5), ("bad", "surface", 4.5), ("bad", "raised", 4.5),
         ("good", "good-bg", 4.5), ("bad", "bad-bg", 4.5), ("warn-ink", "warn-bg", 4.5), ("info-ink", "info-bg", 4.5),
         ("on-bad", "bad", 4.5), ("surface", "ink", 4.5)]


def block(selector):
    found = re.search(re.escape(selector) + r"\s*\{(.*?)\}", TOKENS, re.S)
    return dict(re.findall(r"--([\w-]+):\s*(#[0-9a-fA-F]{6})", found.group(1)))


def theme(palette, mode):
    return {**block(f'[data-mode="{mode}"]'), **block(f'[data-mode="{mode}"][data-palette="{palette}"]')}


def luminance(color):
    channels = [int(color[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    r, g, b = (c / 12.92 if c <= .03928 else ((c + .055) / 1.055) ** 2.4 for c in channels)
    return .2126 * r + .7152 * g + .0722 * b


def contrast(a, b):
    high, low = sorted((luminance(a), luminance(b)), reverse=True)
    return (high + .05) / (low + .05)


class Themes(unittest.TestCase):
    def test_every_theme_is_readable_in_both_modes(self):
        for palette in PALETTES:
            for mode in MODES:
                colors = theme(palette, mode)
                for text, background, least in PAIRS:
                    with self.subTest(palette=palette, mode=mode, text=text, on=background):
                        self.assertGreaterEqual(contrast(colors[text], colors[background]), least)

    def test_every_theme_defines_the_same_tokens(self):
        keys = {frozenset(block(f'[data-mode="{m}"][data-palette="{p}"]')) for p in PALETTES for m in MODES}
        self.assertEqual(len(keys), 1)
        self.assertEqual(len({frozenset(block(f'[data-mode="{m}"]')) for m in MODES}), 1)

    def test_money_means_the_same_in_every_theme(self):
        for mode in MODES:
            for palette in PALETTES:
                self.assertNotIn("good", block(f'[data-mode="{mode}"][data-palette="{palette}"]'))

    def test_every_token_used_exists(self):
        defined = set(re.findall(r"--([\w-]+):", TOKENS)) | {"m"}
        used = set(re.findall(r"var\(--([\w-]+)", CSS + TEMPLATES)) | set(re.findall(r'CSS\("([a-z][\w-]*)"\)', TEMPLATES))
        used |= {f"c{i}" for i in range(8)}
        self.assertEqual(sorted(used - defined), [])

    def test_the_picker_offers_every_palette(self):
        self.assertEqual(tuple(re.findall(r'\["(\w+)", "[A-Z]\w+"\]', PAGE[:PAGE.index("<style>")])), PALETTES)


class SourceFiles(unittest.TestCase):
    def test_every_file_is_part_of_the_page(self):
        found = {p.relative_to(report_html.SOURCE).as_posix() for p in report_html.SOURCE.rglob("*") if p.is_file()}
        listed = {*report_html.STYLES, *report_html.SCRIPTS, "js/boot.js", "index.html"}
        self.assertEqual(found, listed)

    def test_nothing_is_left_waiting_to_be_filled_but_the_data(self):
        self.assertEqual(re.findall(r"/\*__\w+__\*/", PAGE), ["/*__DATA__*/"])


class OneSystem(unittest.TestCase):
    def test_colors_only_appear_as_tokens(self):
        self.assertEqual(re.findall(r"#[0-9a-fA-F]{3,8}\b|rgba?\(", RULES), [])

    def test_templates_write_no_colors_of_their_own(self):
        self.assertEqual(re.findall(r'(?:color|background|fill|stroke)[:=]"?\s*#[0-9a-fA-F]{3,8}', TEMPLATES), [])

    def test_font_sizes_come_from_the_scale(self):
        sizes = re.findall(r"font-size:\s*([^;}]+)", RULES)
        self.assertEqual([s for s in sizes if not s.strip().startswith("var(--text-")], [])
        self.assertEqual(re.findall(r"font:[^;]*?\b\d+(?:\.\d+)?px", RULES), [])

    def test_corners_come_from_the_scale(self):
        radii = re.findall(r"border-radius:\s*([^;}]+)", RULES)
        allowed = [r for r in radii if not r.strip().startswith("var(--radius-")]
        self.assertEqual(allowed, ["3px 3px 1px 1px"])  # the sparkline's flat-bottomed bars

    def test_inline_styles_only_carry_data(self):
        styles = re.findall(r'style="([^"]*)"', TEMPLATES)
        data = re.compile(r"(background:\$\{|background:color-mix|width:\$\{|height:\$\{|flex:\$\{|--m:)")
        self.assertEqual([s for s in styles if not data.match(s)], [])

    def test_no_important_overrides(self):
        self.assertNotIn("!important", CSS)

    def test_each_selector_is_only_styled_in_one_place(self):
        """Later rules patching earlier ones is how the old sheet drifted."""
        top = re.sub(r"@media[^{]*\{(?:[^{}]*\{[^{}]*\})*[^{}]*\}", "", RULES)
        selectors = [s.strip() for s in re.findall(r"(?:^|\})\s*([^{}@]+?)\s*\{", top)]
        repeats = {s for s in selectors if selectors.count(s) > 1}
        self.assertEqual(repeats, set())

    def test_every_paragraph_closes_as_a_paragraph(self):
        """A <p> closed by </div> ends its parent early, and spills what follows out of it."""
        self.assertEqual(re.findall(r"<p[ >](?:(?!</p>|<p[ >]).)*?</div>(?:(?!<p[ >]).)*?</p>", TEMPLATES, re.S), [])
        self.assertEqual(re.findall(r'<p class="sub">(?:(?!</p>).)*?</div>', TEMPLATES, re.S), [])

    def test_every_button_is_the_one_button(self):
        for classes in re.findall(r'<button class="([^"$]*)"', TEMPLATES):
            first = classes.split()[0]
            self.assertIn(first, ("btn", "swatch", "nav-link"), classes)


class Dialogs(unittest.TestCase):
    def test_esc_goes_through_the_dialogs_own_button(self):
        """Closing can have work to finish, which the browser's own Esc would skip."""
        self.assertIn('modal.addEventListener("cancel"', TEMPLATES)
        self.assertRegex(TEMPLATES, r'e\.key === "Escape"\) \{ e\.preventDefault\(\); return dismissModal')

    def test_every_form_enter_saves_has_its_button(self):
        names = re.search(r"ENTER_SAVES = \[(.*?)\]", TEMPLATES).group(1)
        for name in re.findall(r'"([\w-]+)"', names):
            self.assertIn(f'data-modal="{name}"', TEMPLATES)

    def test_every_saved_change_says_so(self):
        self.assertEqual(re.findall(r"^\s*reload\(\);", TEMPLATES, re.M), [])


class ReachableByKeyboard(unittest.TestCase):
    def test_sorting_is_done_with_real_buttons(self):
        self.assertIn('<button type="button" data-sort=', TEMPLATES)
        self.assertNotIn("<th data-sort", TEMPLATES)

    def test_every_chart_goes_through_the_one_that_can_be_read(self):
        self.assertEqual(TEMPLATES.count("<svg viewBox=\"0 0 ${f.W}"), 1)
        self.assertRegex(TEMPLATES, r'role="img" tabindex="0" aria-label="\$\{esc\(label\)\}"')

    def test_dialogs_are_named_and_errors_are_announced(self):
        self.assertIn('aria-labelledby="modalTitle"', TEMPLATES)
        self.assertIn('id="modalMsg" role="alert"', TEMPLATES)


class RedMeansAProblem(unittest.TestCase):
    def test_transactions_and_largest_arent_red(self):
        self.assertIn('<td class="num ${gain(t.amt)}">', TEMPLATES)
        self.assertNotIn('class="num neg"', TEMPLATES)

    def test_going_over_still_is(self):
        self.assertIn('left < 0 ? "neg" : "pos"', TEMPLATES)


class Words(unittest.TestCase):
    def test_taking_something_out_is_always_remove(self):
        self.assertNotRegex(TEMPLATES, r">Delete<|\"Delete |`Delete ")

    def test_backing_out_is_always_cancel(self):
        self.assertNotRegex(TEMPLATES, r">Keep it<|\"Not now\"|>Not now<|>Dismiss<")

    def test_disconnecting_says_disconnect(self):
        self.assertRegex(TEMPLATES, r'removal\(api\(\)\.disconnect_bank\(\), "Disconnected\."\), "Disconnect"\)')


if __name__ == "__main__":
    unittest.main()
