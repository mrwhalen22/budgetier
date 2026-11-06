"""What the desktop app does to your data: review, import, remove, regenerate.

Imports happen in two steps so a person can correct what was guessed: inspect() reads
files without changing anything, commit() applies the reviewed answers. Each imported
file is kept, because removing one means rebuilding its account from the others: rows
that two overlapping exports share must survive when either export is removed.
"""
from __future__ import annotations

import csv
import dataclasses
import io
import json
import os
import re
import shutil
import sys
import tempfile
from datetime import date, datetime
from pathlib import Path

from . import analyze, pdf2csv, report_html, report_xlsx
from .cli import RULES_TEMPLATE, _purchases_look_positive, _slug
from .ledger import Ledger
from .parse import ParsedFile, ParseError, parse_file, parse_money

TYPES = ("checking", "savings", "credit")
LABELS = {"credit": "Card", "savings": "Savings", "checking": "Checking"}


class BudgetError(Exception):
    """A problem to show the person, in words they can act on."""


def app_home() -> Path:
    """User data lives here, not beside the program: ordinary programs can't write to
    Program Files, and an update must never touch your history."""
    override = os.environ.get("BUDGETIER_HOME")
    if override:
        return Path(override)
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Budgetier"
    return Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "Budgetier"


def app_version() -> str:
    folder = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
    try:
        return (folder / "VERSION").read_text(encoding="utf-8-sig").strip()
    except OSError:
        return ""


def literal(pattern: str) -> str | None:
    """A saved rule as plain text, or None if it uses real pattern syntax."""
    if re.fullmatch(r"(?:[^\\.^$*+?()\[\]{}|]|\\[^A-Za-z0-9])*", pattern):
        return re.sub(r"\\(.)", r"\1", pattern)
    return None


class Budget:
    def __init__(self, home: Path):
        self.home = Path(home)
        self.imported = self.home / "imported"
        self.output = self.home / "output"
        self.html_path = self.output / "budget.html"
        self.rules_path = self.home / "rules.csv"
        self.budgets_path = self.home / "budgets.json"
        for folder in (self.home, self.imported, self.output):
            folder.mkdir(parents=True, exist_ok=True)
        if not self.rules_path.exists():
            self.rules_path.write_text(RULES_TEMPLATE, encoding="utf-8")
        self.ledger = Ledger(self.home)
        self._pending: dict[str, dict] = {}
        self._temp = None

    # ---- reports

    def _analysis(self):
        rows = analyze.classify(self.ledger.rows, self.ledger.accounts, analyze.load_rules(self.rules_path))
        return rows, analyze.find_recurring(rows), analyze.checks(rows, self.ledger.accounts, self.ledger.imports)

    def refresh(self) -> Path:
        rows, recurring, checks = self._analysis()
        report_html.write(self.html_path, rows, self.ledger.accounts, recurring, checks, self.ledger.imports,
                          {"rules": self.rules(), "version": app_version(),
                           "budgets": analyze.budget_report(rows, self.ledger.accounts, self.budgets()),
                           "allCategories": sorted({*analyze.category_names(), *(r["category"] for r in self.rules()),
                                                    "Transfer", analyze.SAVED})})
        return self.html_path

    def export_workbook(self, path: Path) -> None:
        if not self.ledger.rows:
            raise BudgetError("There's nothing to export yet.")
        rows, recurring, checks = self._analysis()
        try:
            report_xlsx.write(Path(path), rows, self.ledger.accounts, recurring, checks)
        except PermissionError as e:
            raise BudgetError("That file is open in another program. Close it and try again.") from e

    # ---- importing

    def inspect(self, paths: list[str]) -> dict:
        """Read files and report what would happen. Nothing is saved."""
        self.cancel()
        self._temp = tempfile.TemporaryDirectory(prefix="budgetier-")
        items, errors = [], []
        for text in paths:
            path = Path(text)
            try:
                items += self._inspect_file(path)
            except (ParseError, pdf2csv.ConvertError, OSError) as e:
                errors.append({"file": path.name, "error": str(e)})
        return {"items": items, "errors": errors}

    def _inspect_file(self, path: Path) -> list[dict]:
        original, csv_path, notes = path, path, []
        if path.suffix.lower() == ".pdf":
            statement = pdf2csv.read_pdf(path)
            csv_path = pdf2csv.write_csv(statement, Path(self._temp.name))
            notes = statement.warnings
        elif path.suffix.lower() != ".csv":
            raise ParseError("only CSV and PDF files can be imported")
        parsed = parse_file(csv_path)
        notes = notes + parsed.warnings
        groups: dict[str, list] = {}
        for row in parsed.rows:  # one file can hold several cards
            groups.setdefault(row.account or (parsed.account or ""), []).append(row)
        return [self._proposal(original, csv_path, parsed, number, rows, notes)
                for number, rows in groups.items()]

    def _account_id(self, bank: str, number: str) -> str:
        return f"{_slug(bank)}-{number}"

    def _proposal(self, original, csv_path, parsed: ParsedFile, number, rows, notes) -> dict:
        token = f"{len(self._pending)}"
        self._pending[token] = {"original": original, "csv": csv_path, "parsed": parsed, "rows": rows}
        bank = parsed.bank or ""
        account_id = self._account_id(bank, number) if bank and number else ""
        info = self.ledger.accounts.get(account_id)
        guessed = _purchases_look_positive(parsed, rows)
        positive = [r for r in rows if r.cents > 0]
        negative = [r for r in rows if r.cents < 0]
        sample = (positive if len(positive) >= len(negative) else negative)[0]
        invert = info["invert_sign"] if info else (parsed.invert or guessed)
        new = len(rows)
        if info:
            new = self.ledger.count_new(account_id, self._signed(rows, invert))
        return {
            "id": token, "file": original.name, "bank": bank, "number": number,
            "type": info["type"] if info else ("credit" if guessed else parsed.account_type),
            "known": bool(info), "accountName": info["name"] if info else "",
            "askSign": not info and not parsed.sign_known,
            "spent": (sample.cents > 0) == invert,
            "sample": {"description": sample.description, "date": sample.date.isoformat(),
                       "amount": sample.cents / 100},
            "count": len(rows), "new": new, "first": min(r.date for r in rows).isoformat(),
            "last": max(r.date for r in rows).isoformat(), "notes": notes,
            "hasBalance": any(r.balance is not None for r in rows),
        }

    @staticmethod
    def _signed(rows, invert: bool) -> list:
        return [dataclasses.replace(r, cents=-r.cents) for r in rows] if invert else list(rows)

    def _unique_store_name(self, name: str) -> Path:
        target = self.imported / name
        if target.exists():
            stem, suffix = Path(name).stem, Path(name).suffix
            target = self.imported / f"{stem}.{datetime.now():%Y%m%d-%H%M%S-%f}{suffix}"
        return target

    def _keep_copy(self, pending: dict) -> str:
        """Keep the file we can re-read later, plus an original PDF for your records."""
        if "stored" in pending:
            return pending["stored"]
        csv_path, original = Path(pending["csv"]), Path(pending["original"])
        target = self._unique_store_name(csv_path.name)
        shutil.copy2(csv_path, target)
        if original != csv_path:
            shutil.copy2(original, self._unique_store_name(original.name))
        pending["stored"] = target.name
        return target.name

    def _validated(self, answer: dict) -> dict:
        bank = (answer.get("bank") or "").strip()
        number = re.sub(r"\D", "", answer.get("number") or "")[-4:]
        kind = answer.get("type")
        name = answer.get("file", "this file")
        if not bank:
            raise BudgetError(f"Enter the bank for {name}.")
        if len(number) != 4:
            raise BudgetError(f"Enter the last 4 digits of the account for {name}.")
        if kind not in TYPES:
            raise BudgetError(f"Choose checking, savings or credit card for {name}.")
        balance = (answer.get("balance") or "").strip()
        cents = parse_money(balance) if balance else None
        if balance and cents is None:
            raise BudgetError(f"The balance for {bank} {number} doesn't look like an amount.")
        return {"bank": bank, "number": number, "type": kind, "balance": cents, "spent": answer.get("spent")}

    def commit(self, answers: list[dict]) -> list[dict]:
        """Apply reviewed answers. Bad answers stop everything before anything changes."""
        reviewed = []
        for answer in answers:
            pending = self._pending.get(str(answer.get("id")))
            if pending is None:
                raise BudgetError("That review has expired. Choose the files again.")
            reviewed.append((pending, self._validated({**answer, "file": pending["original"].name})))

        results = []
        for pending, answer in reviewed:
            rows = pending["rows"]
            account_id = self._account_id(answer["bank"], answer["number"])
            info = self.ledger.accounts.get(account_id)
            if info is None:
                info = self._new_account(account_id, answer, pending)
            if answer["balance"] is not None:
                self._pin(info, answer["balance"], date.today())
            before = len(self.ledger.rows)
            result = self.ledger.merge(account_id, self._signed(rows, info["invert_sign"]), pending["original"].name)
            added = len(self.ledger.rows) - before
            if added:
                result["stored"] = self._keep_copy(pending)
            else:
                self.ledger.imports.pop()  # nothing new, so nothing to list or remove later
            results.append({"account": info["name"], "added": added, "duplicates": len(rows) - added})
        self.ledger.save()
        self.refresh()
        self.cancel()
        return results

    def _new_account(self, account_id: str, answer: dict, pending: dict) -> dict:
        parsed, rows = pending["parsed"], pending["rows"]
        spent = answer["spent"]
        if parsed.sign_known or spent is None:
            invert = parsed.invert or (_purchases_look_positive(parsed, rows) and spent is None)
        else:
            positive = [r for r in rows if r.cents > 0]
            negative = [r for r in rows if r.cents < 0]
            sample = (positive if len(positive) >= len(negative) else negative)[0]
            invert = bool(spent) == (sample.cents > 0)
        info = {"name": f"{answer['bank']} {LABELS[answer['type']]} {answer['number']}",
                "bank": answer["bank"], "number": answer["number"], "type": answer["type"],
                "invert_sign": invert}
        self.ledger.accounts[account_id] = info
        return info

    def cancel(self) -> None:
        self._pending = {}
        if self._temp:
            self._temp.cleanup()
            self._temp = None

    # ---- removing

    @staticmethod
    def _key(entry: dict) -> str:
        return entry.get("stored") or entry["file"]

    def _rebuild(self, account: str, keep: list[dict]) -> None:
        """Replay an account from its remaining files, so overlaps stay correct."""
        info = self.ledger.accounts[account]
        self.ledger.rows = [r for r in self.ledger.rows if r["account"] != account]
        self.ledger.imports = [i for i in self.ledger.imports if i["account"] != account]
        for entry in keep:
            path = self.imported / self._key(entry)
            if not path.exists():
                raise BudgetError(f"The saved copy of {entry['file']} is missing, so this can't be "
                                  "undone safely. Nothing was changed.")
            rows = [r for r in parse_file(path).rows if (r.account or info["number"]) == info["number"]]
            result = self.ledger.merge(account, self._signed(rows, info["invert_sign"]), entry["file"])
            result.update(imported_at=entry["imported_at"], stored=entry.get("stored", ""))

    def _remove_stored(self, keys: set[str]) -> None:
        still_used = {self._key(i) for i in self.ledger.imports}
        for key in keys - still_used:
            (self.imported / key).unlink(missing_ok=True)

    def _transaction(self, change) -> dict:
        """Run a removal against a snapshot, so any failure leaves your data untouched."""
        rows, imports = list(self.ledger.rows), list(self.ledger.imports)
        before = len(rows)
        try:
            change()
        except (BudgetError, ParseError, OSError):
            self.ledger.rows, self.ledger.imports = rows, imports
            raise
        self.ledger.save()
        self.refresh()
        return {"removed": before - len(self.ledger.rows)}

    def remove_import(self, key: str) -> dict:
        entries = [i for i in self.ledger.imports if self._key(i) == key]
        if not entries:
            raise BudgetError("That import is already gone.")

        def change():
            for account in {e["account"] for e in entries}:
                keep = [i for i in self.ledger.imports if i["account"] == account and self._key(i) != key]
                self._rebuild(account, keep)
                if not keep:
                    del self.ledger.accounts[account]

        result = self._transaction(change)
        self._remove_stored({key})
        return result

    def remove_account(self, account: str) -> dict:
        if account not in self.ledger.accounts:
            raise BudgetError("That account is already gone.")
        keys = {self._key(i) for i in self.ledger.imports if i["account"] == account}

        def change():
            self.ledger.rows = [r for r in self.ledger.rows if r["account"] != account]
            self.ledger.imports = [i for i in self.ledger.imports if i["account"] != account]
            del self.ledger.accounts[account]

        result = self._transaction(change)
        self._remove_stored(keys)
        return result

    # ---- rules

    def _rule_lines(self) -> list[str]:
        return self.rules_path.read_text(encoding="utf-8").splitlines()

    def _matching(self, pattern: str) -> list[dict]:
        compiled = re.compile(pattern, re.I)
        return [r for r in self.ledger.rows if compiled.search(r["description"].upper())]

    def rules(self) -> list[dict]:
        """Rules in the order they apply, newest first, each with what it matches."""
        found = []
        for line in self._rule_lines():
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            row = next(csv.reader(io.StringIO(line)), [])
            if len(row) < 2 or row[0].strip().lower() == "match":
                continue
            pattern = row[0].strip()
            text = literal(pattern)
            try:
                hits = self._matching(pattern)
            except re.error:
                found.append({"line": line, "text": pattern, "advanced": True, "broken": True, "category": row[1].strip(),
                              "merchant": row[2].strip() if len(row) > 2 else "", "count": 0, "total": 0})
                continue
            found.append({"line": line, "text": pattern if text is None else text, "advanced": text is None,
                          "broken": False, "category": row[1].strip(),
                          "merchant": row[2].strip() if len(row) > 2 else "", "count": len(hits),
                          "total": sum(r["cents"] for r in hits) / 100})
        return found

    @staticmethod
    def _pattern(text: str, advanced: bool) -> str:
        text = text.strip()
        if len(text) < 3:
            raise BudgetError("Enter at least 3 letters to match.")
        if advanced:
            try:
                re.compile(text)
            except re.error as e:
                raise BudgetError(f"That pattern isn't valid: {e}.") from e
            return text
        return re.escape(text.upper()).replace("\\ ", " ")

    def preview_rule(self, text: str, advanced: bool = False) -> dict:
        hits = self._matching(self._pattern(text, advanced))
        examples = list(dict.fromkeys(r["description"] for r in hits))[:3]
        return {"count": len(hits), "total": sum(r["cents"] for r in hits) / 100,
                "share": len(hits) / len(self.ledger.rows) if self.ledger.rows else 0, "examples": examples}

    def _write_rule_lines(self, lines: list[str]) -> None:
        tmp = self.rules_path.with_suffix(".tmp")
        tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
        os.replace(tmp, self.rules_path)
        self.refresh()

    def save_rule(self, original: str | None, text: str, category: str, merchant: str, advanced: bool = False) -> None:
        """New rules go first: the first match wins, and a new one is usually the more specific."""
        if not category.strip():
            raise BudgetError("Choose a category.")
        pattern = self._pattern(text, advanced)
        out = io.StringIO()
        csv.writer(out, lineterminator="").writerow([pattern, category.strip(), merchant.strip()])
        line = out.getvalue()
        lines = self._rule_lines()
        if original and original in lines:
            lines[lines.index(original)] = line
        else:
            lines = [existing for existing in lines
                     if next(csv.reader(io.StringIO(existing)), [""])[0].strip() != pattern]
            at = next((i + 1 for i, existing in enumerate(lines) if existing.strip().lower().startswith("match,")), None)
            if at is None:
                lines.append("match,category,merchant")
                at = len(lines)
            lines.insert(at, line)
        self._write_rule_lines(lines)

    def delete_rule(self, line: str) -> None:
        lines = self._rule_lines()
        if line not in lines:
            raise BudgetError("That rule is already gone.")
        lines.remove(line)
        self._write_rule_lines(lines)

    # ---- budgets

    def budgets(self) -> dict[str, dict]:
        """Category to target: an amount in cents, or a percent of income."""
        if not self.budgets_path.exists():
            return {}
        return json.loads(self.budgets_path.read_text(encoding="utf-8"))

    def _write_budgets(self, budgets: dict[str, dict]) -> None:
        tmp = self.budgets_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(budgets, indent=2, sort_keys=True), encoding="utf-8")
        os.replace(tmp, self.budgets_path)
        self.refresh()

    def save_budget(self, category: str, mode: str, value: str) -> None:
        category = category.strip()
        if not category:
            raise BudgetError("Choose a category.")
        if category in analyze.NOT_BUDGETED:
            raise BudgetError(f"{category} isn't spending, so it can't have a budget.")
        if mode == "amount":
            target = parse_money(value)
            if target is None or target <= 0:
                raise BudgetError("Enter a dollar amount above zero.")
        elif mode == "percent":
            try:
                target = float(value.strip().rstrip("%"))
            except ValueError as e:
                raise BudgetError("Enter a percentage, like 10.") from e
            if not 0 < target <= 100:
                raise BudgetError("Enter a percentage above 0, up to 100.")
        else:
            raise BudgetError("Choose a dollar amount or a percent of income.")
        self._write_budgets({**self.budgets(), category: {"mode": mode, "value": target}})

    def delete_budget(self, category: str) -> None:
        budgets = self.budgets()
        if category not in budgets:
            raise BudgetError("That budget is already gone.")
        del budgets[category]
        self._write_budgets(budgets)

    # ---- account details

    @staticmethod
    def _pin(info: dict, cents: int, day: date) -> None:
        info["balance_anchor"] = {"date": day.isoformat(), "amount": cents / 100}
        info.pop("balance_skipped", None)

    def update_account(self, account: str, name: str, kind: str, balance: str, as_of: str) -> None:
        info = self.ledger.accounts.get(account)
        if info is None:
            raise BudgetError("That account is gone.")
        if not name.strip():
            raise BudgetError("Give the account a name.")
        if kind not in TYPES:
            raise BudgetError("Choose checking, savings or credit card.")
        info.update(name=name.strip(), type=kind)
        if balance.strip():
            cents = parse_money(balance)
            if cents is None:
                raise BudgetError("That balance doesn't look like an amount.")
            try:
                day = date.fromisoformat(as_of) if as_of else date.today()
            except ValueError as e:
                raise BudgetError("That date doesn't look right.") from e
            self._pin(info, cents, day)
        self.ledger.save_accounts()
        self.refresh()
