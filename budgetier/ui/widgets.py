"""Small pieces every tab uses."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout

from . import theme


def text(value: str, kind: str = "", wrap: bool = True) -> QLabel:
    """A label that only ever shows text. Qt shows anything that looks like HTML as HTML,
    and bank descriptions are whatever the bank sent, so no label is allowed to guess."""
    label = QLabel()
    label.setTextFormat(Qt.PlainText)
    label.setText(value)
    label.setWordWrap(wrap)
    label.setTextInteractionFlags(Qt.TextSelectableByMouse)
    if kind:
        label.setProperty("kind", kind)
    return label


def card(*children, title: str = "", note: str = "") -> QFrame:
    frame = QFrame()
    frame.setProperty("kind", "card")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(*(theme.SPACE[5],) * 4)
    layout.setSpacing(theme.SPACE[2])
    if title:
        layout.addWidget(text(title, "h2"))
    if note:
        layout.addWidget(text(note, "dim"))
    for child in children:
        layout.addWidget(child)
    return frame
