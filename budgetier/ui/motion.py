"""Short, quiet motion: popups that fade in, notes that slide up, bars that grow.

Everything here only changes how a thing looks on its way somewhere. What it shows, and
whether it's visible, changes at once, so nothing waits on an animation. "Reduce motion"
under Appearance turns all of it off.
"""
from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QEasingCurve, QObject, QPoint, QPropertyAnimation, QVariantAnimation
from PySide6.QtWidgets import QGraphicsOpacityEffect, QWidget

from . import settings

FAST, NORMAL = 120, 180  # milliseconds
_on = True


def load(home) -> bool:
    """Whether motion is on, from settings.json."""
    set_on(not settings.load(home).get("reduce_motion", False))
    return _on


def set_on(on: bool) -> None:
    global _on
    _on = bool(on)


def on() -> bool:
    return _on


def _keep(owner: QObject, animation: QObject, name: str) -> None:
    """One animation of each kind per widget: a new one replaces the one still running."""
    old = getattr(owner, name, None)
    if old is not None:
        try:
            old.stop()
        except RuntimeError:
            pass
    setattr(owner, name, animation)


def fade_in(window: QWidget, ms: int = FAST) -> None:
    """A top-level window: popups, dialogs, the chart's note."""
    if not _on:
        window.setWindowOpacity(1)
        return
    animation = QPropertyAnimation(window, b"windowOpacity", window)
    animation.setDuration(ms)
    animation.setStartValue(0.0)
    animation.setEndValue(1.0)
    animation.setEasingCurve(QEasingCurve.OutCubic)
    _keep(window, animation, "_fade")
    animation.start()


def slide(widget: QWidget, to: QPoint, ms: int = FAST, start: QPoint | None = None) -> None:
    """Move a widget, gliding when motion is on."""
    if not _on or (start is None and not widget.isVisible()):
        _keep(widget, None, "_slide")
        widget.move(to)
        return
    animation = QPropertyAnimation(widget, b"pos", widget)
    animation.setDuration(ms)
    animation.setStartValue(start if start is not None else widget.pos())
    animation.setEndValue(to)
    animation.setEasingCurve(QEasingCurve.OutCubic)
    _keep(widget, animation, "_slide")
    animation.start()


def reveal(widget: QWidget, ms: int = NORMAL, then: Callable[[], None] | None = None, out: bool = False) -> None:
    """Fade a widget inside the window in, or out and then run `then`. The effect is removed
    afterwards, since drawing through it costs something on every paint."""
    if not _on:
        widget.setGraphicsEffect(None)
        if then:
            then()
        return
    effect = QGraphicsOpacityEffect(widget)
    widget.setGraphicsEffect(effect)
    animation = QPropertyAnimation(effect, b"opacity", widget)
    animation.setDuration(ms)
    animation.setStartValue(1.0 if out else 0.0)
    animation.setEndValue(0.0 if out else 1.0)
    animation.setEasingCurve(QEasingCurve.OutCubic)

    def done():
        try:
            widget.setGraphicsEffect(None)
        except RuntimeError:  # the widget went first
            return
        if then:
            then()
    animation.finished.connect(done)
    _keep(widget, animation, "_reveal")
    animation.start()


def progress(owner: QObject, changed: Callable[[float], None], ms: int = NORMAL * 2,
             start: float = 0.0, end: float = 1.0, name: str = "_progress") -> None:
    """Count from start to end, easing out, calling changed with each value."""
    if not _on:
        _keep(owner, None, name)
        changed(end)
        return
    animation = QVariantAnimation(owner)
    animation.setDuration(ms)
    animation.setStartValue(float(start))
    animation.setEndValue(float(end))
    animation.setEasingCurve(QEasingCurve.OutCubic)
    animation.valueChanged.connect(lambda v: changed(float(v)))
    _keep(owner, animation, name)
    changed(start)
    animation.start()
