"""The durable store: every transaction ever imported, per account, in plain CSV.

Everything else (dashboard, workbook, categories) is regenerated from these
files, so changing a rule applies to the whole history.
"""
from __future__ import annotations

import csv
import json
import os
import re
import shutil
from collections import Counter
from datetime import date, datetime
from pathlib import Path

from .parse import RawRow

FIELDS = ["date", "account", "description", "amount", "balance", "bank_category", "source"]
IMPORT_FIELDS = ["imported_at", "file", "account", "first", "last", "rows", "added", "duplicates", "stored"]


def _money(cents: int | None) -> str:
    if cents is None:
        return ""
    sign = "-" if cents < 0 else ""
    return f"{sign}{abs(cents) // 100}.{abs(cents) % 100:02d}"


def _cents(text: str) -> int | None:
    if text == "":
        return None
    sign = -1 if text.startswith("-") else 1
    whole, _, frac = text.lstrip("-").partition(".")
    return sign * (int(whole) * 100 + int((frac + "00")[:2]))


def _key(day: date, cents: int, description: str) -> tuple:
    return day, cents, re.sub(r"\s+", " ", description).strip().upper()


def _write_csv(path: Path, fields: list[str], rows: list[dict]) -> None:
    tmp = path.with_suffix(".tmp")
    with tmp.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    os.replace(tmp, path)


class Ledger:
    def __init__(self, home: Path):
        self.home = home
        self.data_dir = home / "data"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.path = self.data_dir / "ledger.csv"
        self.imports_path = self.data_dir / "imports.csv"
        self.accounts_path = home / "accounts.json"
        self.rows = self._load_rows()
        self.imports = self._load_imports()
        self.accounts: dict[str, dict] = (
            json.loads(self.accounts_path.read_text(encoding="utf-8"))
            if self.accounts_path.exists() else {})

    def _load_rows(self) -> list[dict]:
        if not self.path.exists():
            return []
        with self.path.open(newline="", encoding="utf-8") as f:
            return [{**r, "date": date.fromisoformat(r["date"]),
                     "cents": _cents(r["amount"]), "balance": _cents(r["balance"])}
                    for r in csv.DictReader(f)]

    def _load_imports(self) -> list[dict]:
        if not self.imports_path.exists():
            return []
        with self.imports_path.open(newline="", encoding="utf-8") as f:
            return list(csv.DictReader(f))

    def count_new(self, account_id: str, incoming: list[RawRow]) -> int:
        """How many of these rows merge() would add. Changes nothing."""
        have = Counter(_key(r["date"], r["cents"], r["description"])
                       for r in self.rows if r["account"] == account_id)
        seen: Counter = Counter()
        new = 0
        for raw in incoming:
            key = _key(raw.date, raw.cents, raw.description)
            seen[key] += 1
            new += seen[key] > have[key]
        return new

    def merge(self, account_id: str, incoming: list[RawRow], source: str) -> dict:
        """Add what's new for one account.

        Identical rows are legitimate (two $5 coffees in a day), so this compares
        counts: if a file shows a row three times and the ledger has it twice, one
        is added. That keeps overlapping exports from doubling up and keeps real
        repeats, and importing the same file again changes nothing.
        """
        have = Counter(_key(r["date"], r["cents"], r["description"])
                       for r in self.rows if r["account"] == account_id)
        seen: Counter = Counter()
        added = 0
        for raw in incoming:
            key = _key(raw.date, raw.cents, raw.description)
            seen[key] += 1
            if seen[key] > have[key]:
                self.rows.append({
                    "date": raw.date, "account": account_id, "description": raw.description,
                    "amount": _money(raw.cents), "cents": raw.cents, "balance": raw.balance,
                    "bank_category": raw.bank_category, "source": source,
                })
                added += 1
        self.imports.append({
            "imported_at": datetime.now().isoformat(timespec="seconds"), "file": source,
            "account": account_id, "first": min(r.date for r in incoming).isoformat(),
            "last": max(r.date for r in incoming).isoformat(), "rows": len(incoming),
            "added": added, "duplicates": len(incoming) - added,
        })
        return self.imports[-1]

    def save(self) -> None:
        if self.path.exists():
            shutil.copy2(self.path, self.path.with_suffix(".csv.bak"))
        self.rows.sort(key=lambda r: (r["date"], r["account"]))  # stable: keeps same-day order
        _write_csv(self.path, FIELDS, [
            {**{k: r[k] for k in FIELDS}, "date": r["date"].isoformat(),
             "balance": _money(r["balance"])} for r in self.rows])
        _write_csv(self.imports_path, IMPORT_FIELDS, self.imports)
        self.save_accounts()

    def save_accounts(self) -> None:
        self.accounts_path.write_text(json.dumps(self.accounts, indent=2) + "\n", encoding="utf-8")
