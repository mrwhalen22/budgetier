"""Fill dashboard.html with the data. The result is one offline file."""
from __future__ import annotations

import json
from collections import Counter
from datetime import date, datetime
from pathlib import Path

from .analyze import SPENDING_KINDS, account_balances, coverage_start, partial_month


def build_data(rows, accounts, recurring, checks, imports) -> dict:
    account_ids = sorted(accounts, key=lambda a: accounts[a]["name"])
    index = {a: i for i, a in enumerate(account_ids)}
    balances = account_balances(rows, accounts)

    summaries = []
    for account in account_ids:
        own = [r for r in rows if r["account"] == account]
        if not own:
            continue
        info = accounts[account]
        balance = balances.get(account)
        summaries.append({
            "id": account, "index": index[account], "name": info["name"], "bank": info["bank"],
            "number": info["number"], "type": info["type"], "count": len(own),
            "first": min(r["date"] for r in own).isoformat(),
            "last": max(r["date"] for r in own).isoformat(),
            "balance": balance["current"] / 100 if balance else None,
            "balances": {m: c / 100 for m, c in balance["months"].items()} if balance else {},
            "balanceAsOf": balance["as_of"] if balance else None,
            "calculated": bool(balance and balance["calculated"]),
        })

    # Ranked once over all history so a category keeps its color under any filter.
    spend = Counter()
    for r in rows:
        if r["kind"] in SPENDING_KINDS:
            spend[r["category"]] -= r["cents"]
    categories = [c for c, _ in spend.most_common()]

    end = max((r["date"] for r in rows), default=date.today())
    return {
        "generated": datetime.now().strftime("%b %d, %Y %I:%M %p"),
        "end": end.isoformat(),
        "partialMonth": partial_month(end),
        "coverageFrom": coverage_start(rows, accounts),
        "accounts": summaries,
        "accountCount": len(account_ids),
        "categories": categories,
        "txns": [[r["date"].isoformat(), index[r["account"]], r["description"], r["merchant"],
                  r["category"], r["kind"], r["cents"] / 100] for r in rows],
        "recurring": [{**e, "account": accounts[e["account"]]["name"]} for e in recurring],
        "checks": checks,
        "imports": [{**i, "key": i.get("stored") or i["file"], "account": accounts[i["account"]]["name"]}
                    for i in imports[-30:]][::-1],
    }


def write(path: Path, rows, accounts, recurring, checks, imports, extra: dict | None = None) -> None:
    template = (Path(__file__).parent / "dashboard.html").read_text(encoding="utf-8")
    payload = {**build_data(rows, accounts, recurring, checks, imports), **(extra or {})}
    data = json.dumps(payload, separators=(",", ":"))
    html = template.replace("/*__DATA__*/null", data.replace("</", "<\\/"))
    path.write_text(html, encoding="utf-8")
