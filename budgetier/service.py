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
import logging
import re
import shutil
import sys
import tempfile
from datetime import date
from pathlib import Path

from . import analyze, pdf2csv, report_xlsx, rules
from .accounts import TYPES, account_id, account_name, pin_balance, purchases_look_positive, sample_row
from .ledger import Ledger
from .parse import ParsedFile, ParseError, parse_file, parse_money
from .storage import BudgetError, app_home, read_text, unique_path, write_files
from .sync import BankSync
from .updates import Updater

__all__ = ["Budget", "BudgetError", "app_home", "app_version"]

log = logging.getLogger("budgetier")


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


def _valid_target(target) -> bool:
    return (isinstance(target, dict) and target.get("mode") in ("amount", "percent")
            and type(target.get("value")) in (int, float) and target["value"] > 0)


class Budget:
    def __init__(self, home: Path):
        self.home = Path(home)
        self.imported = self.home / "imported"
        self.output = self.home / "output"
        self.rules_path = self.home / "rules.csv"
        self.budgets_path = self.home / "budgets.json"
        self.edits_path = self.home / analyze.EDITS_FILE
        self.updates = Updater(self.home, app_version())
        for folder in (self.home, self.imported, self.output):
            folder.mkdir(parents=True, exist_ok=True)
        if not self.rules_path.exists():
            self.rules_path.write_text(rules.TEMPLATE, encoding="utf-8")
        self.ledger = Ledger(self.home)
        self.notices: list[dict] = []  # problems found while loading, shown with the checks
        self._pending: dict[str, dict] = {}
        self._temp = None
        self._undo: dict[Path, tuple[bytes | None, bytes | None]] | None = None  # file: (before, after)
        self.sync = BankSync(self)

    # ---- reports

    def analysis(self):
        """Every transaction with its category and kind, the recurring payments, and the checks."""
        edits = self.edits()  # first: a damaged file adds a notice to the checks
        rows = analyze.classify(self.ledger.rows, self.ledger.accounts, analyze.load_rules(self.rules_path), edits)
        checks = analyze.checks(rows, self.ledger.accounts, self.ledger.imports)
        return rows, analyze.find_recurring(rows), self.notices + checks

    def export_workbook(self, path: Path) -> None:
        if not self.ledger.rows:
            raise BudgetError("There's nothing to export yet.")
        rows, recurring, checks = self.analysis()
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
            except Exception:  # one odd file mustn't stop the others
                log.exception("couldn't read an imported file")
                errors.append({"file": path.name, "error": "this file couldn't be read"})
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

    def _proposal(self, original, csv_path, parsed: ParsedFile, number, rows, notes) -> dict:
        token = f"{len(self._pending)}"
        self._pending[token] = {"original": original, "csv": csv_path, "parsed": parsed, "rows": rows,
                                "number": number}
        bank = parsed.bank or ""
        account = account_id(bank, number) if bank and number else ""
        info = self.ledger.accounts.get(account)
        guessed = purchases_look_positive(parsed, rows)
        sample = sample_row(rows)
        invert = info["invert_sign"] if info else (parsed.invert or guessed)
        new = len(rows)
        if info:
            new = self.ledger.count_new(account, self._signed(rows, invert))
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

    def _keep_copy(self, pending: dict, copies: list[Path]) -> str:
        """Keep the file we can re-read later, plus an original PDF for your records."""
        csv_path, original = Path(pending["csv"]), Path(pending["original"])
        target = unique_path(self.imported, csv_path.name)
        try:
            for source, kept in ((csv_path, target), (original, unique_path(self.imported, original.name))):
                if source != csv_path or kept == target:
                    copies.append(kept)
                    shutil.copy2(source, kept)
        except OSError as e:
            raise BudgetError(f"{original.name} couldn't be read. If it was moved, choose it again.") from e
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
            raise BudgetError(f"Choose the kind of account {name} is.")
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

        results, copies = [], []

        def change():
            for pending, answer in reviewed:
                rows = pending["rows"]
                account = account_id(answer["bank"], answer["number"])
                info = self.ledger.accounts.get(account)
                if info is None:
                    info = self._new_account(account, answer, pending)
                if answer["balance"] is not None:
                    pin_balance(info, answer["balance"], date.today())
                before = len(self.ledger.rows)
                result = self.ledger.merge(account, self._signed(rows, info["invert_sign"]), pending["original"].name)
                added = len(self.ledger.rows) - before
                if added:
                    # The number as the file has it: review may have corrected it.
                    result.update(stored=self._keep_copy(pending, copies), file_account=pending["number"])
                else:
                    self.ledger.imports.pop()  # nothing new, so nothing to list or remove later
                results.append({"account": info["name"], "added": added, "duplicates": len(rows) - added})

        def discard_copies():
            for path in copies:
                path.unlink(missing_ok=True)

        self._transaction(change, discard_copies)
        self.cancel()
        return results

    def _new_account(self, account: str, answer: dict, pending: dict) -> dict:
        parsed, rows = pending["parsed"], pending["rows"]
        spent = answer["spent"]
        if parsed.sign_known or spent is None:
            invert = parsed.invert or (purchases_look_positive(parsed, rows) and spent is None)
        else:
            invert = bool(spent) == (sample_row(rows).cents > 0)
        info = {"name": account_name(answer["bank"], answer["type"], answer["number"]),
                "bank": answer["bank"], "number": answer["number"], "type": answer["type"],
                "invert_sign": invert}
        self.ledger.accounts[account] = info
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
        # Rows from the bank feed never came from a file, so they stay.
        self.ledger.rows = [r for r in self.ledger.rows if r["account"] != account or r["sync_id"]]
        self.ledger.imports = [i for i in self.ledger.imports if i["account"] != account]
        for entry in keep:
            path = self.imported / self._key(entry)
            if not path.exists():
                raise BudgetError(f"The saved copy of {entry['file']} is missing, so this can't be "
                                  "undone safely. Nothing was changed.")
            rows = self._rows_for(parse_file(path), entry, info)
            result = self.ledger.merge(account, self._signed(rows, info["invert_sign"]), entry["file"])
            result.update(imported_at=entry["imported_at"], stored=entry.get("stored", ""),
                          file_account=entry.get("file_account", ""))

    @staticmethod
    def _rows_for(parsed: ParsedFile, entry: dict, info: dict) -> list:
        """Which rows of a saved file went into this account."""
        wanted = entry.get("file_account")
        if wanted:
            rows = [r for r in parsed.rows if (r.account or parsed.account or "") == wanted]
        else:  # imported before the file's own number was recorded
            rows = [r for r in parsed.rows if (r.account or info["number"]) == info["number"]]
            if not rows and len({r.account for r in parsed.rows}) == 1:
                rows = parsed.rows  # a one-account file whose number was corrected in review
        if not rows:
            raise BudgetError(f"{entry['file']} no longer matches this account, so this can't be "
                              "undone safely. Nothing was changed.")
        return rows

    def _remove_stored(self, keys: set[str]) -> None:
        still_used = {self._key(i) for i in self.ledger.imports}
        for key in keys - still_used:
            (self.imported / key).unlink(missing_ok=True)

    def _transaction(self, change, undo=None) -> None:
        """Change the ledger against a snapshot, so any failure leaves your data as it was."""
        snapshot = self.ledger.snapshot()
        try:
            change()
            self.ledger.save()
        except Exception:
            self.ledger.restore(snapshot)
            if undo:
                undo()
            raise

    def remove_import(self, key: str) -> dict:
        entries = [i for i in self.ledger.imports if self._key(i) == key]
        if not entries:
            raise BudgetError("That import is already gone.")

        def change():
            for account in {e["account"] for e in entries}:
                keep = [i for i in self.ledger.imports if i["account"] == account and self._key(i) != key]
                self._rebuild(account, keep)
                if not keep and not any(r["account"] == account for r in self.ledger.rows):
                    del self.ledger.accounts[account]

        before = len(self.ledger.rows)
        self._transaction(change)
        for account in {e["account"] for e in entries} - set(self.ledger.accounts):
            self.sync.forget_account(account)
        self._remove_stored({key})
        return {"removed": before - len(self.ledger.rows)}

    def remove_account(self, account: str) -> dict:
        if account not in self.ledger.accounts:
            raise BudgetError("That account is already gone.")
        keys = {self._key(i) for i in self.ledger.imports if i["account"] == account}

        def change():
            self.ledger.rows = [r for r in self.ledger.rows if r["account"] != account]
            self.ledger.imports = [i for i in self.ledger.imports if i["account"] != account]
            del self.ledger.accounts[account]

        before = len(self.ledger.rows)
        self._transaction(change)
        self.sync.forget_account(account)
        self._remove_stored(keys)
        return {"removed": before - len(self.ledger.rows)}

    # ---- rules

    def _matching(self, pattern: str) -> list[dict]:
        compiled = re.compile(pattern, re.I)
        return [r for r in self.ledger.rows if compiled.search(r["description"].upper())]

    def rules(self) -> list[dict]:
        """Rules in the order they apply, newest first, each with what it matches."""
        found = []
        for rule in rules.read(self.rules_path):
            text = literal(rule.pattern)
            shared = {"line": rule.line, "category": rule.category, "merchant": rule.merchant}
            try:
                hits = self._matching(rule.pattern)
            except re.error:
                found.append({**shared, "text": rule.pattern, "advanced": True, "broken": True, "count": 0, "total": 0})
                continue
            found.append({**shared, "text": rule.pattern if text is None else text, "advanced": text is None,
                          "broken": False, "count": len(hits), "total": sum(r["cents"] for r in hits) / 100})
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

    def suggest_rule(self, merchant: str, descriptions: list[str]) -> dict:
        """The rule already covering the first description, because a new one would only sit
        on top of it; otherwise text to start a new rule from."""
        text = descriptions[0].upper()
        for rule in rules.read(self.rules_path):
            try:
                hit = re.search(rule.pattern, text, re.I)
            except re.error:
                continue
            if hit:
                return {"rule": next(r for r in self.rules() if r["line"] == rule.line)}
        return {"text": analyze.match_text(merchant, descriptions)}

    def _write_rule_lines(self, lines: list[str]) -> None:
        write_files({self.rules_path: "\n".join(lines) + "\n"})

    def save_rule(self, original: str | None, text: str, category: str, merchant: str, advanced: bool = False) -> dict:
        """New rules go first: the first match wins, and a new one is usually the more specific."""
        if not category.strip():
            raise BudgetError("Choose a category.")
        pattern = self._pattern(text, advanced)
        out = io.StringIO()
        csv.writer(out, lineterminator="").writerow([pattern, category.strip(), merchant.strip()])
        line = out.getvalue()
        lines = rules.lines(self.rules_path)
        if original and original in lines:
            lines[lines.index(original)] = line
        else:
            lines = [existing for existing in lines if (rules.cells(existing) or [""])[0].strip() != pattern]
            at = next((i + 1 for i, existing in enumerate(lines) if existing.strip().lower().startswith("match,")), None)
            if at is None:
                lines.append("match,category,merchant")
                at = len(lines)
            lines.insert(at, line)
        self._write_rule_lines(lines)
        return {"count": len(self._matching(pattern))}

    def delete_rule(self, line: str) -> None:
        lines = rules.lines(self.rules_path)
        if line not in lines:
            raise BudgetError("That rule is already gone.")
        lines.remove(line)
        self._write_rule_lines(lines)

    # ---- single transactions

    def edits(self) -> dict[str, dict]:
        """Transactions changed by hand, by analyze.edit_key: a category and maybe a name."""
        return self._choices(self.edits_path, analyze.valid_edit, "transaction changes")

    def _edit_key(self, tx: dict) -> str:
        try:
            key = analyze.edit_key(tx["date"], tx["account"], int(tx["cents"]), tx["description"], int(tx["n"]))
        except (KeyError, TypeError, ValueError, AttributeError) as e:
            raise BudgetError("That transaction couldn't be found.") from e
        if key not in analyze.edit_keys(self.ledger.rows):
            raise BudgetError("That transaction is gone.")
        return key

    def _write_edits(self, edits: dict[str, dict]) -> None:
        write_files({self.edits_path: json.dumps(edits, indent=2, sort_keys=True)})

    def save_edit(self, tx: dict, category: str, merchant: str) -> None:
        """Change one transaction, leaving rules and everything else as they are."""
        if not category.strip():
            raise BudgetError("Choose a category.")
        key = self._edit_key(tx)
        self._write_edits({**self.edits(), key: {"category": category.strip(), "merchant": merchant.strip()}})

    def clear_edit(self, tx: dict) -> None:
        edits = self.edits()
        if edits.pop(self._edit_key(tx), None) is None:
            raise BudgetError("That change is already gone.")
        self._write_edits(edits)

    # ---- budgets

    def budgets(self) -> dict[str, dict]:
        """Category to target: an amount in cents, or a percent of income."""
        return self._choices(self.budgets_path, _valid_target, "budgets")

    def _choices(self, path: Path, valid, what: str) -> dict[str, dict]:
        if not path.exists():
            return {}
        try:
            saved = json.loads(read_text(path))
        except ValueError:
            saved = None
        good = {k: v for k, v in saved.items() if valid(v)} if isinstance(saved, dict) else {}
        if saved != good:
            self._set_aside(path, good, what)
        return good

    def _set_aside(self, path: Path, good: dict[str, dict], what: str) -> None:
        """These are worth less than a working app. Keep what's readable, keep the file
        so nothing is lost, and say so."""
        aside = unique_path(self.home, f"{path.stem}.damaged.json")
        shutil.copy2(path, aside)
        write_files({path: json.dumps(good, indent=2, sort_keys=True)})
        self.notices.append({"level": "warning", "title": f"Some {what} couldn't be read",
                             "detail": f"Any that are missing need adding again. The damaged file is "
                                       f"saved as {aside.name} in your data folder."})

    def _write_budgets(self, budgets: dict[str, dict]) -> None:
        write_files({self.budgets_path: json.dumps(budgets, indent=2, sort_keys=True)})

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

    # ---- undoing the last small change

    def _undo_files(self) -> list[Path]:
        """What the small changes write: rules, single transactions, budgets and account details.
        Imports and removals rebuild the ledger and ask first, so they aren't undone this way."""
        return [self.rules_path, self.edits_path, self.budgets_path, self.ledger.accounts_path]

    @staticmethod
    def _read(path: Path) -> bytes | None:
        return path.read_bytes() if path.exists() else None

    def undoable(self, work, *args):
        """Make a small change and keep what it replaced, so it can be undone."""
        before = {path: self._read(path) for path in self._undo_files()}
        result = work(*args)
        changed = {path: (old, self._read(path)) for path, old in before.items()}
        self._undo = {path: pair for path, pair in changed.items() if pair[0] != pair[1]} or None
        return result

    def can_undo(self) -> bool:
        return bool(self._undo)

    def undo(self) -> None:
        """Put back what the last small change replaced, unless something has changed it since:
        then putting it back would quietly lose that newer change too."""
        if not self._undo:
            raise BudgetError("There's nothing to undo.")
        if any(self._read(path) != after for path, (_, after) in self._undo.items()):
            self._undo = None
            raise BudgetError("Something else changed since, so that can't be undone.")
        put_back = {path: before.decode("utf-8") for path, (before, _) in self._undo.items() if before is not None}
        if put_back:
            write_files(put_back)
        for path, (before, _) in self._undo.items():
            if before is None:
                path.unlink(missing_ok=True)
        if self.ledger.accounts_path in self._undo:
            self.ledger.accounts = self.ledger._load_accounts()
            self.ledger._recover_accounts()
        self._undo = None

    # ---- account details

    def update_account(self, account: str, name: str, kind: str, balance: str, as_of: str) -> None:
        info = self.ledger.accounts.get(account)
        if info is None:
            raise BudgetError("That account is gone.")
        if not name.strip():
            raise BudgetError("Give the account a name.")
        if kind not in TYPES:
            raise BudgetError("Choose the kind of account this is.")
        cents, day = None, None
        if balance.strip():
            cents = parse_money(balance)
            if cents is None:
                raise BudgetError("That balance doesn't look like an amount.")
            try:
                day = date.fromisoformat(as_of) if as_of else date.today()
            except ValueError as e:
                raise BudgetError("That date doesn't look right.") from e
        info.update(name=name.strip(), type=kind)
        info.pop("recovered", None)
        if cents is not None:
            pin_balance(info, cents, day)
        self.ledger.save_accounts()
