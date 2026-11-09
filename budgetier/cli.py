"""Import whatever is in inbox/, update the ledger, and write the workbook."""
from __future__ import annotations

import argparse
import sys
import webbrowser
from collections import defaultdict
from datetime import date
from pathlib import Path

from . import analyze, pdf2csv, report_xlsx, rules
from .accounts import account_id, account_name, pin_balance, purchases_look_positive, sample_row
from .ledger import Ledger
from .parse import ParsedFile, ParseError, parse_file, parse_money
from .storage import DataError, app_home, copy_in, hold_lock, unique_path, use_vault, write_files


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


def _ask_type(bank: str, number: str, guess: str) -> str:
    choices = {"1": "checking", "2": "savings", "3": "credit", "4": "investment", "5": "retirement", "6": "loan",
               "c": "checking", "s": "savings", "cc": "credit", "credit": "credit", "loan": "loan"}
    while True:
        default = next(k for k, v in choices.items() if v == guess)
        answer = _ask(f"    {bank} {number} is new. 1 = checking, 2 = savings, "
                      f"3 = credit card, 4 = investing, 5 = retirement, 6 = loan [{default}]: ").lower()
        if not answer:
            return guess
        if answer in choices:
            return choices[answer]
        print("    Please answer 1 to 5.")


def _ask_inverted(rows, guess: bool) -> bool:
    """Show a typical row from this file: seeing it is what makes the answer certain."""
    sample = sample_row(rows)
    spent_if_positive = guess
    default = "y" if (sample.cents > 0) == spent_if_positive else "n"
    answer = _ask(f"    This file shows \"{sample.description}\" on {sample.date} as "
                  f"{sample.cents / 100:.2f}. Was that money you spent? [{default}]: ").lower()
    spent = (answer or default).startswith("y")
    return spent == (sample.cents > 0)


def _ensure_account(ledger: Ledger, parsed: ParsedFile, bank: str, number: str, rows) -> str:
    """Signs and type are settled once, so a small later file can't flip an account.

    At a terminal the person answers; otherwise the amounts decide and it's flagged."""
    account = account_id(bank, number)
    if account not in ledger.accounts:
        guessed = purchases_look_positive(parsed, rows)
        account_type = "credit" if guessed else parsed.account_type
        invert = parsed.invert or guessed
        asked = sys.stdin.isatty()
        if asked:
            account_type = _ask_type(bank, number, account_type)
            if not parsed.sign_known:
                invert = _ask_inverted(rows, invert)
        ledger.accounts[account] = {
            "name": account_name(bank, account_type, number), "bank": bank, "number": number,
            "type": account_type, "invert_sign": invert}
        note = ""
        if guessed and not asked:
            ledger.accounts[account]["sign_guessed"] = True
            note = " (looks like a card from its amounts; fix in accounts.json if wrong)"
        elif parsed.type_is_guess and not asked:
            note = " (type is a guess; fix in accounts.json if wrong)"
        print(f"  New account: {ledger.accounts[account]['name']}{note}")
    return account


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
        account = _ensure_account(ledger, parsed, bank, number, rows)
        if ledger.accounts[account]["invert_sign"]:
            for row in rows:
                row.cents = -row.cents
        result = ledger.merge(account, rows, path.name)
        result["file_account"] = rows[0].account or parsed.account or ""
        print(f"  {path.name} -> {ledger.accounts[account]['name']}: "
              f"{result['added']} new, {result['duplicates']} already had "
              f"({result['first']} to {result['last']})")
    for warning in parsed.warnings:
        print(f"    note: {warning}")
    return True


def _ask_balances(ledger: Ledger) -> None:
    """Ask once per account that has no balance of its own. Enter skips for good;
    --set-balance still works later."""
    has_column = {r["account"] for r in ledger.rows if r["balance"] is not None}
    has_rows = {r["account"] for r in ledger.rows}
    for account, info in ledger.accounts.items():
        if (account in has_column or account not in has_rows
                or "balance_anchor" in info or info.get("balance_skipped")):
            continue
        question = (f"What do you owe on {info['name']} right now?" if info["type"] in ("credit", "loan")
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
                pin_balance(info, cents, date.today())
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
    pin_balance(ledger.accounts[matches[0]], cents, day)
    print(f"Balance set: {ledger.accounts[matches[0]]['name']} ${cents / 100:,.2f} on {day}")
    return True


def _archive(path: Path, imported: Path) -> None:
    copy_in(path, unique_path(imported, path.name))  # encrypted, if the data folder is
    path.unlink()


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


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="budgetier", description=__doc__)
    parser.add_argument("--home", type=Path, default=app_home(),
                        help="folder holding inbox/, data/, output/ (default: the app's data folder)")
    parser.add_argument("--bank", help="bank name, when a file doesn't reveal it")
    parser.add_argument("--account", help="account number or last 4, when a file doesn't reveal it")
    parser.add_argument("--open", action="store_true", help="open the workbook when done")
    parser.add_argument("--set-balance", nargs=2, metavar=("ACCOUNT", "AMOUNT"),
                        help="last 4 digits and today's balance; for a card, the amount owed")
    parser.add_argument("--as-of", metavar="YYYY-MM-DD", help="date of --set-balance (default: today)")
    args = parser.parse_args(argv)

    home: Path = args.home.resolve()
    home.mkdir(parents=True, exist_ok=True)
    lock = hold_lock(home)
    if lock is None:
        print("Budgetier is open. Close it, then run this again.")
        return 2
    try:
        if not _unlock(home):
            return 2
        return _run(args, home)
    except DataError as e:
        print(e)
        return 2
    finally:
        lock.close()


def _unlock(home: Path) -> bool:
    """An encrypted data folder needs its passcode, typed without showing it."""
    from getpass import getpass

    from . import vault
    if vault.read_header(home) is None:
        return True
    for _ in range(3):
        try:
            use_vault(vault.open_with(home, getpass("Passcode for your Budgetier data: ")))
            return True
        except vault.WrongKey:
            print("That isn't it.")
        except EOFError:
            break
    print("Budgetier's data is encrypted. Run this again with the passcode, or open the app.")
    return False


def _run(args, home: Path) -> int:
    inbox, imported, output = home / "inbox", home / "imported", home / "output"
    for folder in (inbox, imported, output):
        folder.mkdir(parents=True, exist_ok=True)
    rules_path = home / "rules.csv"
    if not rules_path.exists():
        write_files({rules_path: rules.TEMPLATE})

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

    rows = analyze.classify(ledger.rows, ledger.accounts, analyze.load_rules(rules_path),
                            analyze.load_edits(rules_path.with_name(analyze.EDITS_FILE)))
    recurring = analyze.find_recurring(rows)
    checks = analyze.checks(rows, ledger.accounts, ledger.imports)

    xlsx_path = output / "budget.xlsx"
    written = True
    try:
        report_xlsx.write(xlsx_path, rows, ledger.accounts, recurring, checks)
        print(f"Workbook: {xlsx_path}")
    except PermissionError:
        written = False
        print(f"Workbook not updated: close {xlsx_path.name} in Excel and run again.")

    for check in checks:
        print(f"  ! {check['title']}: {check['detail']}")
    if args.open and written:
        webbrowser.open(xlsx_path.as_uri())
    return 1 if skipped else 0
