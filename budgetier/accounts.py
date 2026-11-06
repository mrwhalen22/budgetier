"""What the desktop app and the command line agree on about an account."""
from __future__ import annotations

import re
from datetime import date

from .parse import ParsedFile, RawRow

TYPES = ("checking", "savings", "credit")
LABELS = {"credit": "Card", "savings": "Savings", "checking": "Checking"}


def account_id(bank: str, number: str) -> str:
    return f"{re.sub(r'[^a-z0-9]+', '-', bank.lower()).strip('-')}-{number}"


def account_name(bank: str, kind: str, number: str) -> str:
    return f"{bank} {LABELS[kind]} {number}"


def purchases_look_positive(parsed: ParsedFile, rows: list[RawRow]) -> bool:
    """Spending is most of any account, so mostly-positive amounts mean a card that
    reports purchases as positive. A savings account can honestly be nearly all
    deposits, so it doesn't get this test."""
    if parsed.sign_known or parsed.account_type == "savings" or len(rows) < 5:
        return False
    return sum(1 for r in rows if r.cents > 0) / len(rows) > 0.7


def sample_row(rows: list[RawRow]) -> RawRow:
    """A typical row, for asking which way a file's signs run."""
    positive = [r for r in rows if r.cents > 0]
    negative = [r for r in rows if r.cents < 0]
    return (positive if len(positive) >= len(negative) else negative)[0]


def pin_balance(info: dict, cents: int, day: date) -> None:
    info["balance_anchor"] = {"date": day.isoformat(), "amount": cents / 100}
    info.pop("balance_skipped", None)
