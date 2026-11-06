"""The compiled spreadsheet. Regenerated from the ledger on every run, so it holds
computed values rather than formulas, and edits made in Excel don't carry over."""
from __future__ import annotations

import re
from collections import defaultdict
from datetime import date
from pathlib import Path

from openpyxl import Workbook
from openpyxl.chart import BarChart, Reference, Series
from openpyxl.formatting.rule import ColorScaleRule
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter as col
from openpyxl.worksheet.table import Table, TableStyleInfo

from .analyze import account_balances, coverage_start, monthly_summary

FONT = "Arial"
# Green above zero, red below. SPENT_* are for columns holding spending as a positive
# number, where more is the red direction.
MONEY = '[Color10]$#,##0.00;[Red]-$#,##0.00;"-"'
WHOLE = '[Color10]$#,##0;[Red]-$#,##0;"-"'
PERCENT = '[Color10]0%;[Red]-0%;"-"'
SPENT = '[Red]$#,##0.00;[Color10]-$#,##0.00;"-"'
SPENT_WHOLE = '[Red]$#,##0;[Color10]-$#,##0;"-"'
DATE = "mmm d, yyyy"
INK = "1F2933"
HEAD = PatternFill("solid", fgColor="1F4E79")
BAND = PatternFill("solid", fgColor="EEF3F8")
RULE = Border(bottom=Side(style="thin", color="C3C2B7"))


def _title(ws, text: str, note: str = "") -> int:
    ws["A1"] = text
    ws["A1"].font = Font(name=FONT, size=16, bold=True, color=INK)
    ws["A2"] = note
    ws["A2"].font = Font(name=FONT, size=10, color="52514E")
    ws.sheet_view.showGridLines = False
    return 4


def _header(ws, row: int, labels: list[str]) -> None:
    for i, label in enumerate(labels, 1):
        cell = ws.cell(row, i, label)
        cell.font = Font(name=FONT, size=10, bold=True, color="FFFFFF")
        cell.fill = HEAD
        cell.alignment = Alignment(horizontal="left" if i == 1 else "center", vertical="center", wrap_text=True)


def _widths(ws, widths: list[int]) -> None:
    for i, width in enumerate(widths, 1):
        ws.column_dimensions[col(i)].width = width


def _body(ws, start: int, rows: list[list], formats: dict[int, str]) -> int:
    for r, values in enumerate(rows, start):
        for c, value in enumerate(values, 1):
            cell = ws.cell(r, c, value)
            cell.font = Font(name=FONT, size=10)
            cell.border = RULE
            if c in formats:
                cell.number_format = formats[c]
    return start + len(rows)


def _table(ws, name: str, top: int, rows: list[list], labels: list[str], formats: dict[int, str]) -> None:
    """Excel table: filter buttons, sorting and banding built in."""
    _header(ws, top, labels)
    end = _body(ws, top + 1, rows, formats)
    if rows:
        table = Table(displayName=name, ref=f"A{top}:{col(len(labels))}{end - 1}")
        table.tableStyleInfo = TableStyleInfo(name="TableStyleLight1", showRowStripes=True)
        ws.add_table(table)
    ws.freeze_panes = ws.cell(top + 1, 1)


def _summary(wb, rows, recurring, checks, accounts) -> None:
    ws = wb.active
    ws.title = "Summary"
    first, last = min(r["date"] for r in rows), max(r["date"] for r in rows)
    top = _title(ws, "Budget summary", f"{first:%b %d, %Y} to {last:%b %d, %Y}. "
                 "Transfers between your own accounts aren't counted; refunds net against spending. "
                 "Card payments with no imported purchases count as estimated spending.")
    months = monthly_summary(rows)
    partial = last.strftime("%Y-%m") if last.day < 26 else None
    # Before checking history starts there's no rent or income, so averages skip it.
    start = coverage_start(rows, accounts) or months[0]["month"]
    complete = [m for m in months if m["month"] != partial and m["month"] >= start] or months
    recent = complete[-12:]
    income = sum(m["income"] for m in recent) / len(recent) / 100
    spending = sum(m["spending"] for m in recent) / len(recent) / 100
    bills = sum(e["per_month"] for e in recurring if e["active"] and e["kind"] == "expense")
    tiles = [(f"Avg. monthly spending ({len(recent)} mo)", spending, SPENT_WHOLE),
             (f"Avg. monthly income ({len(recent)} mo)", income, WHOLE),
             ("Savings rate", (income - spending) / income if income else 0, PERCENT),
             ("Recurring bills per month", bills, SPENT_WHOLE)]
    for i, (label, value, fmt) in enumerate(tiles):
        c = 1 + i
        ws.cell(top, c, label).font = Font(name=FONT, size=9, color="52514E")
        ws.cell(top, c).alignment = Alignment(wrap_text=True, vertical="top")
        cell = ws.cell(top + 1, c, value)
        cell.font = Font(name=FONT, size=16, bold=True, color=INK)
        cell.number_format = fmt
        cell.alignment = Alignment(horizontal="left")
    ws.row_dimensions[top].height = 28

    table_top = top + 3
    _header(ws, table_top, ["Month", "Income", "Spending", "Kept", "Savings rate"])
    data = []
    for m in months:
        income, spending = m["income"] / 100, m["spending"] / 100
        label = m["month"] + (" (so far)" if m["month"] == partial else "")
        if m["month"] < start:
            label += " (cards only)"
        data.append([label, income, spending, income - spending,
                     (income - spending) / income if income else None])
    end = _body(ws, table_top + 1, data, {2: MONEY, 3: SPENT, 4: MONEY, 5: PERCENT})

    chart = BarChart()
    chart.type, chart.title, chart.height, chart.width = "col", "Income and spending", 9, 20
    window = max(table_top + 1, end - 24)
    for c in (2, 3):
        series = Series(Reference(ws, min_col=c, min_row=window, max_row=end - 1),
                        title=ws.cell(table_top, c).value)
        series.graphicalProperties.solidFill = "1F9D55" if c == 2 else "E34948"
        chart.series.append(series)
    chart.set_categories(Reference(ws, min_col=1, min_row=window, max_row=end - 1))
    chart.y_axis.numFmt, chart.y_axis.delete, chart.x_axis.delete = "$#,##0", False, False
    ws.add_chart(chart, f"G{table_top}")

    if checks:
        row = end + 2
        ws.cell(row, 1, "Worth checking").font = Font(name=FONT, size=11, bold=True, color=INK)
        for check in checks:
            row += 1
            ws.cell(row, 1, f"{check['title']}: {check['detail']}").font = Font(name=FONT, size=10)
    _widths(ws, [24, 18, 18, 18, 14, 3])


def _categories(wb, rows, accounts) -> None:
    ws = wb.create_sheet("Categories")
    top = _title(ws, "Spending by category", "Net of refunds, one column per month, largest category first. "
                 "The average skips months before checking history and the month in progress.")
    months = monthly_summary(rows)
    totals = defaultdict(int)
    for m in months:
        for category, cents in m["categories"].items():
            totals[category] += cents
    cats = sorted(totals, key=totals.get, reverse=True)
    last = max(r["date"] for r in rows)
    partial = last.strftime("%Y-%m") if last.day < 26 else None
    start = coverage_start(rows, accounts) or months[0]["month"]
    covered = [m for m in months if m["month"] >= start and m["month"] != partial] or months

    def average(category: str) -> float:
        return sum(m["categories"].get(category, 0) for m in covered) / len(covered) / 100

    _header(ws, top, ["Category", *[m["month"] for m in months], "Total", "Avg. / month"])
    data = [[c, *[m["categories"].get(c, 0) / 100 for m in months], totals[c] / 100, average(c)]
            for c in cats]
    n = len(months)
    data.append(["Total", *[m["spending"] / 100 for m in months],
                 sum(totals.values()) / 100, sum(m["spending"] for m in covered) / len(covered) / 100])
    end = _body(ws, top + 1, data, {i: SPENT_WHOLE for i in range(2, n + 4)})
    for c in range(1, n + 4):
        ws.cell(end - 1, c).font = Font(name=FONT, size=10, bold=True)
    if cats:
        ws.conditional_formatting.add(
            f"B{top + 1}:{col(n + 1)}{end - 2}",
            ColorScaleRule(start_type="num", start_value=0, start_color="FFFFFF",
                           end_type="max", end_color="F4A6A6"))
    ws.freeze_panes = ws.cell(top + 1, 2)
    _widths(ws, [24, *[10] * n, 12, 12])


def _recurring(wb, recurring, accounts_lookup) -> None:
    ws = wb.create_sheet("Recurring")
    top = _title(ws, "Recurring payments and income",
                 "Detected from repeating merchants, amounts and timing. Varies = the amount changes each time.")
    labels = ["Name", "Type", "Category", "Every", "Amount", "Per month", "Varies", "Price change",
              "Status", "Times seen", "Last", "Next expected", "Account"]
    data = [[e["merchant"], "Income" if e["kind"] == "income" else "Bill", e["category"], e["cadence"],
             e["amount"], e["per_month"], "Yes" if e["variable"] else "", e["price_change"] or None,
             "Active" if e["active"] else "Stopped", e["count"],
             _day(e["last"]), _day(e["next"]) if e["active"] else None, accounts_lookup[e["account"]]]
            for e in recurring]
    _table(ws, "Recurring", top, data, labels, {5: MONEY, 6: MONEY, 8: SPENT, 11: DATE, 12: DATE})
    for row, entry in enumerate(recurring, top + 1):
        if entry["kind"] != "income":
            ws.cell(row, 5).number_format = ws.cell(row, 6).number_format = SPENT
    _widths(ws, [26, 9, 16, 11, 12, 12, 8, 12, 9, 8, 14, 14, 28])


def _day(text: str) -> date:
    return date.fromisoformat(text)


def _largest(wb, rows, accounts) -> None:
    ws = wb.create_sheet("Largest")
    top = _title(ws, "Largest expenses", "The 100 biggest single expenses across all history.")
    biggest = sorted((r for r in rows if r["kind"] == "expense"), key=lambda r: r["cents"])[:100]
    data = [[r["date"], r["merchant"], r["category"], -r["cents"] / 100, accounts[r["account"]]["name"],
             r["description"]] for r in biggest]
    _table(ws, "Largest", top, data, ["Date", "Merchant", "Category", "Amount", "Account", "Description"],
           {1: DATE, 4: SPENT})
    _widths(ws, [14, 26, 16, 13, 28, 56])


def _accounts(wb, rows, accounts) -> None:
    ws = wb.create_sheet("Accounts")
    top = _title(ws, "Accounts", "One row per bank + account number. Each has its own sheet with its full history.")
    balances = account_balances(rows, accounts)
    data = []
    for account, info in sorted(accounts.items(), key=lambda kv: kv[1]["name"]):
        own = [r for r in rows if r["account"] == account]
        if not own:
            continue
        balance = balances.get(account)
        basis = ("Not set" if not balance else "Calculated" if balance["calculated"] else "From export")
        data.append([info["name"], info["bank"], info["number"], info["type"], len(own),
                     own[0]["date"], own[-1]["date"], balance["current"] / 100 if balance else None,
                     basis, _day(balance["as_of"]) if balance else None])
    _table(ws, "Accounts", top, data, ["Account", "Bank", "Number", "Type", "Transactions", "First", "Last",
                                       "Latest balance", "Balance basis", "As of"],
           {6: DATE, 7: DATE, 8: MONEY, 10: DATE})
    _widths(ws, [32, 20, 9, 10, 13, 14, 14, 15, 13, 14])


TX_LABELS = ["Date", "Account", "Merchant", "Category", "Kind", "Amount", "Balance", "Description", "Source file"]
TX_FORMATS = {1: DATE, 6: MONEY, 7: MONEY}
TX_WIDTHS = [14, 28, 26, 16, 10, 13, 13, 56, 34]


def _tx_row(r, accounts) -> list:
    return [r["date"], accounts[r["account"]]["name"], r["merchant"], r["category"], r["kind"],
            r["cents"] / 100, r["balance"] / 100 if r["balance"] is not None else None,
            r["description"], r.get("source", "")]


def _transactions(wb, rows, accounts) -> None:
    ws = wb.create_sheet("All Transactions")
    newest_first = sorted(rows, key=lambda r: r["date"], reverse=True)
    top = _title(ws, "All transactions", "Every account, newest first. Negative = money out.")
    _table(ws, "AllTransactions", top, [_tx_row(r, accounts) for r in newest_first], TX_LABELS, TX_FORMATS)
    _widths(ws, TX_WIDTHS)


def _account_sheets(wb, rows, accounts) -> None:
    used = set()
    for n, (account, info) in enumerate(sorted(accounts.items(), key=lambda kv: kv[1]["name"])):
        own = sorted((r for r in rows if r["account"] == account), key=lambda r: r["date"], reverse=True)
        if not own:
            continue
        title = re.sub(r"[\\/*?:\[\]]", " ", info["name"])[:31]
        while title in used:
            title = f"{title[:28]}{n:03d}"
        used.add(title)
        ws = wb.create_sheet(title)
        top = _title(ws, info["name"], f"{len(own):,} transactions, {own[-1]['date']:%b %d, %Y} to "
                     f"{own[0]['date']:%b %d, %Y}. Newest first.")
        _table(ws, f"Account{n}", top, [_tx_row(r, accounts) for r in own], TX_LABELS, TX_FORMATS)
        _widths(ws, TX_WIDTHS)


def write(path: Path, rows, accounts, recurring, checks) -> None:
    wb = Workbook()
    _summary(wb, rows, recurring, checks, accounts)
    _categories(wb, rows, accounts)
    _recurring(wb, recurring, {a: i["name"] for a, i in accounts.items()})
    _largest(wb, rows, accounts)
    _accounts(wb, rows, accounts)
    _transactions(wb, rows, accounts)
    _account_sheets(wb, rows, accounts)
    wb.save(path)
