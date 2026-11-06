"""Convert a Synchrony Bank account PDF into a CSV Budgetier can import.

    python -m budgetier.pdf2csv Synchrony.pdf

Files dropped in inbox/ are converted automatically; this is for checking one by
hand. Synchrony's PDF is a printed web page, so its columns don't line up and plain
text extraction pairs amounts with the wrong rows. This reads word positions, then
proves the result: every running balance must equal the one before it plus the
amount. If any row fails that, nothing is written.
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

from .parse import parse_money

DATE = re.compile(r"^[A-Z][a-z]{2} \d{1,2}, \d{4}$")
MONEY = re.compile(r"^-?\$[\d,]+\.\d{2}$")
LEFT_EDGE, RIGHT_EDGE = 150, 450  # date column | description column | money column


class ConvertError(Exception):
    pass


@dataclass
class Row:
    date: date
    description: str
    cents: int
    balance: int


@dataclass
class Statement:
    account: str
    is_savings: bool
    rows: list[Row]  # oldest first
    warnings: list[str] = field(default_factory=list)

    @property
    def filename(self) -> str:
        kind = "Savings_" if self.is_savings else ""
        return f"Synchrony_{kind}{self.account}.csv"


def _posted_words(pages: list[list[dict]]) -> list[dict]:
    """Words after the Posted Transactions heading, in reading order across pages.

    Reading across pages matters: a reference number can wrap onto the next page."""
    words = [{**w, "page": n} for n, page in enumerate(pages) for w in page]
    words.sort(key=lambda w: (w["page"], round(w["top"], 1), w["x0"]))
    start = next((i for i, w in enumerate(words) if w["text"].startswith("Posted Transactions")), None)
    if start is None:
        raise ConvertError("no 'Posted Transactions' section found")
    return words[start + 1:]


def _rows(words: list[dict]) -> list[Row]:
    found = []
    for w in words:
        text = w["text"].strip()
        if w["x0"] < LEFT_EDGE and DATE.match(text):
            found.append({"date": datetime.strptime(text, "%b %d, %Y").date(), "text": [], "money": []})
        elif found and w["x0"] >= RIGHT_EDGE and MONEY.match(text):
            found[-1]["money"].append(parse_money(text))
        elif found and LEFT_EDGE <= w["x0"] < RIGHT_EDGE:
            found[-1]["text"].append(text)
    rows = []
    for item in found:
        if len(item["money"]) != 2 or not item["text"]:
            raise ConvertError(f"the transaction on {item['date']} doesn't have one description, "
                               "one amount and one balance")
        amount, balance = item["money"]
        rows.append(Row(item["date"], " ".join(item["text"]), amount, balance))
    if not rows:
        raise ConvertError("no posted transactions found")
    return rows[::-1]


def _check_balances(rows: list[Row]) -> None:
    for older, newer in zip(rows, rows[1:]):
        if older.balance + newer.cents != newer.balance:
            raise ConvertError(
                f"balances don't add up at {newer.date} ({newer.description}): "
                f"${older.balance / 100:,.2f} + ${newer.cents / 100:,.2f} should be "
                f"${newer.balance / 100:,.2f}. Nothing was written, because the "
                "amounts may be paired with the wrong rows.")


def parse_pages(pages: list[list[dict]]) -> Statement:
    """Takes each page's words, as dicts with text, x0 and top."""
    header = " ".join(w["text"] for page in pages for w in page)
    if "synchronybank.com" not in header.lower() and "synchrony" not in header.lower():
        raise ConvertError("this doesn't look like a Synchrony Bank PDF, the only kind supported")
    number = re.search(r"X{4,}\s*(\d{4})\b", header)
    if not number:
        raise ConvertError("couldn't find the account number")

    rows = _rows(_posted_words(pages))
    _check_balances(rows)
    statement = Statement(number.group(1), "SAVINGS" in header.upper(), rows)
    current = re.search(r"Current Balance\s*:\s*(\$[\d,]+\.\d{2})", header)
    if current and parse_money(current.group(1)) != rows[-1].balance:
        statement.warnings.append(f"latest row shows ${rows[-1].balance / 100:,.2f} but the page's "
                                  f"current balance is {current.group(1)}; a pending item may explain it")
    return statement


def read_pdf(path: Path) -> Statement:
    try:
        import pdfplumber
    except ImportError as e:
        raise ConvertError("pdfplumber isn't installed; run: "
                           ".venv/Scripts/python -m pip install -r requirements.txt") from e
    try:
        with pdfplumber.open(path) as pdf:
            pages = [p.extract_words(keep_blank_chars=True, x_tolerance=2, y_tolerance=1)
                     for p in pdf.pages]
    except Exception as e:  # pdfplumber raises many unrelated types for bad or locked files
        raise ConvertError(f"couldn't read the PDF ({type(e).__name__})") from e
    if not any(pages):
        raise ConvertError("no text in this PDF; it may be a scanned image")
    return parse_pages(pages)


def write_csv(statement: Statement, folder: Path) -> Path:
    path = folder / statement.filename
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["Date", "Description", "Amount", "Balance"])
        for r in statement.rows:
            writer.writerow([r.date.isoformat(), r.description, f"{r.cents / 100:.2f}", f"{r.balance / 100:.2f}"])
    return path


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="budgetier.pdf2csv", description=__doc__.split("\n")[0])
    parser.add_argument("pdf", type=Path)
    parser.add_argument("-o", "--out", type=Path, help="folder for the CSV (default: next to the PDF)")
    args = parser.parse_args(argv)
    try:
        statement = read_pdf(args.pdf)
    except ConvertError as e:
        print(f"Not converted: {e}", file=sys.stderr)
        return 1
    path = write_csv(statement, args.out or args.pdf.parent)
    rows = statement.rows
    print(f"{path}: {len(rows)} transactions, {rows[0].date} to {rows[-1].date}, "
          f"balances verified, latest ${rows[-1].balance / 100:,.2f}")
    for warning in statement.warnings:
        print(f"  note: {warning}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
