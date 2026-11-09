"""Keep accounts up to date from SimpleFIN.

Files stay the record for anything they cover. When a bank account is linked to an
account that already has history, the feed only adds from that history's last day on,
and rows near that day are matched by amount and date, because a feed words things
differently from an export. Each feed row keeps its id, so syncing twice adds nothing.
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
from datetime import date, datetime, timedelta

from . import credentials, simplefin
from .accounts import TYPES, account_id, account_name, entered_balance, pin_balance
from .parse import _guess_type, last4
from .simplefin import Feed
from .storage import BudgetError, unique_path, write_files

OVERLAP_DAYS = 5  # some banks date a row before the day it reaches the feed; repeats cost nothing
RECENT = timedelta(minutes=5)  # a second press this soon can't have anything new, and a
# review this recent is reused: opening the same screen twice shouldn't cost a request
DAILY_LIMIT = 20  # the server allows about 24 a day and disables access beyond that
# Syncing by itself: when Budgetier opens, unless it synced within the hour; or once a day.
AUTO = (("off", "Only when I press Sync now"), ("open", "When Budgetier opens"), ("daily", "Once a day, while it's open"))
AUTO_AFTER = {"open": timedelta(hours=1), "daily": timedelta(hours=20)}


class BankSync:
    def __init__(self, budget):
        self.budget = budget
        self.home = budget.home
        self.path = self.home / "sync.json"
        self.state = self._load()
        self._feed: Feed | None = None  # kept from review, so linking costs no request
        self._feed_at: datetime | None = None

    # ---- saved state

    def _load(self) -> dict:
        if not self.path.exists():
            return {}
        try:
            state = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(state, dict) or not isinstance(state.get("links", {}), dict):
                raise ValueError("unexpected shape")
            return state
        except ValueError:
            aside = unique_path(self.home, "sync.damaged.json")
            shutil.copy2(self.path, aside)
            self.budget.notices.append({"level": "warning", "title": "Bank sync settings couldn't be read",
                                        "detail": "Choose your accounts again on the Accounts tab. Nothing "
                                                  f"was lost. The damaged file is saved as {aside.name}."})
            return {"connected": True}

    def _save(self) -> None:
        write_files({self.path: json.dumps(self.state, indent=2, sort_keys=True)})

    @property
    def links(self) -> dict[str, dict]:
        return self.state.setdefault("links", {})

    def status(self) -> dict:
        accounts = self.budget.ledger.accounts
        names = [accounts[link["account"]]["name"] for link in self.links.values() if link["account"] in accounts]
        return {"connected": bool(self.state.get("connected")), "lastSync": self.state.get("last_sync"),
                "linked": sorted(names), "problems": self.state.get("problems", []),
                "unlinked": self.state.get("unlinked", 0), "auto": self.auto}

    # ---- syncing by itself

    @property
    def auto(self) -> str:
        mode = self.state.get("auto", "off")
        return mode if mode in AUTO_AFTER else "off"

    def set_auto(self, mode: str) -> None:
        if mode not in (*AUTO_AFTER, "off"):
            raise BudgetError("Choose when to sync.")
        self.state["auto"] = mode
        self._save()

    def auto_due(self, now: datetime | None = None, opening: bool = False) -> bool:
        """Whether to sync by itself now: it's set to, there are accounts to update, and the last
        sync is old enough. When Budgetier opens counts only as it opens."""
        mode = self.auto
        if mode == "off" or (mode == "open" and not opening) or not self.state.get("connected") or not self.links:
            return False
        last = self.state.get("last_sync")
        try:
            return last is None or (now or datetime.now()) - datetime.fromisoformat(last) >= AUTO_AFTER[mode]
        except ValueError:
            return True

    # ---- limits

    def _recent_requests(self, now: datetime) -> list[str]:
        return [t for t in self.state.get("requests", []) if now - datetime.fromisoformat(t) < timedelta(days=1)]

    def _fetch(self, access: str, start: date, end: date) -> Feed:
        """One request per MAX_DAYS, counted, because going over can lose the connection."""
        feed = Feed()
        while start <= end:
            now = datetime.now()
            used = self._recent_requests(now)
            if len(used) >= DAILY_LIMIT:
                raise BudgetError("Budgetier has synced as often as SimpleFIN allows today. Try again tomorrow.")
            self.state["requests"] = used + [now.isoformat(timespec="seconds")]
            self._save()
            stop = min(start + timedelta(days=simplefin.MAX_DAYS - 1), end)
            part = simplefin.fetch(access, start, stop)
            feed.problems = list(dict.fromkeys(feed.problems + part.problems))
            known = {a.key: a for a in feed.accounts}
            for account in part.accounts:
                if account.key in known:  # the newest window has the newest balance
                    known[account.key].rows += account.rows
                    known[account.key].balance = account.balance
                    known[account.key].balance_date = account.balance_date
                else:
                    feed.accounts.append(account)
            start = stop + timedelta(days=1)
        return feed

    def _access(self) -> str:
        access = credentials.load(self.home)
        if not access:
            raise BudgetError("The bank connection is missing from this computer. Disconnect, then connect "
                              "again with a new setup token.")
        return access

    # ---- connecting

    def connect(self, token: str) -> dict:
        """Claim a setup token, then offer the accounts. Once a token is claimed it can't be
        claimed again, so anything that fails after that must not read as a bad token."""
        if not (self.state.get("connected") and credentials.load(self.home)):
            simplefin.claim_url(token)  # a typo shouldn't get as far as anything else
            credentials.check(self.home)
            credentials.save(self.home, simplefin.claim(token))
            self.state = {"connected": True, "links": {}}
            self._save()
        try:
            return self.review()
        except BudgetError as e:
            return {"accounts": [], "existing": self._existing(),
                    "problems": [f"Connected, but the accounts couldn't be read yet. {e}"]}

    def _existing(self) -> list[dict]:
        accounts = self.budget.ledger.accounts
        return sorted(({"id": a, "name": info["name"]} for a, info in accounts.items()), key=lambda a: a["name"])

    def review(self) -> dict:
        """What the feed offers and where each account would go. Saves no choices."""
        now = datetime.now()
        if self._feed is None or now - self._feed_at >= RECENT:
            today = now.date()
            self._feed = self._fetch(self._access(), today - timedelta(days=simplefin.MAX_DAYS - 1), today)
            self._feed.accounts.sort(key=lambda a: (a.connection, a.name))
            self._feed_at = now
            self._record_outcome(self._feed, synced=False)
        return {"accounts": [self._proposal(a) for a in self._feed.accounts], "existing": self._existing(),
                "problems": self._feed.problems}

    def _proposal(self, feed_account) -> dict:
        accounts = self.budget.ledger.accounts
        number = last4(feed_account.name)
        linked = self.links.get(feed_account.key, {}).get("account")
        same_digits = [a for a, info in accounts.items() if number and info.get("number") == number]
        match = linked if linked in accounts else (same_digits[0] if len(same_digits) == 1 else "")
        return {"key": feed_account.key, "name": feed_account.name, "bank": feed_account.connection, "number": number,
                "type": _guess_type(feed_account.name) or "checking", "balance": feed_account.balance / 100,
                "count": len(feed_account.rows), "currency": feed_account.currency, "account": match,
                "skipped": feed_account.key in self.state.get("skipped", [])}

    def _new_account(self, choice: dict, feed_account) -> str:
        """Many feeds don't give account digits, so they're optional here. Without them the
        bank's own account name identifies it, and the number only has to be stable."""
        bank = (choice.get("bank") or "").strip()
        digits = re.sub(r"\D", "", choice.get("number") or "")[-4:]
        kind = choice.get("type")
        if not bank or kind not in TYPES:
            raise BudgetError(f"Enter the bank and type for {feed_account.name}.")
        if digits and len(digits) != 4:
            raise BudgetError(f"Enter all 4 digits for {feed_account.name}, or leave them blank.")
        number = digits or f"{int(hashlib.sha256(feed_account.key.encode()).hexdigest()[:8], 16) % 10000:04d}"
        name = account_name(bank, kind, digits) if digits else f"{bank} {feed_account.name}"
        account = account_id(bank, number)
        self.budget.ledger.accounts.setdefault(account, {"name": name, "bank": bank, "number": number, "type": kind,
                                                         "invert_sign": False})
        return account

    def link(self, choices: list[dict]) -> dict:
        """Apply the reviewed choices, using the feed review already fetched."""
        if self._feed is None:
            raise BudgetError("That review has expired. Open it again.")
        by_key = {a.key: a for a in self._feed.accounts}
        results = []

        def change():
            ledger = self.budget.ledger
            links, skipped = {}, []
            for choice in choices:
                key = choice.get("key")
                feed_account = by_key.get(key)
                if feed_account is None:
                    continue
                if choice.get("account") == "skip" or feed_account.currency != "USD":
                    skipped.append(key)
                    continue
                account = choice.get("account") or self._new_account(choice, feed_account)
                if account not in ledger.accounts:
                    raise BudgetError(f"Choose an account for {feed_account.name}.")
                if any(link["account"] == account for link in links.values()):
                    raise BudgetError(f"Two bank accounts can't share {ledger.accounts[account]['name']}.")
                links[key] = {"account": account, "since": self._since(key, account)}
            self.state.update(links=links, skipped=skipped)
            results.extend(self._apply(self._feed))

        snapshot = json.dumps(self.state)
        try:
            self.budget._transaction(change)
        except Exception:
            self.state = json.loads(snapshot)
            raise
        self._record_outcome(self._feed)
        self._feed = None
        return {"results": results, "added": sum(r["added"] for r in results)}

    def _since(self, key: str, account: str) -> str | None:
        """Keep the cut-over of an existing link; a new one starts at the account's last day."""
        old = self.links.get(key)
        if old and old["account"] == account:
            return old["since"]
        days = [r["date"] for r in self.budget.ledger.rows if r["account"] == account]
        return max(days).isoformat() if days else None

    # ---- syncing

    def _apply(self, feed: Feed) -> list[dict]:
        ledger, results = self.budget.ledger, []
        by_key = {a.key: a for a in feed.accounts}
        for key, link in self.links.items():
            feed_account = by_key.get(key)
            info = ledger.accounts.get(link["account"])
            if feed_account is None or info is None:
                continue
            since = date.fromisoformat(link["since"]) if link["since"] else None
            added = ledger.merge_synced(link["account"], feed_account.rows, since)
            pin_balance(info, entered_balance(info["type"], feed_account.balance), feed_account.balance_date, live=True)
            results.append({"account": info["name"], "added": added})
        return results

    def _record_outcome(self, feed: Feed, synced: bool = True) -> None:
        """synced says the feed's rows were added. Only then does the last sync move on,
        because the next sync starts from it: a review that adds nothing mustn't count,
        or the days between the real last sync and the review would never arrive."""
        handled = {*self.links, *self.state.get("skipped", [])}
        self.state.update(problems=feed.problems,
                          unlinked=sum(a.key not in handled and a.currency == "USD" for a in feed.accounts))
        if synced:
            self.state["last_sync"] = datetime.now().isoformat(timespec="seconds")
        self._save()

    def sync(self) -> dict:
        """Only when asked. Everything since the last sync, however long ago, so nothing in
        between is missed. The first sync brings in what the feed has, about 90 days."""
        if not self.state.get("connected"):
            return {"added": 0, "skipped": True}
        now = datetime.now()
        last = datetime.fromisoformat(self.state["last_sync"]) if self.state.get("last_sync") else None
        if last and now - last < RECENT:
            return {"added": 0, "skipped": True}
        start = last.date() - timedelta(days=OVERLAP_DAYS) if last else now.date() - timedelta(days=simplefin.MAX_DAYS - 1)
        feed = self._fetch(self._access(), start, now.date())
        results = []

        def change():
            results.extend(self._apply(feed))

        self.budget._transaction(change)
        self._record_outcome(feed)
        return {"added": sum(r["added"] for r in results), "problems": feed.problems,
                "unlinked": self.state["unlinked"]}

    # ---- leaving

    def forget_account(self, account: str) -> None:
        """A removed account stops syncing, and isn't brought back by the next sync."""
        keys = [key for key, link in self.links.items() if link["account"] == account]
        if keys:
            for key in keys:
                del self.links[key]
            self.state["skipped"] = self.state.get("skipped", []) + keys
            self._save()

    def disconnect(self) -> None:
        """Your transactions stay. Only the connection and its settings go."""
        credentials.forget(self.home)
        self.state, self._feed = {}, None
        self.path.unlink(missing_ok=True)
        for info in self.budget.ledger.accounts.values():
            anchor = info.get("balance_anchor")
            if anchor:
                anchor.pop("live", None)
        self.budget.ledger.save_accounts()
