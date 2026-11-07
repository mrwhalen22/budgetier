"""Appearance: light, dark or the system's, and the Pine, Ocean or Plum theme."""
from __future__ import annotations

from PySide6.QtCore import QSize
from PySide6.QtWidgets import QButtonGroup, QPushButton

from . import icons, theme, widgets
from .dialogs import Dialog

MODES = (("system", "Match system"), ("light", "Light"), ("dark", "Dark"))
SWATCH = '<circle cx="12" cy="12" r="9"/>'


def appearance(window) -> Dialog:
    dialog = Dialog(window, "Appearance", "This computer remembers your choice.")
    modes, palettes = QButtonGroup(dialog), QButtonGroup(dialog)
    mode_buttons, palette_buttons = [], []
    for value, label in MODES:
        button = QPushButton(label)
        button.setProperty("kind", "segment")
        button.setCheckable(True)
        button.setChecked(window.look.mode == value)
        button.clicked.connect(lambda _=False, value=value: window.set_look(theme.Look(value, window.look.palette)))
        modes.addButton(button)
        mode_buttons.append(button)
    for value, label in theme.PALETTES:
        button = QPushButton(label)
        button.setProperty("kind", "segment")
        button.setCheckable(True)
        button.setChecked(window.look.palette == value)
        accent = theme.tokens(window.mode, value)["accent"]
        button.setIcon(icons.pixmap(SWATCH, accent, 14, button.devicePixelRatioF(), filled=True))
        button.setIconSize(QSize(14, 14))
        button.clicked.connect(lambda _=False, value=value: window.set_look(theme.Look(window.look.mode, value)))
        palettes.addButton(button)
        palette_buttons.append(button)
    dialog.body.addWidget(widgets.text("Mode", "field"))
    dialog.body.addWidget(widgets.row(*mode_buttons, spacing=theme.SPACE[1]))
    dialog.body.addWidget(widgets.text("Theme", "field"))
    dialog.body.addWidget(widgets.row(*palette_buttons, spacing=theme.SPACE[1]))
    dialog.set_buttons([("Done", dialog.dismiss, "primary")])
    dialog.mode_buttons, dialog.palette_buttons = mode_buttons, palette_buttons
    dialog.open()
    dialog.main.setFocus()  # a ring on the first choice would read as a second one chosen
    return dialog
