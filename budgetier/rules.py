"""Reading rules.csv. It's one file a person can edit, read one way everywhere."""
from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from pathlib import Path

from .storage import read_text

TEMPLATE = """\
# Your own categorization rules. They run first and override everything built in,
# and re-apply to your whole history on every run.
# match is a case-insensitive regular expression tested against the bank's description.
# merchant is optional and merges different spellings under one name.
# Use category Transfer for moves between your own accounts (they stop counting as spending).
match,category,merchant
# TRADER JOE,Groceries,Trader Joe's
# VENMO CASHOUT,Transfer,
"""


@dataclass(frozen=True)
class Rule:
    line: str
    pattern: str
    category: str
    merchant: str


def lines(path: Path) -> list[str]:
    return read_text(path).splitlines() if path.exists() else []


def cells(line: str) -> list[str]:
    return next(csv.reader(io.StringIO(line)), [])


def read(path: Path) -> list[Rule]:
    """The rules in the order they apply. Comments, the header and rows with no category
    aren't rules."""
    found = []
    for line in lines(path):
        row = [] if line.lstrip().startswith("#") else cells(line)
        if len(row) < 2 or not row[1].strip() or row[0].strip().lower() == "match":
            continue
        found.append(Rule(line, row[0].strip(), row[1].strip(), row[2].strip() if len(row) > 2 else ""))
    return found
