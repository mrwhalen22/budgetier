"""Import whatever is in inbox/, update the ledger, regenerate the reports."""
from __future__ import annotations

import argparse
import re
import shutil
import sys
import webbrowser
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path

from . import analyze, pdf2csv, report_html, report_xlsx
from .ledger import Ledger
from .parse import ParsedFile, ParseError, parse_file, parse_money

RULES_TEMPLATE = """\
# Your own categorization rules. They run first and override everything built in,
# and re-apply to your whole history on every run.
# match is a case-insensitive regular expression tested against the bank's description.
# merchant is optional and merges different spellings under one name.
# Use category Transfer for moves between your own accounts (they stop counting as spending).
match,category,merchant
# TRADER JOE,Groceries,Trader Joe's
# VENMO CASHOUT,Transfer,
"""


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def _ask(prompt: str) -> str:
    try:
        return input(prompt).strip()
    except EOFError:
        return ""


def _resolve(parsed: ParsedFile, args, known: dict) -> tuple[str | None, str | None]:
    bank = args.bank or parsed.bank
    account = args.account[-4:] if args.account else parsed.account
    if bank and (account or all(r.account for r in parsed.rows)):
        return bank, account
    if not sys.stdin.isatty():
        return bank, account
    print(f"  {parsed.path.name}: which account is this?")
    bank = bank or _ask("    Bank name: ")
    if not account:
        # Some exports (Fifth Third) never state the number, so offer the last answer.
        seen = [a["number"] for a in known.values() if a["bank"] == bank]
        hint = f" [{seen[-1]}]" if seen else ""
        account = _ask(f"    Last 4 digits of the account{hint}: ")[-4:] or (seen[-1] if seen else "")
    return bank, account


def _purchases_look_positive(parsed: ParsedFile, rows) -> bool:
    """Spending is most of any account, so mostly-positive amounts mean a card that
    reports purchases as positive. A savings account can honestly be nearly all
    deposits, so it doesn't get this test."""
    if parsed.sign_known or parsed.account_type == "savings" or len(rows) < 5:
        return False
    return sum(1 for r in rows if r.cents > 0) / len(rows) > 0.7


def _ask_type(bank: str, number: str, guess: str) -> str:
    choices = {"1": "checking", "2": "savings", "3": "credit",
               "c": "checking", "s": "savings", "cc": "credit", "credit": "credit"}
    while True:
        default = next(k for k, v in choices.items() if v == guess)
        answer = _ask(f"    {bank} {number} is new. 1 = checking, 2 = savings, "
                      f"3 = credit card [{default}]: ").lower()
        if not answer:
            return guess
        if answer in choices:
            return choices[answer]
        print("    Please answer 1, 2 or 3.")


def _ask_inverted(rows, guess: bool) -> bool:
    """Show a typical row from this file: seeing it is what makes the answer certain."""
    positive = [r for r in rows if r.cents > 0]
    negative = [r for r in rows if r.cents < 0]
    sample = (positive if len(positive) >= len(negative) else negative)[0]
    spent_if_positive = guess
    default = "y" if (sample.cents > 0) == spent_if_positive else "n"
    answer = _ask(f"    This file shows \"{sample.description}\" on {sample.date} as "
                  f"{sample.cents / 100:.2f}. Was that money you spent? [{default}]: ").lower()
    spent = (answer or default).startswith("y")
    return spent == (sample.cents > 0)


def _ensure_account(ledger: Ledger, parsed: ParsedFile, bank: str, number: str, rows) -> str:
    """Signs and type are settled once, so a small later file can't flip an account.

    At a terminal the person answers; otherwise the amounts decide and it's flagged."""
    account_id = f"{_slug(bank)}-{number}"
    if account_id not in ledger.accounts:
        guessed = _purchases_look_positive(parsed, rows)
        account_type = "credit" if guessed else parsed.account_type
        invert = parsed.invert or guessed
        asked = sys.stdin.isatty()
        if asked:
            account_type = _ask_type(bank, number, account_type)
            if not parsed.sign_known:
                invert = _ask_inverted(rows, invert)
        label = {"credit": "Card", "savings": "Savings", "checking": "Checking"}[account_type]
        ledger.accounts[account_id] = {
            "name": f"{bank} {label} {number}", "bank": bank, "number": number,
            "type": account_type, "invert_sign": invert}
        note = ""
        if guessed and not asked:
            ledger.accounts[account_id]["sign_guessed"] = True
            note = " (looks like a card from its amounts; fix in accounts.json if wrong)"
        elif parsed.type_is_guess and not asked:
            note = " (type is a guess; fix in accounts.json if wrong)"
        print(f"  New account: {ledger.accounts[account_id]['name']}{note}")
    return account_id


def import_file(ledger: Ledger, path: Path, args) -> bool:
    try:
        parsed = parse_file(path)
    except (ParseError, OSError) as e:
        print(f"  SKIPPED {path.name}: {e}")
        return False
    bank, default_number = _resolve(parsed, args, ledger.accounts)
    if not bank or not (default_number or all(r.account for r in parsed.rows)):
        print(f"  SKIPPED {path.name}: can't tell which account this is. Rename it like "
              "BankName_1234.csv or pass --bank and --account.")
        return False

    by_number = defaultdict(list)
    for row in parsed.rows:  # one file can hold several cards
        by_number[row.account or default_number].append(row)

    for number, rows in by_number.items():
        account_id = _ensure_account(ledger, parsed, bank, number, rows)
        if ledger.accounts[account_id]["invert_sign"]:
            for row in rows:
                row.cents = -row.cents
        result = ledger.merge(account_id, rows, path.name)
        print(f"  {path.name} -> {ledger.accounts[account_id]['name']}: "
              f"{result['added']} new, {result['duplicates']} already had "
              f"({result['first']} to {result['last']})")
    for warning in parsed.warnings:
        print(f"    note: {warning}")
    return True


def _pin_balance(info: dict, cents: int, day: date) -> None:
    info["balance_anchor"] = {"date": day.isoformat(), "amount": cents / 100}
    info.pop("balance_skipped", None)


def _ask_balances(ledger: Ledger) -> None:
    """Ask once per account that has no balance of its own. Enter skips for good;
    --set-balance still works later."""
    has_column = {r["account"] for r in ledger.rows if r["balance"] is not None}
    has_rows = {r["account"] for r in ledger.rows}
    for account, info in ledger.accounts.items():
        if (account in has_column or account not in has_rows
                or "balance_anchor" in info or info.get("balance_skipped")):
            continue
        question = (f"What do you owe on {info['name']} right now?" if info["type"] == "credit"
                    else f"What's the balance of {info['name']} right now?")
        while True:
            try:
                answer = input(f"  {question} From the bank's website; Enter to skip: ").strip()
            except EOFError:
                return  # nobody there to answer, so don't record a skip
            if not answer:
                info["balance_skipped"] = True
                break
            cents = parse_money(answer)
            if cents is not None:
                _pin_balance(info, cents, date.today())
                break
            print("  Please enter an amount, like 1234.56.")


def _set_balance(ledger: Ledger, key: str, amount: str, as_of: str | None) -> bool:
    matches = [a for a, info in ledger.accounts.items() if key in (a, info["number"])]
    cents = parse_money(amount)
    if len(matches) != 1 or cents is None:
        known = ", ".join(info["number"] for info in ledger.accounts.values())
        print(f"Couldn't set that balance. Use the last 4 digits ({known}) and an amount like 1234.56.")
        return False
    try:
        day = date.fromisoformat(as_of) if as_of else date.today()
    except ValueError:
        print("Use --as-of YYYY-MM-DD.")
        return False
    _pin_balance(ledger.accounts[matches[0]], cents, day)
    print(f"Balance set: {ledger.accounts[matches[0]]['name']} ${cents / 100:,.2f} on {day}")
    return True


def _archive(path: Path, imported: Path) -> None:
    target = imported / path.name
    if target.exists():
        target = imported / f"{path.stem}.{datetime.now():%Y%m%d-%H%M%S}{path.suffix}"
    shutil.move(str(path), target)


def convert_pdfs(inbox: Path, imported: Path) -> int:
    """Turn PDFs into CSVs in place, so they import like any other file."""
    failed = 0
    for path in sorted(p for p in inbox.iterdir() if p.suffix.lower() == ".pdf"):
        try:
            statement = pdf2csv.read_pdf(path)
        except pdf2csv.ConvertError as e:
            print(f"  SKIPPED {path.name}: {e}")
            failed += 1
            continue
        csv_path = pdf2csv.write_csv(statement, inbox)
        print(f"  {path.name} -> {csv_path.name}: {len(statement.rows)} rows, balances verified")
        for warning in statement.warnings:
            print(f"    note: {warning}")
        _archive(path, imported)
    return failed


def _data_folder() -> Path:
    from .service import app_home  # service imports this module
    return app_home()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="budgetier", description=__doc__)
    parser.add_argument("--home", type=Path, default=_data_folder(),
                        help="folder holding inbox/, data/, output/ (default: the app's data folder)")
    parser.add_argument("--bank", help="bank name, when a file doesn't reveal it")
    parser.add_argument("--account", help="account number or last 4, when a file doesn't reveal it")
    parser.add_argument("--open", action="store_true", help="open the dashboard when done")
    parser.add_argument("--set-balance", nargs=2, metavar=("ACCOUNT", "AMOUNT"),
                        help="last 4 digits and today's balance; for a card, the amount owed")
    parser.add_argument("--as-of", metavar="YYYY-MM-DD", help="date of --set-balance (default: today)")
    args = parser.parse_args(argv)

    home: Path = args.home.resolve()
    inbox, imported, output = home / "inbox", home / "imported", home / "output"
    for folder in (inbox, imported, output):
        folder.mkdir(parents=True, exist_ok=True)
    rules_path = home / "rules.csv"
    if not rules_path.exists():
        rules_path.write_text(RULES_TEMPLATE, encoding="utf-8")

    ledger = Ledger(home)
    skipped = convert_pdfs(inbox, imported)
    files = sorted(p for p in inbox.iterdir() if p.suffix.lower() == ".csv")
    print(f"{len(files)} file(s) in inbox" if files else "No new files in inbox.")
    done = []
    for path in files:
        if import_file(ledger, path, args):
            done.append(path)
        else:
            skipped += 1
    ledger.save()
    for path in done:  # only after the ledger is safely on disk
        _archive(path, imported)

    if args.set_balance and not _set_balance(ledger, *args.set_balance, args.as_of):
        return 2
    if sys.stdin.isatty():
        _ask_balances(ledger)
    ledger.save_accounts()

    if not ledger.rows:
        print(f"Nothing to report yet. Put bank CSV exports in {inbox} and run again.")
        return 1 if skipped else 0

    rows = analyze.classify(ledger.rows, ledger.accounts, analyze.load_rules(rules_path))
    recurring = analyze.find_recurring(rows)
    checks = analyze.checks(rows, ledger.accounts, ledger.imports)

    html_path = output / "budget.html"
    report_html.write(html_path, rows, ledger.accounts, recurring, checks, ledger.imports)
    print(f"Dashboard: {html_path}")
    xlsx_path = output / "budget.xlsx"
    try:
        report_xlsx.write(xlsx_path, rows, ledger.accounts, recurring, checks)
        print(f"Workbook:  {xlsx_path}")
    except PermissionError:
        print(f"Workbook not updated: close {xlsx_path.name} in Excel and run again.")

    for check in checks:
        print(f"  ! {check['title']}: {check['detail']}")
    if args.open:
        webbrowser.open(html_path.as_uri())
    return 1 if skipped else 0
