"""Keyboard shortcuts: one list, for the window to set up and the Help tab to show.

Ctrl is Command on a Mac, where Qt swaps them, so these read right on every system.
"""
from __future__ import annotations

from PySide6.QtGui import QKeySequence, QShortcut

NUMBERED = 9  # Ctrl+1 to Ctrl+9 show the first nine tabs, in the sidebar's order

# What a person reads in Help, the keys, and the window's method that does it.
ACTIONS = (
    ("Find a transaction", "Ctrl+F", "find"),
    ("Undo the last change", "Ctrl+Z", "undo"),
    ("Add files", "Ctrl+I", "add_files"),
    ("Sync banks", "Ctrl+R", "sync"),
    ("Appearance", "Ctrl+,", "appearance"),
    ("Help", "F1", "help"),
)


def shown(keys: str) -> str:
    """The keys as this system writes them: Ctrl+F here, ⌘F on a Mac."""
    return QKeySequence(keys).toString(QKeySequence.NativeText)


def tab_keys(tabs: tuple[str, ...]) -> dict[str, str]:
    return {tab: f"Ctrl+{i}" for i, tab in enumerate(tabs[:NUMBERED], 1)}


def install(window, tabs: tuple[str, ...]) -> list[QShortcut]:
    """Shortcuts for the window. A dialog that's open keeps them from firing behind it."""
    made = []
    for tab, keys in tab_keys(tabs).items():
        made.append(QShortcut(QKeySequence(keys), window, lambda tab=tab: window.show_tab(tab)))
    for _, keys, name in ACTIONS:
        made.append(QShortcut(QKeySequence(keys), window, getattr(window, name)))
    return made


def listing(tabs: tuple[str, ...]) -> list[tuple[str, str]]:
    """(what it does, keys as shown) for every shortcut, for Help."""
    numbered = tab_keys(tabs)
    first, last = list(numbered)[0], list(numbered)[-1]
    return [(f"Show a tab: {first} to {last}", f"{shown(numbered[first])} to {shown(numbered[last])}"),
            *((label, shown(keys)) for label, keys, _ in ACTIONS),
            ("Next or previous tab, from the sidebar", "Up and Down")]
