import tempfile
import unittest
from datetime import date
from pathlib import Path

from budgetier import service
from budgetier.parse import RawRow, parse_file


class Tmp(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.dir = Path(self._dir.name)

    def csv(self, name, text, encoding="utf-8"):
        path = self.dir / name
        path.write_bytes(text.encode(encoding))
        return parse_file(path)


def raw(day, text, cents, balance=None):
    return RawRow(date=date(2026, 1, day), description=text, cents=cents, balance=balance)


ACCOUNTS = {"chk": {"name": "Checking", "type": "checking"}, "card": {"name": "Card", "type": "credit"},
            "sav": {"name": "Savings", "type": "savings"}}


def row(account, day, text, cents, month=1, year=2026, balance=None):
    return {"date": date(year, month, day), "account": account, "description": text, "cents": cents,
            "balance": balance, "bank_category": ""}


class AppCase(Tmp):
    CHASE = "Transaction Date,Post Date,Description,Category,Type,Amount,Memo\n"
    USAA = "Date,Description,Original Description,Category,Amount,Status\n"

    def setUp(self):
        super().setUp()
        self.src = self.dir / "picked"
        self.src.mkdir()
        self.budget = service.Budget(self.dir / "home")
        self.addCleanup(self.budget.cancel)

    def file(self, name, header, rows):
        path = self.src / name
        path.write_text(header + "".join(rows))
        return str(path)

    def chase(self, name, days):
        return self.file(name, self.CHASE, [f"10/{d:02d}/2026,10/{d:02d}/2026,SHOP {d},Shopping,Sale,-{d}.00,\n" for d in days])

    def add(self, *paths, **over):
        plan = self.budget.inspect(list(paths))
        answers = [{"id": i["id"], "bank": i["bank"], "number": i["number"] or "4001", "type": i["type"],
                    "spent": i["spent"] if i["askSign"] else None, "balance": "", **over} for i in plan["items"]]
        return self.budget.commit(answers)

    def rows(self):
        return sorted(r["description"] for r in self.budget.ledger.rows)
