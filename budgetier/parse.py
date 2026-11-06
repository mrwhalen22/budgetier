"""Turn one bank CSV export into normalized rows.

Banks disagree on nearly everything, so columns are found by alias rather than
by a per-bank parser. SIGNATURES only adds what the columns can't say: which
bank it is, what kind of account, and whether the signs are flipped.

Convention after parsing: amounts are integer cents, negative = money out.
"""
from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path

ALIASES = {
    "date": ["transaction date", "trans. date", "trans date", "date", "posting date",
             "posted date", "post date", "clearing date", "booking date", "effective date"],
    "description": ["description", "transaction description", "payee", "name", "merchant",
                    "memo", "narrative", "details"],
    "amount": ["amount", "transaction amount", "amount (usd)", "amt", "net amount"],
    "debit": ["debit", "debits", "debit amount", "withdrawal", "withdrawals", "withdrawal amount",
              "money out", "paid out"],
    "credit": ["credit", "credits", "credit amount", "deposit", "deposits", "deposit amount",
               "money in", "paid in"],
    "balance": ["balance", "running bal.", "running bal", "running balance", "ledger balance"],
    "category": ["category", "transaction category"],
    "account": ["account number", "account #", "account no", "account no.", "account",
                "card no.", "card number", "card no", "card"],
    "status": ["status"],
    "indicator": ["credit debit indicator", "debit/credit", "credit/debit", "dr/cr", "cr/dr",
                  "transaction type", "type", "details", "transaction"],
}

# (columns that must all be present, bank, account type, purchases are positive)
# None means this layout doesn't settle it: USAA uses it for checking (purchases
# negative) and for cards (purchases positive), so the amounts have to decide.
SIGNATURES = [
    ({"transaction date", "post date", "description", "category", "type", "amount"},
     "Chase", "credit", False),
    ({"details", "posting date", "description", "amount", "type", "balance"},
     "Chase", "checking", False),
    ({"transaction date", "posted date", "card no.", "description", "category", "debit", "credit"},
     "Capital One", "credit", False),
    ({"account number", "transaction description", "transaction date", "transaction type",
      "transaction amount", "balance"}, "Capital One", "checking", False),
    ({"trans. date", "post date", "description", "amount", "category"},
     "Discover", "credit", True),
    ({"status", "date", "description", "debit", "credit"}, "Citi", "credit", False),
    ({"posted date", "reference number", "payee", "address", "amount"},
     "Bank of America", "credit", False),
    ({"date", "description", "amount", "running bal."}, "Bank of America", "checking", False),
    ({"transaction date", "clearing date", "description", "merchant", "category", "type",
      "amount (usd)"}, "Apple Card", "credit", True),
    ({"date", "description", "original description", "category", "amount", "status"},
     "USAA", None, None),
    ({"date", "time", "amount", "type", "description"}, "Ally", "checking", False),
    ({"date", "transaction", "name", "memo", "amount"}, "U.S. Bank", "checking", False),
    ({"date", "description", "check number", "amount"}, "Fifth Third", "checking", False),
    ({"date", "description", "card member", "amount"}, "American Express", "credit", True),
    ({"date", "description", "amount", "extended details"}, "American Express", "credit", True),
]

# Recognized in the filename or the lines above the header.
BANK_NAMES = [
    (r"chase", "Chase"),
    (r"amex|american[ _-]?express", "American Express"),
    (r"capital[ _-]?one|capone", "Capital One"),
    (r"discover", "Discover"),
    (r"citi(bank)?", "Citi"),
    (r"bank[ _-]?of[ _-]?america|\bbofa\b|\bboa\b", "Bank of America"),
    (r"wells[ _-]?fargo", "Wells Fargo"),
    (r"u\.?s\.?[ _-]?bank", "U.S. Bank"),
    (r"fifth[ _-]?third|\b5[ _/-]?3[ _-]?bank", "Fifth Third"),
    (r"synchrony", "Synchrony"),
    (r"\bally\b", "Ally"),
    (r"usaa", "USAA"),
    (r"apple", "Apple Card"),
    (r"navy[ _-]?federal", "Navy Federal"),
    (r"\bpnc\b", "PNC"),
    (r"\btd[ _-]?bank\b", "TD Bank"),
    (r"schwab", "Charles Schwab"),
    (r"fidelity", "Fidelity"),
    (r"sofi", "SoFi"),
    (r"marcus", "Marcus"),
]

# These issuers report purchases as positive even with a bare Date/Description/Amount file.
POSITIVE_PURCHASE_BANKS = {"American Express", "Discover", "Apple Card"}

DATE_FORMATS = ["%m/%d/%Y", "%m/%d/%y", "%Y-%m-%d", "%m-%d-%Y", "%m-%d-%y", "%Y/%m/%d",
                "%d/%m/%Y", "%d/%m/%y", "%d-%b-%Y", "%d %b %Y", "%b %d, %Y", "%B %d, %Y"]


@dataclass
class RawRow:
    date: date
    description: str
    cents: int
    balance: int | None = None
    bank_category: str = ""
    account: str = ""  # last 4 from the row itself, when the file carries one


@dataclass
class ParsedFile:
    path: Path
    rows: list[RawRow]
    bank: str | None = None
    account: str | None = None
    account_type: str = "checking"
    type_is_guess: bool = True
    sign_known: bool = False  # False: a single Amount column we can't vouch for
    invert: bool = False
    warnings: list[str] = field(default_factory=list)


class ParseError(Exception):
    pass


def parse_money(text: str) -> int | None:
    """Return cents, or None if the text isn't an amount."""
    s = (text or "").strip().replace("−", "-").replace("$", "").replace(",", "").strip()
    if not s:
        return None
    sign = 1
    upper = s.upper()
    if upper.endswith("CR"):
        s = s[:-2].strip()
    elif upper.endswith("DR"):
        s, sign = s[:-2].strip(), -1
    if s.startswith("(") and s.endswith(")"):
        s, sign = s[1:-1], -1
    if s.endswith("-"):
        s, sign = s[:-1], -1
    try:
        value = Decimal(s.strip())
    except InvalidOperation:
        return None
    if not value.is_finite():  # "NaN" and "Infinity" are valid decimals, but not amounts
        return None
    return sign * int((value * 100).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def _clean_date(text: str) -> str:
    return re.sub(r"[T ]\d{1,2}:\d{2}.*$", "", (text or "").strip())


def _try_date(text: str, fmt: str) -> date | None:
    try:
        return datetime.strptime(text, fmt).date()
    except ValueError:
        return None


def _pick_date_format(values: list[str]) -> str:
    """The format that reads the most values; ties go to the US reading."""
    best, best_hits = DATE_FORMATS[0], -1
    for fmt in DATE_FORMATS:
        hits = sum(1 for v in values if _try_date(v, fmt))
        if hits > best_hits:
            best, best_hits = fmt, hits
    return best


def last4(text: str) -> str:
    digits = re.sub(r"\D", "", text or "")
    return digits[-4:] if len(digits) >= 4 else ""


def _read_text(path: Path) -> str:
    raw = path.read_bytes()
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return raw.decode("utf-16", errors="replace")
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return raw.decode("cp1252", errors="replace")


def _columns(header: list[str]) -> dict[str, int]:
    names = [h.strip().lower() for h in header]
    found: dict[str, int] = {}
    for role, aliases in ALIASES.items():
        for alias in aliases:
            if alias in names:
                found[role] = names.index(alias)
                break
    return found


def _find_header(rows: list[list[str]]) -> tuple[int, dict[str, int]] | None:
    for i, row in enumerate(rows[:40]):
        cols = _columns(row)
        if "date" in cols and "description" in cols and (
                "amount" in cols or "debit" in cols or "credit" in cols):
            return i, cols
    return None


def _headerless(rows: list[list[str]]) -> dict[str, int] | None:
    """Wells Fargo-style exports have no header: date, amount, *, check no, description."""
    first = next((r for r in rows if any(c.strip() for c in r)), None)
    if not first or len(first) < 3:
        return None
    if not any(_try_date(_clean_date(first[0]), f) for f in DATE_FORMATS):
        return None
    money = [i for i in range(1, len(first)) if parse_money(first[i]) is not None]
    if not money:
        return None
    text = [i for i in range(1, len(first)) if i not in money]
    if not text:
        return None
    return {"date": 0, "amount": money[0],
            "description": max(text, key=lambda i: len(first[i]))}


def _table(text: str) -> tuple[list[list[str]], list[str], int, dict[str, int]]:
    """Find the transaction table. Returns (data rows, header, header index, columns)."""
    for delimiter in ",\t;|":
        rows = list(csv.reader(io.StringIO(text), delimiter=delimiter))
        found = _find_header(rows)
        if found:
            i, cols = found
            return rows[i + 1:], rows[i], i, cols
    rows = list(csv.reader(io.StringIO(text)))
    cols = _headerless(rows)
    if cols:
        return rows, [], 0, cols
    raise ParseError("couldn't find date, description and amount columns")


def _from_filename(stem: str) -> tuple[str | None, str | None]:
    """(bank, account) hints. `MyCreditUnion_5678_jan.csv` is the documented convention."""
    bank = next((name for pattern, name in BANK_NAMES if re.search(pattern, stem, re.I)), None)
    m = re.search(r"(?:chase|acct|account|card|ending(?:[ _-]?in)?|x{2,}|#)[ _-]*(\d{4,})(?![-_]\d{2})", stem, re.I)
    account = m.group(1)[-4:] if m else None
    if not account:
        bare = [t for t in re.findall(r"(?<!\d)\d{4}(?!\d)", stem) if not re.match(r"19|20", t)]
        account = bare[0] if bare else None
    if not bank and account:
        m = re.match(r"([A-Za-z][A-Za-z &]+?)(?:[ _-]+(?:savings?|checking|credit|card))?"
                     r"[ _-]+\d{4}(?!\d)", stem, re.I)
        bank = m.group(1).strip() if m else None
    return bank, account


def _from_preamble(lines: str) -> tuple[str | None, str | None]:
    bank = next((name for pattern, name in BANK_NAMES if re.search(pattern, lines, re.I)), None)
    m = re.search(r"(?:account|acct|card)[^0-9\n]{0,30}?[xX*.\- ]*(\d{4,})", lines, re.I)
    return bank, (m.group(1)[-4:] if m else None)


def _guess_type(text: str) -> str | None:
    text = text.lower()
    if re.search(r"saving", text):
        return "savings"
    if re.search(r"checking", text):
        return "checking"
    if re.search(r"credit|\bcard\b|visa|mastercard", text):
        return "credit"
    return None


def _cell(row: list[str], cols: dict[str, int], role: str) -> str:
    i = cols.get(role)
    return row[i].strip() if i is not None and i < len(row) else ""


def _signed_cents(row, cols) -> tuple[int | None, bool]:
    """(cents, the sign is already reliable)."""
    if "amount" in cols:
        return parse_money(_cell(row, cols, "amount")), False
    debit = parse_money(_cell(row, cols, "debit"))
    credit = parse_money(_cell(row, cols, "credit"))
    if debit:
        return -abs(debit), True
    if credit:
        return abs(credit), True
    return None, True


def _indicator_signs(body, cols) -> list[int] | None:
    """Unsigned amounts plus a debit/credit column (Capital One 360 does this)."""
    if "indicator" not in cols or "amount" not in cols:
        return None
    signs, unsigned = [], True
    for row in body:
        cents = parse_money(_cell(row, cols, "amount"))
        word = _cell(row, cols, "indicator").lower()
        if cents is None:
            signs.append(1)
            continue
        if cents < 0:
            unsigned = False
        if word in ("debit", "dr", "d", "withdrawal"):
            signs.append(-1)
        elif word in ("credit", "cr", "c", "deposit"):
            signs.append(1)
        else:
            return None
    return signs if unsigned and -1 in signs else None


def parse_file(path: Path) -> ParsedFile:
    text = _read_text(path)
    try:
        body, header, header_at, cols = _table(text)
    except csv.Error as e:  # such as a binary file renamed to .csv
        raise ParseError("this doesn't look like a bank export") from e
    names = {h.strip().lower() for h in header}
    preamble = "\n".join(text.splitlines()[:header_at])

    file_bank, file_account = _from_filename(path.stem)
    pre_bank, pre_account = _from_preamble(preamble)

    signature = next((s for s in SIGNATURES if s[0] <= names), None)
    bank = signature[1] if signature else (file_bank or pre_bank)
    known_type = signature[2] if signature else None
    account_type, type_is_guess = known_type or "checking", known_type is None

    # A filename saying "savings" beats a signature shared by checking and savings.
    hinted = _guess_type(path.stem) or _guess_type(preamble)
    if hinted and account_type != "credit":
        account_type, type_is_guess = hinted, False
    elif hinted and type_is_guess:
        account_type, type_is_guess = hinted, False
    if bank in POSITIVE_PURCHASE_BANKS and type_is_guess:
        account_type, type_is_guess = "credit", False

    date_fmt = _pick_date_format([_clean_date(_cell(r, cols, "date")) for r in body])
    indicator = _indicator_signs(body, cols)

    rows: list[RawRow] = []
    sign_reliable = indicator is not None
    pending = unreadable = 0
    for n, row in enumerate(body):
        if not any(c.strip() for c in row):
            continue
        if _cell(row, cols, "status").lower() == "pending":
            pending += 1  # re-appears posted, often reworded; would double count
            continue
        day = _try_date(_clean_date(_cell(row, cols, "date")), date_fmt)
        cents, reliable = _signed_cents(row, cols)
        if day is None:
            unreadable += 1
            continue
        if not cents:
            continue  # "Beginning balance" lines and $0 informational rows
        sign_reliable = sign_reliable or reliable
        if indicator:
            cents *= indicator[n]
        rows.append(RawRow(
            date=day,
            description=re.sub(r"\s+", " ", _cell(row, cols, "description")),
            cents=cents,
            balance=parse_money(_cell(row, cols, "balance")),
            bank_category=_cell(row, cols, "category"),
            account=last4(_cell(row, cols, "account")),
        ))

    # Exports may run newest-first, or in newest-first blocks (Fifth Third). Same-day
    # order decides closing balances, so settle the direction before sorting by date.
    falling = sum(a.date > b.date for a, b in zip(rows, rows[1:]))
    rising = sum(a.date < b.date for a, b in zip(rows, rows[1:]))
    if falling > rising:
        rows.reverse()
    rows.sort(key=lambda r: r.date)

    invert = bool(signature and signature[3]) or (
        bank in POSITIVE_PURCHASE_BANKS and account_type == "credit" and "amount" in cols)
    parsed = ParsedFile(
        path=path, rows=rows, bank=bank, account=pre_account or file_account,
        account_type=account_type, type_is_guess=type_is_guess,
        sign_known=sign_reliable or invert or (signature is not None and signature[3] is not None),
        invert=invert,
    )
    if pending:
        parsed.warnings.append(f"skipped {pending} pending row(s); they'll arrive once posted")
    if unreadable:
        parsed.warnings.append(f"skipped {unreadable} row(s) with no readable date")
    if not rows:
        raise ParseError("no transactions found")
    return parsed
