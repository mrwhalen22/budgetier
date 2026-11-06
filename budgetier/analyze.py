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
"""
from __future__ import annotations

import calendar
import csv
import re
import statistics
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

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

UNCATEGORIZED = "Uncategorized"
SAVED = "Savings & Investing"
ESTIMATED = "Card Payments (no detail)"
SPENDING_KINDS = ("expense", "refund", "estimate")
TRANSFER_CATEGORIES = ("Transfer", SAVED)
NOT_BUDGETED = ("Income", "Transfer", SAVED, ESTIMATED, UNCATEGORIZED)
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
PAIR_DAYS = 7  # the slowest real payment seen took 5; a miss would count purchases twice
ISSUER_WORDS = {"American Express": r"AMEX|AMERICAN EXPRESS", "Bank of America": r"BANK OF AMERICA|BK OF AM"}
_LOAN = re.compile(r"MORTGAGE|MTG|HOME LOAN|AUTO LOAN|CAR LOAN|STUDENT LOAN|LOAN PMT|LOAN PAYMENT")
_ISSUER = (r"\b(CHASE|CITI|AMEX|AMERICAN EXPRESS|CAPITAL ONE|DISCOVER|BARCLAY|SYNCHRONY|"
           r"BANK OF AMERICA|BK OF AM|WELLS FARGO|APPLE CARD|GOLDMAN SACHS)\b")
_CARD_PAYMENT = re.compile(rf"CREDIT ?(CARD|CRD)|CRCARDPMT|CARD ?(PAYMENT|PMT)|\bCC (PAYMENT|PMT)\b|"
                           rf"({_ISSUER}).*(CARD|CRD|PMT|PAYMENT|EPAY|AUTOPAY|E-PAYMENT)")
_OWN_TRANSFER = re.compile(r"\bTRANSFER\b|\bXFER\b|\bTFR\b|(TO|FROM) (SAVINGS|CHECKING|SAV\b|CHK\b)")
_CARD_SIDE = re.compile(r"PAYMENT|AUTOPAY|THANK YOU|\bPYMT\b|\bPMT\b")

_PREFIXES = re.compile(
    r"^(WEB INITIATED PAYMENT AT|DEBIT CARD PURCHASE AT|EARLY PAY:|PURCHASE AUTHORIZED ON \d\d/\d\d|RECURRING PAYMENT( AUTHORIZED ON \d\d/\d\d)?|"
    r"POS (DEBIT|PURCHASE|WITHDRAWAL)?|DEBIT CARD PURCHASE|CHECKCARD( \d+)?|CHECK CARD|"
    r"ACH (DEBIT|CREDIT|WITHDRAWAL|DEPOSIT)?|PURCHASE|DEBIT|PAYPAL ?\*|PP ?\*|SQ ?\*|TST ?\*|SP )\s*")
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
    if not path.exists():
        return []
    rules = []
    with path.open(newline="", encoding="utf-8") as f:
        for row in csv.reader(f):
            if not row or row[0].lstrip().startswith("#") or row[0].strip().lower() == "match":
                continue
            if len(row) < 2 or not row[1].strip():
                continue
            try:
                pattern = re.compile(row[0].strip(), re.I)
            except re.error:
                continue  # a typo in a hand-edited rule mustn't stop the app opening
            merchant = row[2].strip() if len(row) > 2 else ""
            rules.append((pattern, row[1].strip(), merchant or None))
    return rules


def category_names() -> list[str]:
    """Every category the built-in rules can produce, for the app's pick lists."""
    names = {c for _, c, _ in DEFAULT_RULES} | {c for _, c in BANK_CATEGORIES}
    return sorted(names - {UNCATEGORIZED})


def clean_merchant(description: str) -> str:
    text = description.upper()
    for _ in range(2):
        text = _PREFIXES.sub("", text).strip()
    text = re.split(r"[*#,]", text)[0] or text
    text = re.sub(r"\.COM\b", "", text)
    text = re.sub(r" (ON \d{6}|FROM CARD|WEB PMTS?|EPAY|DEBITS|PAYMENT|PMT|P2P|CC|CREDIT CRD|CREDIT CARD).*$", "", text)
    words = [w.strip(".,-'/") for w in text.split() if not re.search(r"\d|^X{3,}$", w)]
    words = [w for w in words if w and w not in ("STORE", "LLC", "INC", "THE", "FSB")]
    if len(words) > 1 and words[-1] in _STATES:
        words.pop()
    name = " ".join(words[:3]).replace("'", "").replace("-", " ")  # Cane's / Canes, Hiko-A-Mon
    return " ".join(name.split()).title() or description.strip().title()


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


def _kind(category: str, cents: int, account_type: str) -> str:
    if category in TRANSFER_CATEGORIES:
        return "transfer"
    if cents < 0:
        return "expense"
    if category == "Income" or (category == UNCATEGORIZED and account_type != "credit"):
        return "income"
    return "refund"


def classify(rows: list[dict], accounts: dict, user_rules: list[tuple]) -> list[dict]:
    default_rules = [(re.compile(p), c, m) for p, c, m in DEFAULT_RULES]
    saved_at = [(re.compile(p), SAVED, m) for p, m in _SAVED_AT]
    out = []
    for r in rows:
        account_type = accounts[r["account"]]["type"]
        text = r["description"].upper()
        hit = next((rule for rule in user_rules if rule[0].search(text)), None)
        ruled = hit is not None
        if not hit:
            hit = next((rule for rule in saved_at if rule[0].search(text)), None)
        if not hit and is_transfer(text, r["cents"], account_type, r["bank_category"]):
            hit = (None, "Transfer", None)
        if not hit:  # money out is never income, whatever the name: GUSTO'S PIZZA, a pay reversal
            hit = next((rule for rule in default_rules if rule[0].search(text)
                        and (rule[1] != "Income" or r["cents"] > 0)), None)
        category = hit[1] if hit else (_bank_category(r["bank_category"]) or UNCATEGORIZED)
        merchant = (hit[2] if hit and hit[2] else None) or clean_merchant(r["description"])
        out.append({
            "date": r["date"], "account": r["account"], "description": r["description"],
            "merchant": merchant, "category": category, "cents": r["cents"],
            "balance": r["balance"], "kind": _kind(category, r["cents"], account_type),
            "ruled": ruled, "matched": False, "source": r.get("source", ""),
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
    return out


def _pair_transfers(rows: list[dict], accounts: dict) -> None:
    """Match each transfer with its other half.

    Only a row already recognized as a transfer can claim a partner, and the partner
    must be a transfer too or something unexplained. So a card payment can't swallow
    a same-sized rent payment or paycheck, and a $20 refund can't pair off with an
    unrelated $20 purchase.
    """
    by_amount = defaultdict(list)
    for r in rows:
        by_amount[r["cents"]].append(r)
    for r in rows:
        if r["kind"] != "transfer" or r["matched"]:
            continue
        candidates = [c for c in by_amount[-r["cents"]]
                      if c["account"] != r["account"] and not c["matched"] and not c["ruled"]
                      and c["category"] in (*TRANSFER_CATEGORIES, UNCATEGORIZED)
                      and abs((c["date"] - r["date"]).days) <= PAIR_DAYS]
        if candidates:
            other = min(candidates, key=lambda c: (c["kind"] != "transfer",
                                                   abs((c["date"] - r["date"]).days)))
            r["matched"] = other["matched"] = True
            other["kind"] = "transfer"
            # Both halves imported: it's now one internal move, so the savings
            # account's side alone reports it and it isn't counted as saved twice.
            r["category"] = other["category"] = "Transfer"


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
        "first": group[0]["date"].isoformat(), "last": latest["date"].isoformat(),
        "next": (latest["date"] + timedelta(days=span)).isoformat(),
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
    _, span, tolerance, _, _ = cadence
    ended = date.fromisoformat(entry["last"])
    later = [r for r in merchant_rows if r["account"] != entry["account"] and r["date"] > ended
             and (last_seen[r["account"]] - r["date"]).days <= span * 1.5 + tolerance]
    if later:
        card = later[-1]["account"]
        upcoming = ended + timedelta(days=span)
        while upcoming <= last_seen[card]:
            upcoming += timedelta(days=span)
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


def monthly_summary(rows: list[dict]) -> list[dict]:
    months: dict[str, dict] = {}
    for r in rows:
        m = months.setdefault(r["date"].strftime("%Y-%m"), {
            "month": r["date"].strftime("%Y-%m"), "income": 0, "spending": 0, "categories": defaultdict(int)})
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

    Entered as a card's amount owed, so it's flipped: a card balance is negative,
    which lets the same sum work for purchases and payments on any account."""
    anchor = info["balance_anchor"]
    pinned = date.fromisoformat(anchor["date"])
    start = round(anchor["amount"] * 100) * (-1 if info["type"] == "credit" else 1)

    def on(day: date) -> int:
        after = sum(r["cents"] for r in own if pinned < r["date"] <= day)
        undone = sum(r["cents"] for r in own if day < r["date"] <= pinned)
        return start + after - undone

    last = max(pinned, own[-1]["date"])
    return {"months": {m: on(end) for m, end in _month_ends(own[0]["date"], last)},
            "current": on(last), "as_of": last.isoformat(), "calculated": True}


def account_balances(rows: list[dict], accounts: dict) -> dict[str, dict]:
    """Each account's latest and month-end balances, by the best source it has: the
    export's own balance column, or else a balance the person entered."""
    exported = month_end_balances(rows)
    found = {}
    for account, info in accounts.items():
        own = sorted((r for r in rows if r["account"] == account), key=lambda r: r["date"])
        if account in exported:
            with_balance = [r for r in own if r["balance"] is not None]
            found[account] = {"months": exported[account], "current": with_balance[-1]["balance"],
                              "as_of": with_balance[-1]["date"].isoformat(), "calculated": False}
        elif own and info.get("balance_anchor"):
            found[account] = _calculated(own, info)
    return found


def coverage_start(rows: list[dict], accounts: dict) -> str | None:
    """First month with checking history. Rent and most bills live there, so a month
    before it shows only card spending and would drag every average down."""
    months = [r["date"].strftime("%Y-%m") for r in rows if accounts[r["account"]]["type"] == "checking"]
    return min(months, default=None)


def partial_month(end: date) -> str | None:
    """The month still in progress, judged by the newest transaction."""
    return end.strftime("%Y-%m") if end.day < 26 else None


def budget_report(rows: list[dict], accounts: dict, budgets: dict[str, dict]) -> dict:
    """Spending against each target, by month. A percent target follows that month's
    income, except in the month in progress, where pay may not have landed yet: that
    one uses recent income, or it would read as over budget until payday."""
    targets = [{"category": c, "mode": b["mode"], "value": b["value"] / 100 if b["mode"] == "amount" else b["value"]}
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
            balances[r["account"]][r["date"].strftime("%Y-%m")] = r["balance"]
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


def checks(rows: list[dict], accounts: dict, imports: list[dict]) -> list[dict]:
    """Things that would make the numbers wrong, worded as what to do about them."""
    found = []
    for account, gaps in coverage_gaps(imports).items():
        for start, end in gaps:
            found.append({"level": "warning", "title": f"Missing history: {accounts[account]['name']}",
                          "detail": f"Nothing imported from {start} to {end}. Export that "
                                    "period and drop it in the inbox."})

    unmatched = [r for r in rows if (r["category"] == "Transfer" or r["kind"] == "estimate")
                 and not r["matched"] and r["cents"] < 0 and accounts[r["account"]]["type"] != "credit"]

    # A payment dated before a card's history starts isn't a mystery, just a short export.
    first_by_account: dict[str, date] = {}
    for r in rows:
        first_by_account[r["account"]] = min(first_by_account.get(r["account"], r["date"]), r["date"])
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

    spending = [r for r in rows if r["kind"] == "expense"]
    loose = [r for r in spending if r["category"] == UNCATEGORIZED]
    if spending and loose:
        share = sum(r["cents"] for r in loose) / sum(r["cents"] for r in spending)
        by_merchant = defaultdict(int)
        for r in loose:
            by_merchant[r["merchant"]] += r["cents"]
        top = ", ".join(k for k, _ in sorted(by_merchant.items(), key=lambda kv: kv[1])[:5])
        if share >= 0.01:
            found.append({"level": "info", "title": f"{share:.0%} of spending is uncategorized",
                          "detail": f"Biggest: {top}. Add a line to rules.csv to sort these."})

    # Card spending with no income beside it makes those months look badly overspent.
    deposits = [d for a, d in first_by_account.items() if accounts[a]["type"] == "checking"]
    cards = [d for a, d in first_by_account.items() if accounts[a]["type"] == "credit"]
    if deposits and cards:
        income_from, spending_from = min(deposits), min(cards)
        if (income_from - spending_from).days > 45:
            found.append({"level": "warning", "title": "Income history is shorter than card history",
                          "detail": f"Cards go back to {spending_from} but checking only to "
                                    f"{income_from}. Months before that show spending with no "
                                    "income, so judge savings from later months, or import the "
                                    "earlier bank history."})

    found += _duplicate_checks(rows, accounts)

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
        if info["type"] == "credit" and account not in balances and account in last_by_account:
            found.append({"level": "info", "title": f"No balance yet: {info['name']}",
                          "detail": "Its export doesn't include one. Add it with Edit in the "
                                    "Accounts list."})
    for account, info in accounts.items():
        if info.get("sign_guessed") and info.get("invert_sign"):
            found.append({"level": "info", "title": f"Check signs: {info['name']}",
                          "detail": "Amounts looked like purchases were positive, so they were "
                                    "flipped. If that's wrong, set invert_sign to false in "
                                    "accounts.json and rerun."})
    return found
