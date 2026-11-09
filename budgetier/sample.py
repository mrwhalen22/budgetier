"""Made-up data to look around with before bringing in your own: a year and a half of a checking
account, a credit card, savings and a 401(k), with a budget and a rule. None of it is real.
It always comes out the same, so what the tour points at is there.
"""
from __future__ import annotations

import random
from datetime import date, timedelta
from pathlib import Path

from .accounts import pin_balance, remember_balance
from .ledger import _money
from .service import Budget

MONTHS = 18
ACCOUNTS = {
    "sample-bank-1111": ("Sample Bank", "1111", "checking", "Sample Checking 1111"),
    "sample-card-2222": ("Sample Card Co", "2222", "credit", "Sample Card 2222"),
    "sample-bank-3333": ("Sample Bank", "3333", "savings", "Sample Savings 3333"),
    "sample-plan-4444": ("Sample Retirement", "4444", "retirement", "Sample 401(k) 4444"),
}
CHECKING, CARD, SAVINGS, PLAN = ACCOUNTS
SHOPS = [  # what, how often a month, cents from and to
    ("KROGER #4021", 5, 3500, 14000), ("TRADER JOES #551", 2, 2500, 9000), ("CHIPOTLE 2291", 3, 1100, 2400),
    ("STARBUCKS STORE 1182", 6, 450, 900), ("SHELL OIL 57442", 3, 3000, 6500), ("TARGET 00012", 2, 1500, 12000),
    ("AMAZON MKTP US*2K4", 4, 900, 8000), ("WALGREENS #9911", 1, 800, 4000), ("PANERA BREAD #22", 1, 1200, 2600),
]
BILLS = [  # what, day of the month, account, cents
    ("NETFLIX.COM", 3, CARD, 1599), ("SPOTIFY USA", 9, CARD, 1199), ("PLANET FITNESS", 17, CARD, 2499),
    ("ACH DEBIT LAKESIDE APTS RENT", 1, CHECKING, 165000), ("COMCAST CABLE 800", 20, CHECKING, 7999),
    ("DUKE ENERGY PAYMENT", 14, CHECKING, 9500), ("STATE FARM INS PREM", 6, CHECKING, 12800),
]


def _row(account: str, day: date, text: str, cents: int) -> dict:
    return {"date": day, "account": account, "description": text, "amount": _money(cents), "cents": cents,
            "balance": None, "bank_category": "", "source": "sample", "sync_id": ""}


def rows(today: date, seed: int = 7) -> tuple[list[dict], list[tuple[date, int]]]:
    """The transactions, and the 401(k)'s balance at each month's end."""
    rng = random.Random(seed)
    first = date(today.year - (1 if today.month > 6 else 2), (today.month - 6 - 1) % 12 + 1, 1)
    found, plan, balance = [], [], 3_850_000
    day = first
    while day <= today:
        if day.day in (1, 15):
            found.append(_row(CHECKING, day, "ACME CORP PAYROLL DIRECT DEP", 238500))
            found.append(_row(PLAN, day, "EMPLOYEE CONTRIBUTION", 21000))
            found.append(_row(PLAN, day, "EMPLOYER MATCH", 10500))
            balance += 31500
        for text, on, account, cents in BILLS:
            if day.day == on:
                found.append(_row(account, day, text, -(cents + (rng.randint(-900, 900) if "ENERGY" in text else 0))))
        if day.day == 2:
            found.append(_row(CHECKING, day, "ONLINE TRANSFER TO SAVINGS 3333", -40000))
            found.append(_row(SAVINGS, day, "ONLINE TRANSFER FROM CHECKING 1111", 40000))
        if day.day == 28:
            found.append(_row(SAVINGS, day, "INTEREST PAYMENT", 1800 + rng.randint(0, 400)))
            growth = round(balance * rng.uniform(-.02, .025))
            found.append(_row(PLAN, day, "DIVIDEND REINVEST VTI", 4200 + rng.randint(0, 800)))
            balance += growth + 4600
            plan.append((day, balance))
        for text, per_month, low, high in SHOPS:
            if rng.random() < per_month / 30:
                found.append(_row(CARD, day, text, -rng.randint(low, high)))
        if day.day == 22:
            spent = -sum(r["cents"] for r in found if r["account"] == CARD and r["date"] > day - timedelta(days=31)
                         and r["cents"] < 0)
            found.append(_row(CARD, day, "PAYMENT THANK YOU", spent))
            found.append(_row(CHECKING, day, "SAMPLE CARD CO EPAY", -spent))
        day += timedelta(days=1)
    return found, plan


def build(home: Path, today: date | None = None) -> Budget:
    today = today or date.today()
    budget = Budget(home)
    budget.ledger.accounts = {a: {"name": name, "bank": bank, "number": number, "type": kind, "invert_sign": False}
                              for a, (bank, number, kind, name) in ACCOUNTS.items()}
    found, plan = rows(today)
    budget.ledger.rows = found
    for day, cents in plan:
        remember_balance(budget.ledger.accounts[PLAN], cents, day)
    pin_balance(budget.ledger.accounts[CARD], 61250, today)
    pin_balance(budget.ledger.accounts[SAVINGS], 1_284_000, today)
    budget.ledger.save()
    budget.save_rule(None, "TRADER JOES", "Groceries", "Trader Joe's")
    budget.save_budget("Dining", "amount", "250")
    budget.save_budget("Groceries", "amount", "650")
    return budget
