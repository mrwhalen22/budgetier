"""Made-up data for the window's tests: 15 months of a checking account, a card and savings,
with a rule, a budget, and four merchants still needing a category."""
from datetime import date
from pathlib import Path

from budgetier import service
from budgetier.accounts import pin_balance
from budgetier.ledger import _money

ACCOUNTS = {"chk-0001": ("Bank", "0001", "checking", "Bank Checking 0001"), "card-0002": ("Chase", "0002", "credit", "Chase Card 0002"),
            "sav-0003": ("Bank", "0003", "savings", "Bank Savings 0003")}
UNSORTED = ["QQQ WIDGETS", "VVV PARTS", "XYLO GOODS", "ZZYZX HARDWARE"]
FIRST, LAST = date(2025, 8, 1), date(2026, 10, 15)


def row(account: str, day: date, text: str, cents: int) -> dict:
    return {"date": day, "account": account, "description": text, "amount": _money(cents), "cents": cents, "balance": None,
            "bank_category": "", "source": "made-up.csv", "sync_id": ""}


def made_up() -> list[dict]:
    found, n = [], 0
    year, month = FIRST.year, FIRST.month
    while date(year, month, 1) <= LAST:
        n += 1
        on = lambda d: date(year, month, d)  # noqa: B023, E731 - used within this pass of the loop
        found += [row("chk-0001", on(1), "ACH DEBIT LAKESIDE APTS RENT", -185000), row("chk-0001", on(5), "ACME INC PAYROLL", 312100),
                  row("card-0002", on(3), "NETFLIX.COM", -1599), row("card-0002", on(6), "KROGER #123", -8000 - n * 37),
                  row("card-0002", on(8), "CHIPOTLE 2291", -1450 - n), row("card-0002", on(12), "PAYMENT THANK YOU", 60000),
                  row("chk-0001", on(12), "CHASE CREDIT CRD EPAY", -60000), row("chk-0001", on(13), "ONLINE TRANSFER TO BROKER", -10000),
                  row("sav-0003", on(15), "INT PMT", 500)]
        if date(year, month, 20) <= LAST:
            found.append(row("chk-0001", on(20), "COMCAST CABLE 800", -7999))
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    found += [row("card-0002", date(2026, 6, 14), "BEST BUY 00123", -129999), row("card-0002", date(2026, 3, 21), "DELTA AIR 0062", -68430),
              *[row("card-0002", date(2026, 9, 2 + i), text, -2500 - i) for i, text in enumerate(UNSORTED)]]
    return found


def build(home: Path, rows: list[dict] | None = None) -> service.Budget:
    budget = service.Budget(home)
    budget.ledger.accounts = {a: {"name": name, "bank": bank, "number": number, "type": kind, "invert_sign": False}
                              for a, (bank, number, kind, name) in ACCOUNTS.items()}
    pin_balance(budget.ledger.accounts["sav-0003"], 500000, LAST)
    budget.ledger.rows = made_up() if rows is None else rows
    budget.ledger.save()
    budget.save_rule(None, "KROGER", "Groceries", "Kroger")
    budget.save_budget("Dining", "amount", "300")
    return budget
