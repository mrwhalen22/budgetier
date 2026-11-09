"""Categorize the ledger and work out what it says.

Every row gets a kind, and the totals depend on it:
  expense   money spent
  refund    money back from a merchant; nets against spending
  income    money earned
  estimate  a card payment whose purchases aren't imported. It stands in for them
            as spending, and stops once the card's history is imported and the
            payment pairs up. Without it, an unimported card reads as $0.
  transfer  money moving between your own accounts; counts as neither. Paying a
            card from checking would otherwise count the same purchases twice.
            Money sent to brokerages and online savings banks is a transfer too,
            in category "Savings & Investing", so it counts as saved, not spent.

Inside an investing or retirement account nothing is income or spending either. Money
paid in or taken out is a contribution or a withdrawal, and the rest (dividends, trades,
fees) is "Investment Activity": what makes the balance grow beyond what was paid in.
"""
from __future__ import annotations

import bisect
import calendar
import functools
import itertools
import json
import re
import statistics
from collections import Counter, defaultdict
from datetime import date, timedelta
from pathlib import Path

from .accounts import INVESTED, OWED
from .rules import read as read_rules
from .storage import read_text

# Tried in order against the upper-cased description; first hit wins.
DEFAULT_RULES = [
    (r"VENMO CASHOUT", "Income", "Venmo Cashout"),
    (r"VENMO", "Person to Person", "Venmo"),
    (r"ZELLE", "Person to Person", "Zelle"),
    (r"CASH ?APP", "Person to Person", "Cash App"),
    (r"ATM DEPOSIT|MOBILE DEPOSIT", "Uncategorized", "Deposit"),
    (r"PAYROLL|DIRECT DEP|DIR DEP|SALARY|PAYCHECK|GUSTO|\bADP\b", "Income", None),
    (r"\bINT PMT\b", "Income", "Interest"),
    (r"INTEREST (PAID|PAYMENT|EARNED)|DIVIDEND|CASH ?BACK REWARD|REWARD POINTS REDEMPTION|TAX REFUND|IRS TREAS", "Income", None),
    (r"INTEREST CHARGE|LATE FEE|ANNUAL (MEMBERSHIP )?FEE|OVERDRAFT|MONTHLY (SERVICE|MAINTENANCE) FEE|ATM FEE|FOREIGN TRANSACTION|INTERNATIONAL TRANS FEE", "Fees", None),
    (r"RENT-?A-?CAR|HERTZ|\bAVIS\b", "Transport", None),
    (r"\bRENT\b|MORTGAGE|\bMTG\b|\bHOA\b|LOAN SERVIC|ROCKET MORT|PROPERTY (MGMT|MANAGEMENT)", "Housing", None),
    (r"APPFOLIO", "Housing", "AppFolio"),
    (r"CENTURY 21", "Housing", "Century 21"),
    (r"ELECTRIC|\bPOWER\b|ENERGY|\bWATER\b|\bGAS CO|UTILIT|COMCAST|XFINITY|SPECTRUM|VERIZON|AT&T|\bATT\b|T-MOBILE|TMOBILE|INTERNET|WASTE", "Utilities", None),
    (r"USAA P&C|USAA INS", "Insurance", "USAA Insurance"),
    (r"STATE FARM", "Insurance", "State Farm"),
    (r"GEICO|PROGRESSIVE|ALLSTATE|INSURANCE", "Insurance", None),
    (r"ANTHROPIC|CLAUDE\.AI", "Subscriptions", "Claude"),
    (r"NETFLIX", "Subscriptions", "Netflix"),
    (r"SPOTIFY", "Subscriptions", "Spotify"),
    (r"HULU", "Subscriptions", "Hulu"),
    (r"DISNEY ?\+|DISNEYPLUS", "Subscriptions", "Disney+"),
    (r"YOUTUBE ?PREMIUM|GOOGLE \*YOUTUBE", "Subscriptions", "YouTube Premium"),
    (r"APPLE\.COM/BILL|APPLE ONE|ICLOUD", "Subscriptions", "Apple"),
    (r"ADOBE", "Subscriptions", "Adobe"),
    (r"PATREON", "Subscriptions", "Patreon"),
    (r"AMAZON PRIME|PRIME VIDEO|AMZN PRIME", "Subscriptions", "Amazon Prime"),
    (r"PLANET FIT|\bGYM\b|FITNESS|PELOTON|EQUINOX", "Health", None),
    (r"KROGER FUEL", "Transport", "Kroger Fuel"),
    (r"COSTCO GAS", "Transport", "Costco Gas"),
    (r"WHOLE ?FOODS|WHOLEFDS|WFM\b", "Groceries", "Whole Foods"),
    (r"TRADER JOE", "Groceries", "Trader Joe's"),
    (r"KROGER", "Groceries", "Kroger"),
    (r"SAFEWAY", "Groceries", "Safeway"),
    (r"PUBLIX", "Groceries", "Publix"),
    (r"\bALDI\b", "Groceries", "Aldi"),
    (r"WEGMANS", "Groceries", "Wegmans"),
    (r"\bH-?E-?B\b", "Groceries", "H-E-B"),
    (r"COSTCO", "Groceries", "Costco"),
    (r"INSTACART", "Groceries", "Instacart"),
    (r"GROCER|SUPERMARKET|\bMARKET\b", "Groceries", None),
    (r"STARBUCKS", "Dining", "Starbucks"),
    (r"DUNKIN", "Dining", "Dunkin'"),
    (r"MCDONALD", "Dining", "McDonald's"),
    (r"CHIPOTLE", "Dining", "Chipotle"),
    (r"DOORDASH|DD \*", "Dining", "DoorDash"),
    (r"UBER ?EATS", "Dining", "Uber Eats"),
    (r"GRUBHUB", "Dining", "Grubhub"),
    (r"RESTAURANT|PIZZA|CAFE|COFFEE|TAQUERIA|GRILL|BAKERY|DINER|BURGER|SUSHI|^TST ?\*", "Dining", None),
    (r"\bSHELL\b|CHEVRON|EXXON|\bBP\b|TEXACO|SUNOCO|\bMOBIL\b|\bARCO\b|\bQT\b|WAWA|FUEL", "Transport", None),
    (r"UBER|LYFT", "Transport", None),
    (r"PARKING|\bTOLL\b|TRANSIT|\bMTA\b|\bMETRO\b|DMV|AUTOZONE|JIFFY LUBE", "Transport", None),
    (r"DELTA AIR|UNITED AIR|AMERICAN AIR|SOUTHWEST|JETBLUE|AIRLINES|AIRBNB|MARRIOTT|HILTON|HYATT|HOTEL|EXPEDIA", "Travel", None),
    (r"AMZN|AMAZON", "Shopping", "Amazon"),
    (r"TARGET", "Shopping", "Target"),
    (r"WAL-?MART|WM SUPERCENTER", "Shopping", "Walmart"),
    (r"BEST ?BUY", "Shopping", "Best Buy"),
    (r"HOME ?DEPOT", "Home", "Home Depot"),
    (r"\bLOWE'?S\b", "Home", "Lowe's"),
    (r"IKEA", "Home", "IKEA"),
    (r"CVS|WALGREENS|RITE ?AID|PHARMACY|DENTAL|DOCTOR|MEDICAL|HOSPITAL\b|CLINIC|OPTICAL", "Health", None),
    (r"STEAM ?GAMES|STEAMPOWERED", "Entertainment", "Steam"),
    (r"HOYOVERSE", "Entertainment", "HoYoverse"),
    (r"NINTENDO|PLAYSTATION|XBOX|CINEMA|AMC THEA|\bREGAL\b|TICKETMASTER", "Entertainment", None),
    (r"CHARITY|DONATION|RED CROSS|UNITED WAY", "Gifts & Donations", None),
    (r"TUITION|UNIVERSITY|COLLEGE|STUDENT LOAN|NAVIENT|NELNET", "Education", None),
    (r"\bATM\b.*WITHDRAW|CASH WITHDRAWAL", "Cash", None),
    (r"\bIRS\b|TAX PAYMENT|STATE TAX", "Taxes", None),
]

# When no rule hits, use the bank's own category if it maps onto ours.
# Checked in order, so "pet food" lands on Pets and "coffee" doesn't read as a fee.
BANK_CATEGORIES = [
    ("pet ", "Pets"), ("veterinar", "Pets"),
    ("grocer", "Groceries"), ("food", "Dining"), ("dining", "Dining"), ("restaurant", "Dining"),
    ("coffee", "Dining"), ("alcohol", "Dining"),
    ("gas", "Transport"), ("fuel", "Transport"), ("automotive", "Transport"), ("transport", "Transport"),
    ("rental car", "Transport"), ("taxi", "Transport"), ("parking", "Transport"), ("service & parts", "Transport"),
    ("travel", "Travel"), ("airfare", "Travel"), ("lodging", "Travel"),
    ("shopping", "Shopping"), ("merchandise", "Shopping"), ("clothing", "Shopping"),
    ("electronics", "Shopping"), ("sporting goods", "Shopping"), ("books", "Shopping"), ("hobbies", "Shopping"),
    ("entertainment", "Entertainment"), ("movies", "Entertainment"), ("music", "Entertainment"),
    ("sports", "Entertainment"),
    ("health", "Health"), ("medical", "Health"), ("pharmacy", "Health"),
    ("hair", "Personal Care"), ("laundry", "Personal Care"),
    ("bills", "Utilities"), ("utilit", "Utilities"),
    ("home", "Home"), ("taxes", "Taxes"), ("fee", "Fees"), ("education", "Education"),
    ("gift", "Gifts & Donations"), ("donation", "Gifts & Donations"), ("insurance", "Insurance"),
]

EDITS_FILE = "edits.json"
CARD_PAYMENT = "Card payment"  # banks word these so many ways that the words say nothing
UNCATEGORIZED = "Uncategorized"
SAVED = "Savings & Investing"
ESTIMATED = "Card Payments (no detail)"
CONTRIBUTED, WITHDRAWN, ACTIVITY = "Contributions", "Withdrawals", "Investment Activity"
INVESTING_CATEGORIES = (CONTRIBUTED, WITHDRAWN, ACTIVITY)
SPENDING_KINDS = ("expense", "refund", "estimate")
TRANSFER_CATEGORIES = ("Transfer", SAVED, *INVESTING_CATEGORIES)
INTEREST = "Interest"  # what a loan charges, which is spending; what's paid off it is not
LOAN_PAYMENT = "Loan payment"
NOT_BUDGETED = ("Income", "Transfer", SAVED, ESTIMATED, UNCATEGORIZED, *INVESTING_CATEGORIES)
INCOME_MONTHS = 3  # complete months averaged to stand in for a month still in progress
_SAVED_AT = [
    (r"ROBINHOOD", "Robinhood"), (r"VANGUARD", "Vanguard"), (r"BETTERMENT", "Betterment"),
    (r"WEALTHFRONT", "Wealthfront"), (r"E\*TRADE", "E*TRADE"), (r"ACORNS", "Acorns"),
    (r"FIDELITY", "Fidelity"), (r"SCHWAB", "Schwab"), (r"MERRILL EDGE", "Merrill Edge"),
    # Bank wording only: "SYNCHRONY BANK PAYMENT" is a store card, not savings.
    (r"SYNCHRONY BANK (TRANSFER|P2P)", "Synchrony Bank"), (r"ALLY BANK", "Ally Bank"),
    (r"MARCUS BY GOLDMAN", "Marcus"), (r"SOFI BANK", "SoFi"),
]
_NOT_TRANSFER = re.compile(r"ZELLE|VENMO|CASH ?APP|PAYPAL|\bFEE\b")
# In an investing account: what the market and the account do, before what's paid in or out,
# since "DIVIDEND DEPOSIT" is a dividend. What matches neither counts as activity.
_ACTIVITY = re.compile(r"DIVIDEND|REINVEST|INTEREST|CAPITAL GAIN|\b(BOUGHT|SOLD|BUY|SELL|BUYS|SELLS)\b|\bFEES?\b|SPLIT|"
                       r"REDEMPTION|EXCHANGE|MERGER|SPINOFF|ADVISORY|MGMT|MANAGEMENT|EXPENSE RATIO")
_MOVED = re.compile(r"CONTRIBUT|DEPOSIT|TRANSFER|\bXFER\b|\bTFR\b|\bACH\b|\bEFT\b|ROLLOVER|EMPLOYER|\bMATCH|PAYROLL|"
                    r"\bWIRE\b|WITHDRAW|DISTRIBUTION|ELECTRONIC FUNDS|MONEYLINK|FUNDS (IN|OUT)|FROM (CHECKING|SAVINGS)|"
                    r"TO (CHECKING|SAVINGS)|PAYMENT FROM|DIRECT DEP")
PAIR_DAYS = 7  # the slowest real payment seen took 5; a miss would count purchases twice
ISSUER_WORDS = {"American Express": r"AMEX|AMERICAN EXPRESS", "Bank of America": r"BANK OF AMERICA|BK OF AM"}
_LOAN = re.compile(r"MORTGAGE|MTG|HOME LOAN|AUTO LOAN|CAR LOAN|STUDENT LOAN|LOAN PMT|LOAN PAYMENT")
# A bank-side payment that could be to a loan, for pairing with the loan's own side.
_TO_LOAN = re.compile(r"MORTGAGE|\bMTG\b|\bLOAN\b|\bLN\b|HELOC|NAVIENT|NELNET|MOHELA|AIDVANTAGE|FEDLOAN|GREAT LAKES|"
                      r"SALLIE MAE|AUTO ?(FINANCE|FINANCIAL|PAY)|MOTOR (CREDIT|ACCEPTANCE)|FINANCIAL SERVICES|LENDING")
_LOAN_INTEREST = re.compile(r"INTEREST|\bINT\b|FINANCE CHARGE")
_ISSUER = (r"\b(CHASE|CITI|AMEX|AMERICAN EXPRESS|CAPITAL ONE|DISCOVER|BARCLAY|SYNCHRONY|"
           r"BANK OF AMERICA|BK OF AM|WELLS FARGO|APPLE CARD|GOLDMAN SACHS)\b")
_CARD_PAYMENT = re.compile(rf"CREDIT ?(CARD|CRD)|CRCARDPMT|CARD ?(PAYMENT|PMT)|\bCC (PAYMENT|PMT)\b|"
                           rf"({_ISSUER}).*(CARD|CRD|PMT|PAYMENT|EPAY|AUTOPAY|E-PAYMENT)")
_OWN_TRANSFER = re.compile(r"\bTRANSFER\b|\bXFER\b|\bTFR\b|(TO|FROM) (SAVINGS|CHECKING|SAV\b|CHK\b)")
_CARD_SIDE = re.compile(r"PAYMENT|AUTOPAY|THANK YOU|\bPYMT\b|\bPMT\b")

_PREFIXES = re.compile(
    r"^(WEB INITIATED PAYMENT AT|DEBIT CARD PURCHASE AT|EARLY PAY:|PURCHASE AUTHORIZED ON \d\d/\d\d|RECURRING PAYMENT( AUTHORIZED ON \d\d/\d\d)?|"
    r"POS (DEBIT|PURCHASE|WITHDRAWAL)?|DEBIT CARD PURCHASE|CHECKCARD( \d+)?|CHECK CARD|"
    r"ACH (DEBIT|CREDIT|WITHDRAWAL|DEPOSIT)?|PURCHASE|DEBIT|PAYPAL ?\*|PP ?\*|SQ ?\*|TST ?\*|SP ?\*|SP )\s*")
_CARD_TAIL = re.compile(r" CARD \d{4}$")  # Wells Fargo ends each purchase with the card's last 4
_STATES = set("AL AK AZ AR CA CO CT DE FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE "
              "NV NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY DC".split())

CADENCES = [  # name, days apart, tolerance, per month, minimum occurrences
    ("Weekly", 7, 2, 52 / 12, 4),
    ("Biweekly", 14, 3, 26 / 12, 4),
    ("Monthly", 30, 5, 1, 3),
    ("Quarterly", 91, 12, 1 / 3, 3),
    ("Annual", 365, 25, 1 / 12, 2),
]


def load_rules(path: Path) -> list[tuple]:
    compiled = []
    for rule in read_rules(path):
        try:
            pattern = re.compile(rule.pattern, re.I)
        except re.error:
            continue  # a typo in a hand-edited rule mustn't stop the app opening
        compiled.append((pattern, rule.category, rule.merchant or None))
    return compiled


def valid_edit(edit) -> bool:
    return (isinstance(edit, dict) and isinstance(edit.get("category"), str) and bool(edit["category"].strip())
            and isinstance(edit.get("merchant", ""), str))


def load_edits(path: Path) -> dict[str, dict]:
    """Single transactions changed by hand. A damaged file mustn't stop a report."""
    try:
        saved = json.loads(read_text(path)) if path.exists() else {}
    except ValueError:
        return {}
    return {k: e for k, e in saved.items() if valid_edit(e)} if isinstance(saved, dict) else {}


def edit_key(day, account: str, cents: int, description: str, n: int) -> str:
    """A name for one transaction that survives rebuilding its account from files, which
    a position wouldn't. n counts identical rows, so two $5 coffees stay two."""
    return f"{day}|{account}|{cents}|{' '.join(description.upper().split())}|{n}"


def edit_keys(rows: list[dict]) -> list[str]:
    seen: Counter = Counter()
    keys = []
    for r in rows:
        same = edit_key(r["date"], r["account"], r["cents"], r["description"], 0)
        keys.append(edit_key(r["date"], r["account"], r["cents"], r["description"], seen[same]))
        seen[same] += 1
    return keys


def category_names() -> list[str]:
    """Every category the built-in rules can produce, for the app's pick lists."""
    names = {c for _, c, _ in DEFAULT_RULES} | {c for _, c in BANK_CATEGORIES} | {INTEREST}
    return sorted(names - {UNCATEGORIZED})


@functools.lru_cache(maxsize=65536)  # the same few hundred merchants, over and over
def clean_merchant(description: str) -> str:
    text = description.upper()
    for _ in range(2):
        text = _PREFIXES.sub("", text).strip()
    text = _CARD_TAIL.sub("", text)
    text = re.split(r"[*#,]", text)[0] or text
    text = re.sub(r"\.COM\b", "", text)
    text = re.sub(r" (ON \d{6}|FROM CARD|WEB PMTS?|EPAY|DEBITS|PAYMENT|PMT|P2P|CC|CREDIT CRD|CREDIT CARD).*$", "", text)
    words = [w.strip(".,-'/") for w in text.split() if not re.search(r"\d|^X{3,}$", w)]
    words = [w for w in words if w and w not in ("STORE", "LLC", "INC", "THE", "FSB")]
    if len(words) > 1 and words[-1] in _STATES:
        words.pop()
    name = " ".join(words[:3]).replace("'", "").replace("-", " ")  # Cane's / Canes, Hiko-A-Mon
    return " ".join(name.split()).title() or description.strip().title()


def match_text(merchant: str, descriptions: list[str]) -> str:
    """Text for a new rule to look for, in the bank's own spelling so it really matches.

    The merchant's name if the bank uses it every time; otherwise the first description
    without what changes from one purchase to the next: the bank's wording around it, which
    can hold a date, and any store number or reference code.
    """
    texts = [d.upper() for d in descriptions]
    name = merchant.upper()
    if len(name) >= 3 and all(name in text for text in texts):
        return name
    text = _CARD_TAIL.sub("", texts[0])
    for _ in range(2):
        text = _PREFIXES.sub("", text).strip()
    kept = []
    for word in text.split():
        if kept and re.search(r"\d{3}|\d/\d|^#", word):
            break
        kept.append(word)
    found = " ".join(kept)
    return found if len(found) >= 3 else " ".join(texts[0].split())


def is_transfer(description: str, cents: int, account_type: str, bank_category: str = "") -> bool:
    text = description.upper()
    if _NOT_TRANSFER.search(text):
        return False
    if account_type == "credit":
        # USAA calls a payment just "USAA Credit Card"; only its category says so.
        return cents > 0 and bool(_CARD_SIDE.search(text) or _CARD_SIDE.search(bank_category.upper()))
    if _LOAN.search(text):
        return False
    if account_type == "savings" and re.search(r"\bP2P\b", text):
        return True  # Synchrony's wording for a move from your own linked bank
    return bool(_CARD_PAYMENT.search(text) or _OWN_TRANSFER.search(text))


def is_card_payment(text: str) -> bool:
    return bool(_CARD_PAYMENT.search(text.upper()))


def is_loan_payment(text: str) -> bool:
    return bool(_TO_LOAN.search(text.upper()))


def paid_cards(text: str, accounts: dict) -> list[str]:
    """Imported card accounts this bank-side payment description names."""
    found = []
    for account, info in accounts.items():
        bank = info.get("bank", "")
        if info["type"] == "credit" and bank and re.search(
                ISSUER_WORDS.get(bank, re.escape(bank.upper())), text.upper()):
            found.append(account)
    return found


def _bank_category(text: str) -> str | None:
    text = text.lower()
    return next((ours for needle, ours in BANK_CATEGORIES if needle in text), None)


def investing_category(text: str, positive: bool) -> str:
    """A row inside an investing or retirement account: paid in, taken out, or neither."""
    if _ACTIVITY.search(text) or not _MOVED.search(text):
        return ACTIVITY
    return CONTRIBUTED if positive else WITHDRAWN


def loan_category(text: str, positive: bool) -> tuple[str, str | None] | None:
    """A row inside a loan: a payment toward it, the interest it charges, or neither. Other
    charges, like an escrow payment of property tax, are left to the usual rules."""
    if positive:
        return "Transfer", LOAN_PAYMENT
    if _LOAN_INTEREST.search(text):
        return INTEREST, None
    return None


def _kind(category: str, cents: int, account_type: str) -> str:
    if category in TRANSFER_CATEGORIES:
        return "transfer"
    if cents < 0:
        return "expense"
    if category == "Income" or (category == UNCATEGORIZED and account_type not in OWED):
        return "income"
    return "refund"


def classify(rows: list[dict], accounts: dict, user_rules: list[tuple], edits: dict | None = None,
             splits: dict | None = None, keyed: bool = False) -> list[dict]:
    """A transaction changed by hand beats everything, then your rules, then what's built in.
    keyed: give every row its key even with no edits or splits, for notes to find them by."""
    keys = edit_keys(rows) if edits or splits or keyed else [""] * len(rows)
    default_rules = [(re.compile(p), c, m) for p, c, m in DEFAULT_RULES]
    saved_at = [(re.compile(p), SAVED, m) for p, m in _SAVED_AT]

    def match(text: str, positive: bool, account_type: str, bank_category: str) -> tuple:
        """(category, merchant or None, ruled), from the rules alone."""
        hit = next((rule for rule in user_rules if rule[0].search(text)), None)
        ruled = hit is not None
        if not hit and account_type in INVESTED:
            return investing_category(text, positive), None, False
        if not hit and account_type == "loan":
            found = loan_category(text, positive)
            if found:
                return found[0], found[1], False
        if not hit:
            hit = next((rule for rule in saved_at if rule[0].search(text)), None)
        if not hit and is_transfer(text, 1 if positive else -1, account_type, bank_category):
            hit = (None, "Transfer", CARD_PAYMENT if account_type == "credit" else None)
        if not hit:  # money out is never income, whatever the name: GUSTO'S PIZZA, a pay reversal
            hit = next((rule for rule in default_rules if rule[0].search(text)
                        and (rule[1] != "Income" or positive)), None)
        category = hit[1] if hit else (_bank_category(bank_category) or UNCATEGORIZED)
        return category, hit[2] if hit else None, ruled

    # A long history repeats the same descriptions again and again, and trying every rule
    # on each is most of the time a report takes, so each one is matched only once.
    matched: dict[tuple, tuple] = {}
    out = []
    for r, key in zip(rows, keys):
        account_type = accounts[r["account"]]["type"]
        text = r["description"].upper()
        edit = (edits or {}).get(key)
        if edit:
            category, named, ruled = edit["category"], edit.get("merchant") or None, True
        else:
            facts = (text, r["cents"] > 0, account_type, r["bank_category"])
            if facts not in matched:
                matched[facts] = match(*facts)
            category, named, ruled = matched[facts]
        merchant = named or clean_merchant(r["description"])
        out.append({
            "date": r["date"], "account": r["account"], "description": r["description"],
            "merchant": merchant, "category": category, "cents": r["cents"],
            "balance": r["balance"], "kind": _kind(category, r["cents"], account_type),
            "ruled": ruled, "edited": bool(edit), "matched": False, "source": r.get("source", ""), "key": key,
        })
    _pair_transfers(out, accounts)
    first_seen: dict[str, date] = {}
    for r in out:
        first_seen[r["account"]] = min(first_seen.get(r["account"], r["date"]), r["date"])
    for r in out:
        if (r["kind"] == "transfer" and not r["matched"] and not r["ruled"] and r["cents"] < 0
                and accounts[r["account"]]["type"] != "credit"
                and _CARD_PAYMENT.search(r["description"].upper())):
            # A payment more than a month into a card's history pays for purchases
            # already counted, so estimating it would count them twice.
            cards = paid_cards(r["description"], accounts)
            if not cards or any((r["date"] - first_seen[c]).days < 31 for c in cards if c in first_seen):
                r["kind"], r["category"] = "estimate", ESTIMATED
    return _split(out, accounts, splits) if splits else out


TAG_LONGEST, NOTE_LONGEST = 30, 500


def valid_note(note) -> bool:
    """Words about one transaction, and tags to gather it with others: a trip, a project."""
    return (isinstance(note, dict) and isinstance(note.get("note", ""), str) and len(note.get("note", "")) <= NOTE_LONGEST
            and isinstance(note.get("tags", []), list)
            and all(isinstance(t, str) and t.strip() and len(t) <= TAG_LONGEST for t in note.get("tags", []))
            and bool(note.get("note", "").strip() or note.get("tags")))


def read_tags(text: str) -> list[str]:
    """Tags as typed: separated by commas, with or without a #, in the spelling first used."""
    found: dict[str, str] = {}
    for part in text.split(","):
        tag = " ".join(part.strip().lstrip("#").split())[:TAG_LONGEST].strip()
        if tag:
            found.setdefault(tag.lower(), tag)
    return list(found.values())


def valid_split(split) -> bool:
    """Two or more parts, each with a category and an amount above zero, in cents."""
    parts = split.get("parts") if isinstance(split, dict) else None
    return (isinstance(parts, list) and len(parts) >= 2
            and all(isinstance(p, dict) and isinstance(p.get("category"), str) and p["category"].strip()
                    and type(p.get("cents")) is int and p["cents"] > 0 and isinstance(p.get("merchant", ""), str)
                    for p in parts))


def _split(rows: list[dict], accounts: dict, splits: dict) -> list[dict]:
    """A transaction split by hand stands as its parts, each with its own category, all on
    the same day and in the same direction. A split that no longer adds up to the amount,
    because the transaction changed since, is left out rather than guessed at."""
    out = []
    for r in rows:
        split = splits.get(r["key"])
        if not split or sum(p["cents"] for p in split["parts"]) != abs(r["cents"]):
            out.append(r)
            continue
        sign = 1 if r["cents"] > 0 else -1
        for part in split["parts"]:
            cents = sign * part["cents"]
            out.append({**r, "cents": cents, "category": part["category"].strip(),
                        "merchant": part.get("merchant", "").strip() or r["merchant"],
                        "kind": _kind(part["category"].strip(), cents, accounts[r["account"]]["type"]),
                        "edited": True, "split": True, "whole": r["cents"], "matched": False})
    return out


def _pair_transfers(rows: list[dict], accounts: dict) -> None:
    """Match each transfer with its other half.

    Only a row already recognized as a transfer can claim a partner, and the partner
    must be a transfer too or something unexplained. So a card payment can't swallow
    a same-sized rent payment or paycheck, and a $20 refund can't pair off with an
    unrelated $20 purchase.

    A payment into a loan is the exception: the bank's side is usually filed as Housing or
    Education by its name, so it may claim any payment out of a bank account worded like
    one to a lender. Paired, it's a transfer, and only the loan's interest is spending.
    """
    by_amount = defaultdict(list)
    for r in rows:
        by_amount[r["cents"]].append(r)

    def could_be(c: dict, r: dict) -> bool:
        if c["category"] in (*TRANSFER_CATEGORIES, UNCATEGORIZED):
            return c["category"] != ACTIVITY
        return (accounts[r["account"]]["type"] == "loan" and c["cents"] < 0 and not c["edited"]
                and accounts[c["account"]]["type"] not in (*OWED, *INVESTED) and _lender(c["description"], accounts[r["account"]]))

    for r in rows:
        if r["kind"] != "transfer" or r["matched"] or r["category"] == ACTIVITY:
            continue
        candidates = [c for c in by_amount[-r["cents"]]
                      if c["account"] != r["account"] and not c["matched"] and not c["ruled"] and could_be(c, r)
                      and abs((c["date"] - r["date"]).days) <= PAIR_DAYS]
        if candidates:
            other = min(candidates, key=lambda c: (c["kind"] != "transfer",
                                                   abs((c["date"] - r["date"]).days)))
            r["matched"] = other["matched"] = True
            other["kind"] = "transfer"
            # Both halves imported: it's now one internal move, so the savings
            # account's side alone reports it and it isn't counted as saved twice.
            # An investing account's side stays a contribution or withdrawal.
            for half in (r, other):
                if accounts[half["account"]]["type"] not in INVESTED:
                    half["category"] = "Transfer"


def _lender(description: str, loan: dict) -> bool:
    """Whether a payment's wording could be one to this loan: a lender's words, or its bank's name."""
    text = description.upper()
    bank = (loan.get("bank") or "").upper().strip()
    return bool(_TO_LOAN.search(text) or (len(bank) >= 3 and bank in text))


MONTHS_APART = {"Monthly": 1, "Quarterly": 3, "Annual": 12}


def add_months(day: date, months: int, keep: int) -> date:
    """The same day of the month, months on: the 31st becomes the 30th in a 30-day month."""
    year, month = divmod(day.month - 1 + months, 12)
    year, month = day.year + year, month + 1
    return date(year, month, min(keep, calendar.monthrange(year, month)[1]))


def due_after(last: date, cadence: str, n: int = 1) -> date:
    """The nth time a payment is due after the last one. A monthly bill keeps its day of the
    month, where 30 days on would drift a day or two each time."""
    months = MONTHS_APART.get(cadence)
    if months:
        return add_months(last, months * n, last.day)
    return last + timedelta(days={"Weekly": 7, "Biweekly": 14}.get(cadence, 30) * n)


def _cadence(days: list[date]) -> tuple | None:
    gaps = [(b - a).days for a, b in zip(days, days[1:])]
    if not gaps:
        return None
    for cadence in CADENCES:
        _, span, tolerance, _, minimum = cadence
        if len(days) >= minimum:
            on_beat = sum(1 for g in gaps if abs(g - span) <= tolerance)
            if on_beat / len(gaps) >= 0.8:
                return cadence
    return None


def _amount_clusters(rows: list[dict]) -> list[list[dict]]:
    clusters: list[list[dict]] = []
    for r in sorted(rows, key=lambda x: abs(x["cents"])):
        if clusters:
            anchor = abs(clusters[-1][0]["cents"])
            if abs(r["cents"]) - anchor <= max(anchor * 0.15, 100):
                clusters[-1].append(r)
                continue
        clusters.append([r])
    return clusters


def _recurring_entry(group: list[dict], cadence: tuple, last_seen: dict) -> dict:
    name, span, tolerance, per_month, _ = cadence
    group = sorted(group, key=lambda r: r["date"])
    amounts = [abs(r["cents"]) for r in group]
    latest = group[-1]
    median = statistics.median(amounts)
    typical = amounts[-1] if name in ("Quarterly", "Annual") else statistics.median(amounts[-3:])
    # A price rise is one step; a variable bill moves nearly every time.
    moves = sum(abs(b - a) > 0.01 * median for a, b in zip(amounts, amounts[1:]))
    variable = moves > max(1, (len(amounts) - 1) // 3)
    previous = amounts[-2]
    return {
        "merchant": latest["merchant"], "category": latest["category"],
        "kind": latest["kind"], "cadence": name, "count": len(group),
        "amount": typical / 100, "per_month": typical * per_month / 100,
        "low": min(amounts) / 100, "high": max(amounts) / 100,
        "first": group[0]["date"].isoformat(), "last": latest["date"].isoformat(),
        "next": due_after(latest["date"], name).isoformat(),
        "active": (last_seen[latest["account"]] - latest["date"]).days <= span * 1.5 + tolerance,
        "variable": variable,
        "price_change": (amounts[-1] - previous) / 100
        if not variable and amounts[-1] != previous else 0,
        "account": latest["account"],
    }


def _steady(rows: list[dict]) -> bool:
    """Picked out of a merchant's other purchases, a pattern needs a fixed price (one
    rise allowed), or any two similar shopping trips a year apart look like a bill."""
    amounts = [r["cents"] for r in rows]
    changes = sum(a != b for a, b in zip(amounts, amounts[1:]))
    return changes == 0 or (changes == 1 and len(amounts) > 3)


def _follow_to_new_card(entry: dict, cadence: tuple, merchant_rows: list[dict], last_seen: dict) -> None:
    """A bill that vanishes from one card while the merchant still charges another has
    moved, not stopped, even if the new card's short export misses the usual day."""
    if entry["active"]:
        return
    name, span, tolerance, _, _ = cadence
    ended = date.fromisoformat(entry["last"])
    later = [r for r in merchant_rows if r["account"] != entry["account"] and r["date"] > ended
             and (last_seen[r["account"]] - r["date"]).days <= span * 1.5 + tolerance]
    if later:
        card = later[-1]["account"]
        n = 1
        while due_after(ended, name, n) <= last_seen[card]:
            n += 1
        upcoming = due_after(ended, name, n)
        entry.update(active=True, account=card, next=upcoming.isoformat())


def find_recurring(rows: list[dict]) -> list[dict]:
    last_seen: dict[str, date] = {}
    groups = defaultdict(list)
    for r in rows:
        last_seen[r["account"]] = max(last_seen.get(r["account"], r["date"]), r["date"])
        if r["kind"] in ("expense", "income"):
            groups[(r["merchant"], r["kind"])].append(r)

    found = []
    for group in groups.values():
        group.sort(key=lambda r: r["date"])
        # Bills that vary (electric) are regular as a whole; a shop with a steady
        # $9.99 subscription among random purchases only shows up by amount.
        cadence = _cadence([r["date"] for r in group]) if len(group) >= 4 else None
        if cadence and cadence[0] not in ("Quarterly", "Annual"):
            found.append(_recurring_entry(group, cadence, last_seen))
            continue
        for cluster in _amount_clusters(group):
            ordered = sorted(cluster, key=lambda r: r["date"])
            cadence = _cadence([r["date"] for r in ordered])
            if cadence and (len(ordered) == len(group) or _steady(ordered)):
                entry = _recurring_entry(ordered, cadence, last_seen)
                _follow_to_new_card(entry, cadence, group, last_seen)
                found.append(entry)
    found.sort(key=lambda e: (not e["active"], e["kind"] == "income", -e["per_month"]))
    return found


@functools.lru_cache(maxsize=65536)  # one for each day there's data, used for every row
def month_of(day: date) -> str:
    """2026-03 for a day in March 2026."""
    return f"{day.year:04d}-{day.month:02d}"


def monthly_summary(rows: list[dict]) -> list[dict]:
    months: dict[str, dict] = {}
    for r in rows:
        month = month_of(r["date"])
        m = months.setdefault(month, {
            "month": month, "income": 0, "spending": 0, "categories": defaultdict(int)})
        if r["kind"] == "income":
            m["income"] += r["cents"]
        elif r["kind"] in SPENDING_KINDS:
            m["spending"] -= r["cents"]
            m["categories"][r["category"]] -= r["cents"]
    return [months[k] for k in sorted(months)]


def _month_ends(first: date, last: date):
    year, month = first.year, first.month
    while (year, month) <= (last.year, last.month):
        yield f"{year}-{month:02d}", min(date(year, month, calendar.monthrange(year, month)[1]), last)
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)


def _calculated(own: list[dict], info: dict) -> dict:
    """Walk an entered balance forward and back through the account's transactions.

    Entered as a card's or loan's amount owed, so it's flipped: a card balance is negative,
    which lets the same sum work for purchases and payments on any account."""
    anchor = info["balance_anchor"]
    pinned = date.fromisoformat(anchor["date"])
    start = round(anchor["amount"] * 100) * (-1 if info["type"] in OWED else 1)
    if not own:  # a linked account that's been quiet still has a balance
        return {"months": {anchor["date"][:7]: start}, "current": start, "as_of": anchor["date"], "calculated": True}

    days = [r["date"] for r in own]  # own is in date order
    totals = list(itertools.accumulate((r["cents"] for r in own), initial=0))

    def through(day: date) -> int:
        """Every transaction up to and including day, added up."""
        return totals[bisect.bisect_right(days, day)]

    def on(day: date) -> int:  # what came after the pinned day is added, what came before it undone
        return start + through(day) - through(pinned)

    last = max(pinned, own[-1]["date"])
    return {"months": {m: on(end) for m, end in _month_ends(own[0]["date"], last)},
            "current": on(last), "as_of": last.isoformat(), "calculated": True}


def balance_points(own: list[dict], info: dict) -> list[tuple[date, int]]:
    """Every balance an investing account is known to have had, by day: each one the bank
    sent when syncing, any entered by hand, and any in an export's balance column."""
    found: dict[date, int] = {}
    for r in own:  # in date order, so the last row of a day is that day's close
        if r["balance"] is not None:
            found[r["date"]] = r["balance"]
    entered = [*info.get("balance_history", []), *([info["balance_anchor"]] if info.get("balance_anchor") else [])]
    for point in entered:
        try:
            found[date.fromisoformat(point["date"])] = round(point["amount"] * 100)
        except (KeyError, TypeError, ValueError):
            continue  # a hand-edited file mustn't stop the report
    return sorted(found.items())


def _invested(own: list[dict], info: dict, last_day: date | None) -> dict | None:
    """Markets move an investing account's balance without a transaction, so it can't be
    worked out from one entered balance. Each month shows the last balance known by then."""
    points = balance_points(own, info)
    if not points:
        return None
    months, at = {}, 0
    end = max(points[-1][0], last_day or points[-1][0])
    for month, month_end in _month_ends(points[0][0], end):
        while at < len(points) and points[at][0] <= month_end:
            at += 1
        months[month] = points[at - 1][1]
    day, current = points[-1]
    return {"months": months, "current": current, "as_of": day.isoformat(), "calculated": False,
            "points": [(d.isoformat(), c) for d, c in points]}


def account_balances(rows: list[dict], accounts: dict) -> dict[str, dict]:
    """Each account's latest and month-end balances, by the best source it has: the
    export's own balance column, or else a balance the person entered."""
    exported = month_end_balances(rows)
    last_day = max((r["date"] for r in rows), default=None)
    found = {}
    for account, info in accounts.items():
        own = sorted((r for r in rows if r["account"] == account), key=lambda r: r["date"])
        if info["type"] in INVESTED:
            balance = _invested(own, info, last_day)
            if balance:
                found[account] = {**balance, "live": bool(info.get("balance_anchor", {}).get("live"))}
        elif info.get("balance_anchor", {}).get("live"):
            found[account] = {**_calculated(own, info), "live": True}  # the bank's figure beats an old export
        elif account in exported:
            with_balance = [r for r in own if r["balance"] is not None]
            found[account] = {"months": exported[account], "current": with_balance[-1]["balance"],
                              "as_of": with_balance[-1]["date"].isoformat(), "calculated": False}
        elif own and info.get("balance_anchor"):
            found[account] = _calculated(own, info)
        if info["type"] == "loan" and account in found:  # what's owed, however the bank signed it
            b = found[account]
            found[account] = {**b, "current": -abs(b["current"]), "months": {m: -abs(c) for m, c in b["months"].items()}}
    return found


def coverage_start(rows: list[dict], accounts: dict) -> str | None:
    """First month with checking history. Rent and most bills live there, so a month
    before it shows only card spending and would drag every average down."""
    months = [month_of(r["date"]) for r in rows if accounts[r["account"]]["type"] == "checking"]
    return min(months, default=None)


def partial_month(end: date) -> str | None:
    """The month still in progress, judged by the newest transaction."""
    return end.strftime("%Y-%m") if end.day < 26 else None


def budget_report(rows: list[dict], accounts: dict, budgets: dict[str, dict]) -> dict:
    """Spending against each target, by month. A percent target follows that month's
    income, except in the month in progress, where pay may not have landed yet: that
    one uses recent income, or it would read as over budget until payday."""
    targets = [{"category": c, "mode": b["mode"], "value": b["value"] / 100 if b["mode"] == "amount" else b["value"],
                "rollover": bool(b.get("rollover")), "since": b.get("since")}
               for c, b in sorted(budgets.items())]
    if not rows:
        return {"targets": targets, "months": []}
    summary = {m["month"]: m for m in monthly_summary(rows)}
    start = coverage_start(rows, accounts) or ""
    dates = [r["date"] for r in rows]
    months = [m for m, _ in _month_ends(min(dates), max(dates)) if m >= start]
    partial = partial_month(max(dates))
    income = {m: summary[m]["income"] if m in summary else 0 for m in months}
    recent = [income[m] for m in months if m != partial][-INCOME_MONTHS:]

    report = []
    for month in months:
        base = sum(recent) // len(recent) if month == partial and recent else income[month]
        spent = summary[month]["categories"] if month in summary else {}
        report.append({
            "month": month, "partial": month == partial, "income": income[month] / 100, "base": base / 100,
            "spent": {c: cents / 100 for c, cents in spent.items()},
            "targets": {c: (b["value"] if b["mode"] == "amount" else round(base * b["value"] / 100)) / 100
                        for c, b in budgets.items()},
        })
    return {"targets": targets, "months": report}


def month_end_balances(rows: list[dict]) -> dict[str, dict[str, int]]:
    balances: dict[str, dict[str, int]] = defaultdict(dict)
    for r in sorted(rows, key=lambda r: r["date"]):  # stable: last row of a month is the close
        if r["balance"] is not None:
            balances[r["account"]][month_of(r["date"])] = r["balance"]
    return dict(balances)


def coverage_gaps(imports: list[dict]) -> dict[str, list[tuple[date, date]]]:
    """Stretches of an account's history no import has covered."""
    spans = defaultdict(list)
    for i in imports:
        spans[i["account"]].append((date.fromisoformat(i["first"]), date.fromisoformat(i["last"])))
    gaps = defaultdict(list)
    for account, ranges in spans.items():
        ranges.sort()
        reach = ranges[0][1]
        for start, end in ranges[1:]:
            if (start - reach).days > 14:  # quiet cards can legitimately skip a week or two
                gaps[account].append((reach, start))
            reach = max(reach, end)
    return dict(gaps)


def _dollars(cents: int) -> str:
    return f"${abs(cents) / 100:,.2f}"


def _duplicate_checks(rows: list[dict], accounts: dict) -> list[dict]:
    """What merging can't catch, because the rows don't compare as equal."""
    found = []
    # One account imported under two numbers: same rows, separate accounts.
    keys = defaultdict(set)
    for r in rows:
        keys[r["account"]].add((r["date"], r["cents"], r["description"].upper()))
    names = sorted(keys)
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            shared = len(keys[a] & keys[b])
            if shared >= 5 and shared >= 0.3 * min(len(keys[a]), len(keys[b])):
                found.append({"level": "warning", "title": "Same transactions on two accounts",
                              "detail": f"{accounts[a]['name']} and {accounts[b]['name']} share "
                                        f"{shared} identical rows, so they may be one account "
                                        "imported under two numbers. That would double count them."})
    # A bank rewording or redating a row between two exports.
    by_amount = defaultdict(list)
    for r in rows:
        if r["kind"] == "expense" and abs(r["cents"]) >= 500:
            by_amount[(r["account"], r["cents"])].append(r)
    suspects = []
    for group in by_amount.values():
        group.sort(key=lambda r: r["date"])
        suspects += [b for a, b in zip(group, group[1:])
                     if a["source"] != b["source"] and (b["date"] - a["date"]).days <= 4]
    if suspects:
        total = sum(r["cents"] for r in suspects)
        examples = ", ".join(f"{r['merchant']} on {r['date']}" for r in suspects[:3])
        found.append({"level": "warning", "title": "Possible duplicates between exports",
                      "detail": f"{len(suspects)} rows ({_dollars(total)}) match another row's amount "
                                f"within 4 days but came from a different file, e.g. {examples}. "
                                "A bank may have reworded them after posting; look them up in "
                                "Transactions."})
    return found


def _first_dates(rows: list[dict]) -> dict[str, date]:
    first: dict[str, date] = {}
    for r in rows:
        first[r["account"]] = min(first.get(r["account"], r["date"]), r["date"])
    return first


def _gap_checks(accounts: dict, imports: list[dict]) -> list[dict]:
    found = []
    for account, gaps in coverage_gaps(imports).items():
        for start, end in gaps:
            found.append({"level": "warning", "title": f"Missing history: {accounts[account]['name']}",
                          "detail": f"Nothing imported from {start} to {end}. Export that "
                                    "period and drop it in the inbox."})
    return found


def _unmatched_checks(rows: list[dict], accounts: dict) -> list[dict]:
    """Money that left a bank account for somewhere we can't see."""
    found = []
    unmatched = [r for r in rows if (r["category"] == "Transfer" or r["kind"] == "estimate")
                 and not r["matched"] and r["cents"] < 0 and accounts[r["account"]]["type"] not in OWED]

    # A payment dated before a card's history starts isn't a mystery, just a short export.
    first_by_account = _first_dates(rows)
    too_early = defaultdict(list)
    earlier_than_history = []
    missing_from_card = []
    for r in unmatched:
        text = r["description"].upper()
        cards = paid_cards(text, accounts)
        early_card = next((c for c in cards if r["date"] < first_by_account.get(c, r["date"])), None)
        if early_card:
            too_early[early_card].append(r)
            earlier_than_history.append(r)
        elif r["kind"] == "transfer" and cards:
            missing_from_card.append(r)
        elif any(info.get("bank") and info["bank"].upper() in text and a != r["account"]
                 and info["type"] != "credit" and r["date"] < first_by_account.get(a, r["date"])
                 for a, info in accounts.items()):
            earlier_than_history.append(r)  # hides no purchases; the income warning covers it
    for account, payments in too_early.items():
        total = _dollars(sum(r["cents"] for r in payments))
        found.append({"level": "warning", "title": f"Export more history: {accounts[account]['name']}",
                      "detail": f"This card's history starts {first_by_account[account]}, but "
                                f"{len(payments)} earlier payments ({total}) went to it. Those "
                                "payments count as estimated spending until you import the "
                                "purchases behind them."})
    if missing_from_card:
        found.append({"level": "warning", "title": "Card payments not found on the card",
                      "detail": f"{len(missing_from_card)} payment(s) totalling "
                                f"{_dollars(sum(r['cents'] for r in missing_from_card))} left your bank "
                                "but aren't on the imported card. They're left out of spending, "
                                "because that card's purchases already count. Check for a second "
                                "card or a gap in that card's export."})
    claimed = {id(r) for r in earlier_than_history + missing_from_card}
    unmatched = [r for r in unmatched if id(r) not in claimed]
    if unmatched:
        by_merchant = defaultdict(int)
        for r in unmatched:
            by_merchant[r["merchant"]] += r["cents"]
        top = sorted(by_merchant.items(), key=lambda kv: kv[1])[:3]
        names = ", ".join(f"{name} ({_dollars(c)})" for name, c in top)
        count = f"{len(unmatched)} payment{'s' if len(unmatched) != 1 else ''}"
        found.append({"level": "warning", "title": "Transfers out with no matching account",
                      "detail": f"{count} totalling "
                                f"{_dollars(sum(r['cents'] for r in unmatched))} went somewhere "
                                f"not imported: {names}. Card payments here count as estimated "
                                "spending until that card's purchases are imported."})
    return found


def _uncategorized_check(rows: list[dict]) -> list[dict]:
    spending = [r for r in rows if r["kind"] == "expense"]
    loose = [r for r in spending if r["category"] == UNCATEGORIZED]
    if not spending or not loose:
        return []
    share = sum(r["cents"] for r in loose) / sum(r["cents"] for r in spending)
    if share < 0.01:
        return []
    by_merchant = defaultdict(int)
    for r in loose:
        by_merchant[r["merchant"]] += r["cents"]
    top = ", ".join(k for k, _ in sorted(by_merchant.items(), key=lambda kv: kv[1])[:5])
    return [{"level": "info", "title": f"{share:.0%} of spending is uncategorized",
             "detail": f"Biggest: {top}. Add a line to rules.csv to sort these."}]


def _income_history_check(rows: list[dict], accounts: dict) -> list[dict]:
    """Card spending with no income beside it makes those months look badly overspent."""
    first_by_account = _first_dates(rows)
    deposits = [d for a, d in first_by_account.items() if accounts[a]["type"] == "checking"]
    cards = [d for a, d in first_by_account.items() if accounts[a]["type"] == "credit"]
    if not deposits or not cards or (min(deposits) - min(cards)).days <= 45:
        return []
    return [{"level": "warning", "title": "Income history is shorter than card history",
             "detail": f"Cards go back to {min(cards)} but checking only to {min(deposits)}. Months "
                       "before that show spending with no income, so judge savings from later "
                       "months, or import the earlier bank history."}]


def _account_checks(rows: list[dict], accounts: dict) -> list[dict]:
    found = []
    latest = max((r["date"] for r in rows), default=None)
    last_by_account = {}
    for r in rows:
        last_by_account[r["account"]] = max(last_by_account.get(r["account"], r["date"]), r["date"])
    for account, last in last_by_account.items():
        if latest and (latest - last).days > 45:
            found.append({"level": "warning", "title": f"Out of date: {accounts[account]['name']}",
                          "detail": f"Last transaction is {last}, but other accounts run to "
                                    f"{latest}. Recent months undercount spending."})
    balances = account_balances(rows, accounts)
    for account, info in accounts.items():
        if info["type"] in OWED and account not in balances and account in last_by_account:
            found.append({"level": "info", "title": f"No balance yet: {info['name']}",
                          "detail": "Its export doesn't include one. Add it with Edit in the "
                                    "Accounts list."})
    for info in accounts.values():
        if info.get("sign_guessed") and info.get("invert_sign"):
            found.append({"level": "info", "title": f"Check signs: {info['name']}",
                          "detail": "Amounts looked like purchases were positive, so they were "
                                    "flipped. If that's wrong, set invert_sign to false in "
                                    "accounts.json and rerun."})
        if info.get("recovered"):
            found.append({"level": "warning", "title": f"Check this account: {info['name']}",
                          "detail": "Its transactions were kept, but its details were lost. Set its "
                                    "name and type with Edit in the Accounts list."})
    return found


def checks(rows: list[dict], accounts: dict, imports: list[dict]) -> list[dict]:
    """Things that would make the numbers wrong, worded as what to do about them."""
    return (_gap_checks(accounts, imports) + _unmatched_checks(rows, accounts) + _uncategorized_check(rows)
            + _income_history_check(rows, accounts) + _duplicate_checks(rows, accounts)
            + _account_checks(rows, accounts))
