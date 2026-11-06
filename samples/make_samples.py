"""Write fake exports to samples/demo/inbox for trying Budgetier without real data.

    python samples/make_samples.py
    python -m budgetier --home samples/demo

Everything is invented and seeded. The files deliberately overlap in time and use
each bank's own layout, so they exercise merging, sign handling and transfers.
"""
import csv
import random
from datetime import date, timedelta
from pathlib import Path

OUT = Path(__file__).parent / "demo" / "inbox"
START, END = date(2025, 8, 1), date(2026, 10, 31)
rng = random.Random(7)

checking, chase_card, amex, savings = [], [], [], []


def days():
    d = START
    while d <= END:
        yield d
        d += timedelta(days=1)


def add_month(d):
    return date(d.year + d.month // 12, d.month % 12 + 1, 1)


month = START
while month <= END:
    def on(day):
        return month.replace(day=day)

    checking.append((on(1), "ACH DEBIT LAKESIDE APTS RENT", -1850.00))
    checking.append((on(9), "DUKE ENERGY ELECTRIC 8005551212", -round(rng.uniform(70, 165), 2)))
    checking.append((on(14), "COMCAST CABLE 800-266-2278 PA", -79.99))
    checking.append((on(20), "GEICO AUTO INSURANCE", -112.40))
    chase_card.append((on(3), "NETFLIX.COM", -15.49 if month < date(2026, 3, 1) else -17.99))
    chase_card.append((on(11), "SPOTIFY USA", -11.99))
    amex.append((on(17), "PLANET FIT 1234 CLUB FEES", -24.99))
    if month.month % 3 == 2:
        chase_card.append((on(22), "PROGRESSIVE WATER UTIL QTR", -96.00))

    card_total = round(rng.uniform(900, 1500), 2)
    checking.append((on(25), "CHASE CREDIT CRD AUTOPAY", -card_total))
    chase_card.append((on(26), "AUTOMATIC PAYMENT - THANK YOU", card_total))
    amex_total = round(rng.uniform(250, 500), 2)
    checking.append((on(27), "AMEX EPAYMENT ACH PMT", -amex_total))
    amex.append((on(28), "PAYMENT RECEIVED - THANK YOU", amex_total))
    checking.append((on(15), "ONLINE TRANSFER TO SAV 4410", -400.00))
    savings.append((on(15), "Online Transfer from CHK 8123", 400.00))
    savings.append((on(28), "Interest Paid", round(rng.uniform(11, 16), 2)))
    # A card that was never exported: the dashboard should flag these payments.
    checking.append((on(18), "CITI CARD ONLINE PAYMENT", -round(rng.uniform(120, 220), 2)))
    month = add_month(month)

payday = date(2025, 8, 8)
while payday <= END:
    checking.append((payday, "ACME CORP PAYROLL DIRECT DEP", 3120.55))
    payday += timedelta(days=14)
checking.append((date(2025, 12, 19), "ACME CORP BONUS PAYROLL", 2500.00))
checking.append((date(2026, 2, 6), "ZELLE PAYMENT TO J SMITH", -240.00))
savings.append((date(2026, 5, 12), "Withdrawal to CHK 8123 TRANSFER", -2000.00))
checking.append((date(2026, 5, 13), "ONLINE TRANSFER FROM SAV 4410", 2000.00))

SHOPS = [(chase_card, "WHOLEFDS MKT 10234 AUSTIN TX", 25, 140, .11),
         (chase_card, "TRADER JOE'S #512 AUSTIN TX", 20, 90, .09),
         (chase_card, "STARBUCKS STORE 08123 AUSTIN TX", 4, 9, .22),
         (chase_card, "AMZN MKTP US*2K4LM19A0", 10, 120, .14),
         (chase_card, "SHELL OIL 57441234 AUSTIN TX", 28, 58, .08),
         (chase_card, "TST* FUEGO TACOS AUSTIN TX", 14, 60, .08),
         (amex, "TARGET 00012345 AUSTIN TX", 15, 110, .07),
         (amex, "DOORDASH*THAI KITCHEN", 18, 48, .07),
         (amex, "UBER TRIP HELP.UBER.COM", 9, 32, .05),
         (checking, "CVS/PHARMACY #08812", 6, 45, .03),
         (checking, "ZZYZX HARDWARE SUPPLY", 12, 70, .02)]
for d in days():
    for ledger, name, low, high, chance in SHOPS:
        if rng.random() < chance:
            ledger.append((d, name, -round(rng.uniform(low, high), 2)))
chase_card.append((date(2026, 3, 21), "DELTA AIR 0062341234", -684.30))
chase_card.append((date(2026, 3, 29), "AMZN MKTP US*REFUND", 42.17))
chase_card.append((date(2026, 6, 14), "BEST BUY 00012345", -1299.99))
amex.append((date(2026, 7, 4), "MARRIOTT RESORT AUSTIN", -912.44))
# A genuine repeat: two identical coffees on one day must both survive the merge.
chase_card.extend([(date(2026, 4, 2), "STARBUCKS STORE 08123 AUSTIN TX", -5.75)] * 2)


def between(rows, start, end):
    return sorted((r for r in rows if start <= r[0] <= end), key=lambda r: r[0])


def write(name, header, rows):
    with (OUT / name).open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


def chase_checking(name, start, end):
    balance, out = 4210.18, []
    for d, text, amount in sorted(checking, key=lambda r: r[0]):
        balance = round(balance + amount, 2)
        if start <= d <= end:
            out.append(("CREDIT" if amount > 0 else "DEBIT", d.strftime("%m/%d/%Y"), text,
                        f"{amount:.2f}", "ACH_DEBIT", f"{balance:.2f}", ""))
    write(name, ["Details", "Posting Date", "Description", "Amount", "Type", "Balance", "Check or Slip #"],
          out[::-1])  # Chase lists newest first


def chase_credit(name, start, end):
    out = [(d.strftime("%m/%d/%Y"), (d + timedelta(days=1)).strftime("%m/%d/%Y"), text, "",
            "Sale", f"{amount:.2f}", "") for d, text, amount in between(chase_card, start, end)]
    write(name, ["Transaction Date", "Post Date", "Description", "Category", "Type", "Amount", "Memo"], out[::-1])


OUT.mkdir(parents=True, exist_ok=True)
# Overlapping exports of the same accounts; months 2026-01/02 appear in both.
chase_checking("Chase8123_Activity_20250801_20260228.CSV", START, date(2026, 2, 28))
chase_checking("Chase8123_Activity_20260101_20261031.CSV", date(2026, 1, 1), END)
chase_credit("Chase5521_Activity_20250801_20260228.CSV", START, date(2026, 2, 28))
chase_credit("Chase5521_Activity_20260101_20261031.CSV", date(2026, 1, 1), END)
write("amex_activity_3007.csv", ["Date", "Description", "Amount"],
      [(d.strftime("%m/%d/%Y"), t, f"{-a:.2f}") for d, t, a in between(amex, START, END)])

balance, rows = 8000.00, []
for d, text, amount in sorted(savings, key=lambda r: r[0]):
    balance = round(balance + amount, 2)
    rows.append((d.isoformat(), text, f"{amount:.2f}", f"{balance:.2f}"))
write("HillCountryCU_Savings_4410.csv", ["Date", "Description", "Amount", "Balance"], rows)
print(f"Wrote {len(list(OUT.iterdir()))} files to {OUT}")
