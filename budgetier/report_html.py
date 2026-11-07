"""Join the dashboard's source files and fill in the data. The result is one offline file.

A page opened from disk can't load scripts as modules, so the files are joined instead,
and they share one scope. Order matters only for code that runs while the page loads.
"""
from __future__ import annotations

import json
from collections import Counter
from datetime import date, datetime
from pathlib import Path

from .analyze import SPENDING_KINDS, account_balances, coverage_start, partial_month

SOURCE = Path(__file__).parent / "dashboard"
STYLES = ("styles/intro.css", "styles/tokens.css", "styles/base.css", "styles/components.css", "styles/views.css")
SCRIPTS = ("js/core.js", "js/charts.js", "js/views/shared.js", "js/views/overview.js", "js/views/spending.js",
           "js/views/recurring.js", "js/views/largest.js", "js/views/savings.js", "js/views/accounts.js",
           "js/views/transactions.js", "js/views/budgets.js", "js/router.js", "js/views/help.js", "js/updates.js",
           "js/views/rules.js", "js/tour.js", "js/dialogs.js", "js/bank-sync.js", "js/reload.js", "js/import.js",
           "js/forms.js", "js/events.js", "js/start.js")


def _joined(names: tuple[str, ...]) -> str:
    return "".join((SOURCE / name).read_text(encoding="utf-8") for name in names)


def page() -> str:
    """The whole page, still waiting for its data."""
    return ((SOURCE / "index.html").read_text(encoding="utf-8")
            .replace("/*__BOOT__*/", _joined(("js/boot.js",)))
            .replace("/*__STYLES__*/", _joined(STYLES))
            .replace("/*__SCRIPT__*/", _joined(SCRIPTS)))


def build_data(rows, accounts, recurring, checks, imports) -> dict:
    account_ids = sorted(accounts, key=lambda a: accounts[a]["name"])
    index = {a: i for i, a in enumerate(account_ids)}
    balances = account_balances(rows, accounts)

    summaries = []
    for account in account_ids:
        own = [r for r in rows if r["account"] == account]
        info = accounts[account]
        balance = balances.get(account)
        if not own and not (balance and balance.get("live")):
            continue
        summaries.append({
            "id": account, "index": index[account], "name": info["name"], "bank": info["bank"],
            "number": info["number"], "type": info["type"], "count": len(own),
            "first": min(r["date"] for r in own).isoformat() if own else None,
            "last": max(r["date"] for r in own).isoformat() if own else None,
            "balance": balance["current"] / 100 if balance else None,
            "balances": {m: c / 100 for m, c in balance["months"].items()} if balance else {},
            "balanceAsOf": balance["as_of"] if balance else None,
            "calculated": bool(balance and balance["calculated"]),
            "live": bool(balance and balance.get("live")),
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
                  r["category"], r["kind"], r["cents"] / 100, *([1] if r.get("edited") else [])] for r in rows],
        "recurring": [{**e, "account": accounts[e["account"]]["name"]} for e in recurring],
        "checks": checks,
        "imports": [{**i, "key": i.get("stored") or i["file"], "account": accounts[i["account"]]["name"]}
                    for i in imports[-30:]][::-1],
    }


def write(path: Path, rows, accounts, recurring, checks, imports, extra: dict | None = None) -> None:
    payload = {**build_data(rows, accounts, recurring, checks, imports), **(extra or {})}
    data = json.dumps(payload, separators=(",", ":"))
    # No "<" goes in raw: bank text such as "<!-- <script>" makes a browser skip the tag that
    # closes the data, which leaves the whole page blank.
    html = page().replace("/*__DATA__*/null", data.replace("<", "\\u003c"))
    path.write_text(html, encoding="utf-8")
