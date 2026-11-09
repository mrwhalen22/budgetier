"""How amounts and dates read on screen. Amounts arrive in cents."""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from ..views import day_name, month_name

__all__ = ["money", "cents", "short", "tone", "gain", "owed", "month_name", "day_name", "plural"]


def _round(value: float, decimals: int) -> Decimal:
    """Halves round up, as people expect, where Python would round them to even."""
    return Decimal(repr(value)).quantize(Decimal(1).scaleb(-decimals), ROUND_HALF_UP)


def money(amount: float, decimals: int = 0) -> str:
    """$1,234, or -$1,234.56 with decimals=2."""
    dollars = _round(abs(amount) / 100, decimals)
    sign = "-" if amount < 0 and dollars else ""
    return f"{sign}${dollars:,.{decimals}f}"


def cents(amount: float) -> str:
    return money(amount, 2)


def short(amount: float) -> str:
    """For chart axes and tight cells: $950, $1.2k, $1.5M."""
    a = abs(amount) / 100
    if a >= 999_950:
        text = f"{_round(a / 1_000_000, 1)}".removesuffix(".0") + "M"
    elif a >= 1000:
        text = f"{_round(a / 1000, 1)}".removesuffix(".0") + "k"
    else:
        text = f"{_round(a, 0)}"
    return ("-$" if amount < 0 else "$") + text


def tone(amount: float) -> str:
    """Red below zero and green above, for amounts where either way matters."""
    return "neg" if amount < 0 else "pos" if amount > 0 else ""


def gain(amount: float) -> str:
    """Green for money in. Ordinary spending isn't a problem, so it isn't red."""
    return "pos" if amount > 0 else ""


def owed(amount: float) -> str:
    """What's owed, under a label that already says so: $613, not -$613. A card in credit
    shows as -$50 owed."""
    return money(-amount)


def plural(count: int, one: str, many: str | None = None) -> str:
    return f"{count:,} {one if count == 1 else many or one + 's'}"
