"""How the window looks: the color tokens, the look a person chose, and the style sheet.

Every color the window uses comes from here.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from . import settings

MODES = ("system", "light", "dark")
PALETTES = (("pine", "Pine"), ("ocean", "Ocean"), ("plum", "Plum"))

# Sizes in pixels, the same in every theme. Text is scaled by the size chosen in Appearance.
TEXT = {"xs": 12, "sm": 13, "md": 14, "lg": 16, "xl": 20, "2xl": 26, "3xl": 34, "4xl": 52}
SIZES = (("small", "Smaller", .9), ("default", "Default", 1.0), ("large", "Larger", 1.15), ("larger", "Largest", 1.3))
SPACE = {1: 4, 2: 8, 3: 12, 4: 16, 5: 20, 6: 24, 8: 32, 10: 40}
RADIUS = {"sm": 6, "md": 10, "lg": 14}
CONTROL, CONTROL_SM = 36, 28
CHEVRON = 28  # the room a dropdown keeps at its right for its arrow

MODE_TOKENS = {
    "light": {
        "good": "#0b6b34", "bad": "#b3232a", "on-bad": "#ffffff",
        "good-bg": "#e2f2e8", "bad-bg": "#fbe8e6", "warn-bg": "#fbf1da", "warn-ink": "#5e4306", "info-bg": "#e7eff7",
        "info-ink": "#1b456e", "income": "#1f9d55", "spending": "#e34948", "other": "#a9a79f",
        "c0": "#2a78d6", "c1": "#eb6834", "c2": "#1baf7a", "c3": "#eda100", "c4": "#e87ba4", "c5": "#0e94b8",
        "c6": "#6250d6", "c7": "#9c6b4e",
        "line-soft": "rgba(23, 32, 28, .08)", "hover": "rgba(23, 32, 28, .05)", "scrim": "rgba(8, 14, 12, .5)",
    },
    "dark": {
        "good": "#4ccb84", "bad": "#f28b86", "on-bad": "#2a0d0c",
        "good-bg": "#12301f", "bad-bg": "#3a1a19", "warn-bg": "#30270f", "warn-ink": "#f2cf7c", "info-bg": "#15263a",
        "info-ink": "#a5c8ee", "income": "#2fb36a", "spending": "#e66767", "other": "#6f6d68",
        "c0": "#3987e5", "c1": "#d95926", "c2": "#199e70", "c3": "#c98500", "c4": "#d55181", "c5": "#2aa9cc",
        "c6": "#9085e9", "c7": "#b98c6f",
        "line-soft": "rgba(255, 255, 255, .09)", "hover": "rgba(255, 255, 255, .06)", "scrim": "rgba(0, 0, 0, .6)",
    },
}

PALETTE_TOKENS = {
    ("light", "pine"): {"page": "#f4f2ec", "surface": "#fffefb", "raised": "#f9f7f1", "nav": "#ebe8df", "line": "#e2ded2",
                        "ink": "#17201c", "ink-2": "#46514b", "muted": "#5d675f",
                        "accent": "#7d6128", "on-accent": "#fffdf7", "accent-soft": "#f1e8d3"},
    ("dark", "pine"): {"page": "#0b100e", "surface": "#141b18", "raised": "#1a221e", "nav": "#0e1512", "line": "#27312c",
                       "ink": "#eef1ec", "ink-2": "#b9c2bc", "muted": "#929c95",
                       "accent": "#d6b06a", "on-accent": "#17201c", "accent-soft": "#2e2817"},
    ("light", "ocean"): {"page": "#f1f4f7", "surface": "#ffffff", "raised": "#f6f8fb", "nav": "#e5ebf2", "line": "#d9e1e9",
                         "ink": "#14202b", "ink-2": "#43525f", "muted": "#566675",
                         "accent": "#1f63b5", "on-accent": "#ffffff", "accent-soft": "#e0ecf8"},
    ("dark", "ocean"): {"page": "#0a1016", "surface": "#121a22", "raised": "#18222c", "nav": "#0d141b", "line": "#24313d",
                        "ink": "#ebf0f5", "ink-2": "#b4c0cc", "muted": "#8f9dab",
                        "accent": "#6aa9ee", "on-accent": "#0b1620", "accent-soft": "#16283b"},
    ("light", "plum"): {"page": "#f6f2f6", "surface": "#fffdff", "raised": "#f9f5f9", "nav": "#eee6ee", "line": "#e4dae4",
                        "ink": "#221a24", "ink-2": "#544857", "muted": "#685b6b",
                        "accent": "#7a3f94", "on-accent": "#ffffff", "accent-soft": "#f0e3f5"},
    ("dark", "plum"): {"page": "#110c13", "surface": "#1a141d", "raised": "#211a25", "nav": "#140f17", "line": "#332a38",
                       "ink": "#f3eef5", "ink-2": "#c4b9c8", "muted": "#a094a6",
                       "accent": "#c89be0", "on-accent": "#1d1222", "accent-soft": "#2c2033"},
}


@dataclass(frozen=True)
class Look:
    mode: str = "system"
    palette: str = "pine"
    size: str = "default"  # how big text is: one of SIZES


def load_look(home: Path) -> Look:
    """A look that can't be read is worth nothing more than the default."""
    return read_look(settings.load(home).get("look"))


def read_look(saved) -> Look:
    if not isinstance(saved, dict):
        saved = {}
    mode = saved.get("mode") if saved.get("mode") in MODES else Look.mode
    palette = saved.get("palette") if saved.get("palette") in dict(PALETTES) else Look.palette
    size = saved.get("size") if saved.get("size") in {name for name, _, _ in SIZES} else Look.size
    return Look(mode, palette, size)


def save_look(home: Path, look: Look) -> None:
    settings.save(home, look={"mode": look.mode, "palette": look.palette, "size": look.size})


def scale_for(size: str) -> float:
    return next((scale for name, _, scale in SIZES if name == size), 1.0)


_scale = 1.0  # the text size applied last


def px(size: str | int) -> int:
    """A text size in pixels at the size chosen: a name from TEXT, or pixels at the default size.
    For widgets that draw their own text, which the style sheet doesn't reach."""
    return round((TEXT[size] if isinstance(size, str) else size) * _scale)


def mode_for(look: Look, system_dark: bool) -> str:
    if look.mode == "system":
        return "dark" if system_dark else "light"
    return look.mode


def mix(a: str, b: str, share: float) -> str:
    """Two #rrggbb colors blended, `share` of the way from a to b."""
    x, y = (tuple(int(c[i:i + 2], 16) for i in (1, 3, 5)) for c in (a, b))
    return "#" + "".join(f"{round(p + (q - p) * share):02x}" for p, q in zip(x, y))


def tokens(mode: str, palette: str) -> dict[str, str]:
    t = {**MODE_TOKENS[mode], **PALETTE_TOKENS[(mode, palette)]}
    # States worked out from the colors above, so every theme gets them alike.
    t["line-strong"] = mix(t["line"], t["ink"], .2)
    t["pressed"] = mix(t["surface"], t["ink"], .08)
    t["accent-hover"] = mix(t["accent"], t["ink"], .14)
    t["accent-pressed"] = mix(t["accent"], t["ink"], .26)
    t["bad-hover"] = mix(t["bad"], t["ink"], .14)
    return t


_current = tokens("light", "pine")


def current() -> dict[str, str]:
    """The colors applied last, for widgets that draw themselves."""
    return _current


def qss_color(css: str) -> str:
    """Qt's style sheets take alpha as 0 to 255, where CSS takes 0 to 1."""
    found = re.fullmatch(r"rgba\((\d+), (\d+), (\d+), ([\d.]+)\)", css)
    if found:
        r, g, b, a = found.groups()
        return f"rgba({r}, {g}, {b}, {round(float(a) * 255)})"
    return css


def style_sheet(t: dict[str, str], scale: float = 1.0) -> str:
    """The whole window's style sheet. Widgets say what they are with an object name or a
    'kind' property."""
    c = {name: qss_color(value) for name, value in t.items()}
    text = {name: round(value * scale) for name, value in TEXT.items()}
    return f"""
* {{ font-size: {text['md']}px; }}
QWidget {{ color: {c['ink']}; }}
QMainWindow, #content, #view, #lockScreen {{ background: {c['page']}; }}
QScrollArea, QScrollArea > QWidget > QWidget {{ background: transparent; border: none; }}
QToolTip {{ color: {c['ink']}; background: {c['surface']}; border: 1px solid {c['line']};
    padding: {SPACE[2]}px {SPACE[3]}px; font-size: {text['sm']}px; }}

#side {{ background: {c['nav']}; border-right: 1px solid {c['line']}; }}
#brand {{ font-size: {text['lg']}px; font-weight: 600; color: {c['ink']}; }}
#foot {{ font-size: {text['xs']}px; color: {c['muted']}; }}
QPushButton[kind="nav"] {{
    text-align: left; min-height: 20px; padding: {SPACE[2]}px; border: none; border-radius: {RADIUS['md']}px;
    font-size: {text['md']}px; font-weight: 500; color: {c['ink-2']}; background: transparent; }}
QPushButton[kind="nav"]:hover {{ background: {c['hover']}; color: {c['ink']}; }}
QPushButton[kind="nav"]:checked {{ background: {c['accent-soft']}; color: {c['ink']}; }}
QPushButton[kind="nav"]:focus {{ outline: none; border: 2px solid {c['accent']}; padding: {SPACE[2] - 2}px; }}

#title {{ font-size: {text['2xl']}px; font-weight: 600; }}
QLabel[kind="h1"] {{ font-size: {text['xl']}px; font-weight: 600; }}
#subtitle {{ font-size: {text['sm']}px; color: {c['muted']}; }}

QPushButton {{
    min-height: {CONTROL - 2}px; padding: 0 {SPACE[3]}px; font-size: {text['sm']}px; font-weight: 500;
    color: {c['ink']}; background: {c['surface']}; border: 1px solid {c['line']}; border-radius: {RADIUS['md']}px; }}
QPushButton:hover {{ background: {c['raised']}; border-color: {c['line-strong']}; }}
QPushButton:pressed {{ background: {c['pressed']}; }}
QPushButton:focus {{ border: 2px solid {c['accent']}; padding: 0 {SPACE[3] - 1}px; min-height: {CONTROL - 4}px; }}
QPushButton:disabled {{ color: {c['muted']}; border-color: {c['line-soft']}; }}
QPushButton[kind="primary"] {{ background: {c['accent']}; border-color: {c['accent']}; color: {c['on-accent']}; }}
QPushButton[kind="primary"]:hover {{ background: {c['accent-hover']}; border-color: {c['accent-hover']}; }}
QPushButton[kind="primary"]:pressed {{ background: {c['accent-pressed']}; border-color: {c['accent-pressed']}; }}
QPushButton[kind="danger"] {{ background: {c['bad']}; border-color: {c['bad']}; color: {c['on-bad']}; }}
QPushButton[kind="danger"]:hover {{ background: {c['bad-hover']}; border-color: {c['bad-hover']}; }}
QPushButton[kind="primary"]:focus, QPushButton[kind="danger"]:focus {{ border-color: {c['ink']}; }}

QLineEdit, QComboBox {{
    min-height: {CONTROL - 2}px; padding: 0 {SPACE[3]}px; font-size: {text['sm']}px; color: {c['ink']};
    background: {c['surface']}; border: 1px solid {c['line']}; border-radius: {RADIUS['md']}px; }}
QComboBox {{ padding-right: {CHEVRON + 4}px; }}
QLineEdit:hover, QComboBox:hover {{ border-color: {c['line-strong']}; }}
QLineEdit:focus, QComboBox:focus {{ border: 2px solid {c['accent']}; padding: 0 {SPACE[3] - 1}px;
    min-height: {CONTROL - 4}px; }}
QComboBox:focus {{ padding-right: {CHEVRON + 3}px; }}
QComboBox:disabled, QLineEdit:disabled {{ color: {c['muted']}; background: {c['raised']}; border-color: {c['line-soft']}; }}
QComboBox::drop-down {{ border: none; width: {CHEVRON}px; subcontrol-origin: padding; subcontrol-position: top right; }}
QComboBox::down-arrow {{ image: none; width: 0; height: 0; }}
#popup-list {{ background: transparent; border: none; outline: none; }}

QFrame[kind="card"] {{ background: {c['surface']}; border: 1px solid {c['line-soft']}; border-radius: {RADIUS['lg']}px; }}
QLabel[kind="h2"] {{ font-size: {text['lg']}px; font-weight: 600; }}
QLabel[kind="h3"] {{ font-weight: 600; margin-top: {SPACE[1]}px; }}
QLabel[kind="dim"] {{ font-size: {text['sm']}px; color: {c['muted']}; }}
QLabel[kind="strong"] {{ font-weight: 500; }}
QLabel[kind="empty"] {{ color: {c['muted']}; padding: {SPACE[6]}px 0; }}
QLabel[kind="chip"], QLabel[kind="legend"] {{ color: {c['ink-2']}; font-size: {text['sm']}px; }}
QLabel[kind="legend"] {{ font-size: {text['xs']}px; }}
QLabel[kind="pct"] {{ color: {c['muted']}; font-size: {text['xs']}px; }}
QPushButton[kind="small"] {{ min-height: {CONTROL_SM - 2}px; padding: 0 {SPACE[2]}px; font-size: {text['xs']}px;
    border-radius: {RADIUS['sm']}px; }}
QCheckBox {{ color: {c['ink-2']}; font-size: {text['sm']}px; spacing: {SPACE[2]}px; }}

#filters QComboBox {{ min-width: 150px; }}
QToolButton[kind="picker"] {{
    min-height: {CONTROL - 2}px; padding: 0 {CHEVRON + 4}px 0 {SPACE[3]}px; font-size: {text['sm']}px; color: {c['ink']};
    background: {c['surface']}; border: 1px solid {c['line']}; border-radius: {RADIUS['md']}px; }}
QToolButton[kind="picker"]:hover {{ border-color: {c['line-strong']}; }}
QToolButton[kind="picker"]:focus {{ border: 2px solid {c['accent']}; padding: 0 {CHEVRON + 3}px 0 {SPACE[3] - 1}px;
    min-height: {CONTROL - 4}px; }}
QToolButton[kind="picker"]::menu-indicator {{ image: none; width: 0; height: 0; }}
QMenu {{ background: transparent; color: {c['ink']}; border: none; padding: 0; font-size: {text['sm']}px; }}
QMenu::item {{ padding: {SPACE[2]}px {SPACE[4]}px {SPACE[2]}px {SPACE[2]}px; border-radius: {RADIUS['sm']}px; }}
QMenu::item:selected {{ background: {c['accent-soft']}; color: {c['ink']}; }}
QMenu::indicator {{ width: 16px; height: 16px; padding-left: {SPACE[2]}px; }}
QMenu::separator {{ height: 1px; background: {c['line-soft']}; margin: {SPACE[1]}px {SPACE[2]}px; }}

QFrame[kind="tile"], QFrame[kind="hero"] {{ background: {c['surface']}; border: 1px solid {c['line-soft']};
    border-radius: {RADIUS['lg']}px; }}
QLabel[kind="k"] {{ font-size: {text['sm']}px; font-weight: 500; color: {c['ink-2']}; }}
QLabel[kind="v"] {{ font-size: {text['2xl']}px; font-weight: 600; }}
QLabel[kind="big"] {{ font-size: {text['4xl']}px; font-weight: 600; }}
QLabel[kind="s"] {{ font-size: {text['xs']}px; color: {c['muted']}; }}
QLabel[tone="pos"] {{ color: {c['good']}; }}
QLabel[tone="neg"] {{ color: {c['bad']}; }}
QLabel[kind="flow"] {{ font-size: {text['sm']}px; color: {c['ink-2']}; }}
QLabel[kind="flow-share"] {{ font-size: {text['sm']}px; font-weight: 600; color: {c['ink-2']}; }}

QFrame[kind="banner"] {{ border-radius: {RADIUS['md']}px; }}
QFrame[kind="banner"][level="warn"] {{ background: {c['warn-bg']}; }}
QFrame[kind="banner"][level="info"] {{ background: {c['info-bg']}; }}
QFrame[level="warn"] QLabel, QFrame[level="warn"] QPushButton {{ color: {c['warn-ink']}; }}
QFrame[level="info"] QLabel {{ color: {c['info-ink']}; }}
QLabel[kind="b"] {{ font-size: {text['sm']}px; font-weight: 600; }}
QLabel[kind="banner-text"] {{ font-size: {text['sm']}px; }}
QPushButton[kind="banner-head"] {{ text-align: left; min-height: 0; padding: 0; border: none; background: transparent;
    font-size: {text['sm']}px; font-weight: 600; }}

QFrame[kind="hbar"] {{ border-radius: {RADIUS['md']}px; border: 2px solid transparent; }}
QFrame[kind="hbar"]:hover {{ background: {c['hover']}; }}
QFrame[kind="hbar"]:focus {{ border-color: {c['accent']}; }}

QTableWidget[kind="table"] {{ background: transparent; border: none; font-size: {text['sm']}px; outline: none;
    selection-background-color: {c['accent-soft']}; selection-color: {c['ink']}; }}
QTableWidget[kind="table"]::item {{ padding: 0 {SPACE[2]}px; border-bottom: 1px solid {c['line-soft']}; }}
QTableWidget[clickable="true"]::item:hover {{ background: {c['hover']}; }}
QTableWidget[kind="table"]::item:selected {{ background: {c['accent-soft']}; color: {c['ink']}; }}
QDialog#dialog {{ background: {c['surface']}; }}
QLabel[kind="field"] {{ font-size: {text['xs']}px; font-weight: 500; color: {c['ink-2']}; }}
QLabel[kind="code"] {{ font-size: {text['xs']}px; color: {c['ink-2']}; }}
QLabel[kind="sub"] {{ font-size: {text['sm']}px; color: {c['muted']}; }}
QLabel[kind="error"] {{ font-size: {text['sm']}px; color: {c['bad']}; }}
QLabel[kind="warn"] {{ font-size: {text['sm']}px; color: {c['warn-ink']}; background: {c['warn-bg']};
    border-radius: {RADIUS['sm']}px; padding: {SPACE[1]}px {SPACE[2]}px; }}
QLabel[kind="panel-text"] {{ font-size: {text['sm']}px; color: {c['ink-2']}; }}
QFrame[kind="panel"] {{ background: {c['raised']}; border: 1px solid {c['line-soft']}; border-radius: {RADIUS['md']}px; }}
QRadioButton {{ color: {c['ink']}; spacing: {SPACE[2]}px; }}
QPushButton[kind="small-danger"] {{ min-height: {CONTROL_SM - 2}px; padding: 0 {SPACE[2]}px; font-size: {text['xs']}px;
    border-radius: {RADIUS['sm']}px; color: {c['bad']}; }}
QPushButton[kind="primary"]:disabled, QPushButton[kind="danger"]:disabled {{ color: {c['muted']};
    background: {c['raised']}; border-color: {c['line']}; }}
QPushButton[kind="segment"] {{ padding: 0 {SPACE[3]}px; }}
QPushButton[kind="segment"]:checked {{ background: {c['accent-soft']}; border: 2px solid {c['accent']}; }}
QPushButton[kind="small-primary"] {{ min-height: {CONTROL_SM - 2}px; padding: 0 {SPACE[2]}px; font-size: {text['xs']}px;
    border-radius: {RADIUS['sm']}px; background: {c['accent']}; border-color: {c['accent']}; color: {c['on-accent']}; }}
QPushButton[kind="nav-link"] {{ text-align: left; min-height: 20px; padding: {SPACE[2]}px; border: none;
    border-radius: {RADIUS['md']}px; font-size: {text['sm']}px; color: {c['ink-2']}; background: transparent; }}
QPushButton[kind="nav-link"]:hover {{ background: {c['hover']}; color: {c['ink']}; }}
QFrame#coach {{ background: {c['surface']}; border: 1px solid {c['line']}; border-radius: {RADIUS['lg']}px; }}
QFrame[kind="budget"] {{ border-bottom: 1px solid {c['line-soft']}; }}
#toast {{ background: {c['ink']}; color: {c['page']}; border-radius: {RADIUS['md']}px; padding: {SPACE[2]}px {SPACE[4]}px;
    font-size: {text['sm']}px; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 0; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 0; }}
QScrollBar::handle {{ background: {c['line']}; border-radius: 5px; }}
QScrollBar::handle:vertical {{ min-height: 32px; }}
QScrollBar::handle:horizontal {{ min-width: 32px; }}
QScrollBar::handle:hover {{ background: {c['muted']}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: none; }}
QHeaderView {{ background: transparent; border: none; }}
QHeaderView::section {{ background: transparent; color: {c['muted']}; font-size: {text['xs']}px; font-weight: 500;
    border: none; border-bottom: 1px solid {c['line']}; padding: {SPACE[2]}px; }}
"""


def apply(app, look: Look) -> str:
    """Style the whole application. Returns the mode used, light or dark."""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QColor, QPalette

    system_dark = app.styleHints().colorScheme() == Qt.ColorScheme.Dark
    mode = mode_for(look, system_dark)
    t = tokens(mode, look.palette)
    palette = QPalette()
    for role, name in ((QPalette.Window, "page"), (QPalette.Base, "surface"), (QPalette.AlternateBase, "raised"),
                       (QPalette.Text, "ink"), (QPalette.WindowText, "ink"), (QPalette.ButtonText, "ink"),
                       (QPalette.Button, "surface"), (QPalette.Highlight, "accent"),
                       (QPalette.HighlightedText, "on-accent"), (QPalette.PlaceholderText, "muted"),
                       (QPalette.ToolTipBase, "surface"), (QPalette.ToolTipText, "ink")):
        palette.setColor(role, QColor(t[name]))
    app.setPalette(palette)
    global _current, _scale
    _current, _scale = t, scale_for(look.size)
    sheet = style_sheet(t, _scale)
    if app.styleSheet() != sheet:  # setting it restyles every widget, so only when it changes
        app.setStyleSheet(sheet)
    return mode
