"""Transactions as a CSV file, for a spreadsheet or another app: whatever the window is showing."""
from __future__ import annotations

import csv
import io
from pathlib import Path

HEADERS = ["Date", "Merchant", "Description", "Category", "Kind", "Amount", "Account", "Note", "Tags"]
# A spreadsheet runs a cell that starts with one of these as a formula, and a bank description
# can say anything, so text like that is kept as text with a leading apostrophe.
_FORMULA = ("=", "+", "-", "@", "\t", "\r")


def _text(value: str) -> str:
    return "'" + value if value.startswith(_FORMULA) else value


def csv_text(txns, account_names: dict[str, str]) -> str:
    """One row per transaction, amounts as plain numbers with money out below zero."""
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\r\n")
    writer.writerow(HEADERS)
    for t in txns:
        writer.writerow([t.date, _text(t.merchant), _text(t.description), _text(t.category), t.kind,
                         f"{t.cents / 100:.2f}", _text(account_names.get(t.account, "")), _text(t.note),
                         _text(", ".join(t.tags))])
    return out.getvalue()


def write_csv(path: Path, txns, account_names: dict[str, str]) -> None:
    # With a byte order mark, so Excel reads accented names correctly.
    Path(path).write_text(csv_text(txns, account_names), encoding="utf-8-sig", newline="")
