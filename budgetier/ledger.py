"""The durable store: every transaction ever imported, per account, in plain CSV.

Everything else (dashboard, workbook, categories) is regenerated from these
files, so changing a rule applies to the whole history.
"""
from __future__ import annotations

import copy
import csv
import io
import json
import re
import shutil
from collections import Counter
from datetime import date, datetime
from pathlib import Path

from .parse import RawRow
from .storage import DataError, read_text, write_files

FIELDS = ["date", "account", "description", "amount", "balance", "bank_category", "source"]
IMPORT_FIELDS = ["imported_at", "file", "account", "first", "last", "rows", "added", "duplicates", "stored",
                 "file_account"]


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


def _csv_text(fields: list[str], rows: list[dict]) -> str:
    out = io.StringIO(newline="")
    writer = csv.DictWriter(out, fieldnames=fields)
    writer.writeheader()
    writer.writerows(rows)
    return out.getvalue()


def _damaged(path: Path, error: Exception) -> DataError:
    backup = path.with_name(path.name + ".bak")
    remedy = (f"A copy from before your last change is beside it, named {backup.name}. Replace the damaged "
              "file with that copy, then open Budgetier again." if backup.exists()
              else "If you edited it, undo that change and open Budgetier again.")
    return DataError(f"{path.name} in {path.parent} can't be read, so your data can't be opened ({error}). {remedy}")


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
        self.accounts = self._load_accounts()
        self._recover_accounts()

    def _load_rows(self) -> list[dict]:
        if not self.path.exists():
            return []
        try:
            return [{**r, "date": date.fromisoformat(r["date"]),
                     "cents": _cents(r["amount"]), "balance": _cents(r["balance"])}
                    for r in csv.DictReader(io.StringIO(read_text(self.path), newline=""))]
        except (ValueError, KeyError, TypeError, AttributeError, csv.Error) as e:
            raise _damaged(self.path, e) from e

    def _load_imports(self) -> list[dict]:
        if not self.imports_path.exists():
            return []
        try:
            return list(csv.DictReader(io.StringIO(read_text(self.imports_path), newline="")))
        except csv.Error as e:
            raise _damaged(self.imports_path, e) from e

    def _load_accounts(self) -> dict[str, dict]:
        if not self.accounts_path.exists():
            return {}
        try:
            accounts = json.loads(read_text(self.accounts_path))
            if not all(isinstance(info, dict) for info in accounts.values()):
                raise ValueError("an account isn't in the expected form")
        except (ValueError, AttributeError) as e:
            raise _damaged(self.accounts_path, e) from e
        return accounts

    def _recover_accounts(self) -> None:
        """Rows without an account would stop every report. The rows are what matter, so
        keep them under a stand-in the person can rename; a check points it out."""
        used = {r["account"] for r in self.rows} | {i["account"] for i in self.imports}
        for account in sorted(used - set(self.accounts)):
            number = account.rsplit("-", 1)[-1]
            self.accounts[account] = {"name": f"Recovered account {number}", "bank": "Unknown", "number": number,
                                      "type": "checking", "invert_sign": False, "recovered": True}

    def snapshot(self) -> tuple:
        return list(self.rows), copy.deepcopy(self.imports), copy.deepcopy(self.accounts)

    def restore(self, snapshot: tuple) -> None:
        self.rows, self.imports, self.accounts = snapshot

    def _new_rows(self, account_id: str, incoming: list[RawRow]) -> list[RawRow]:
        """Identical rows are legitimate (two $5 coffees in a day), so this compares
        counts: if a file shows a row three times and the ledger has it twice, one is
        new. That keeps overlapping exports from doubling up and keeps real repeats, and
        importing the same file again adds nothing."""
        have = Counter(_key(r["date"], r["cents"], r["description"])
                       for r in self.rows if r["account"] == account_id)
        seen: Counter = Counter()
        new = []
        for raw in incoming:
            key = _key(raw.date, raw.cents, raw.description)
            seen[key] += 1
            if seen[key] > have[key]:
                new.append(raw)
        return new

    def count_new(self, account_id: str, incoming: list[RawRow]) -> int:
        """How many of these rows merge() would add. Changes nothing."""
        return len(self._new_rows(account_id, incoming))

    def merge(self, account_id: str, incoming: list[RawRow], source: str) -> dict:
        """Add what's new for one account."""
        new = self._new_rows(account_id, incoming)
        self.rows += [{
            "date": raw.date, "account": account_id, "description": raw.description,
            "amount": _money(raw.cents), "cents": raw.cents, "balance": raw.balance,
            "bank_category": raw.bank_category, "source": source,
        } for raw in new]
        added = len(new)
        self.imports.append({
            "imported_at": datetime.now().isoformat(timespec="seconds"), "file": source,
            "account": account_id, "first": min(r.date for r in incoming).isoformat(),
            "last": max(r.date for r in incoming).isoformat(), "rows": len(incoming),
            "added": added, "duplicates": len(incoming) - added,
        })
        return self.imports[-1]

    def _accounts_text(self) -> str:
        return json.dumps(self.accounts, indent=2) + "\n"

    def save(self) -> None:
        """Rows, imports and accounts refer to each other, so they're saved together."""
        self.rows.sort(key=lambda r: (r["date"], r["account"]))  # stable: keeps same-day order
        files = {
            self.path: _csv_text(FIELDS, [{**{k: r[k] for k in FIELDS}, "date": r["date"].isoformat(),
                                           "balance": _money(r["balance"])} for r in self.rows]),
            self.imports_path: _csv_text(IMPORT_FIELDS, self.imports),
            self.accounts_path: self._accounts_text(),
        }
        for path in files:
            if path.exists():
                shutil.copy2(path, path.with_name(path.name + ".bak"))
        write_files(files)

    def save_accounts(self) -> None:
        write_files({self.accounts_path: self._accounts_text()})
