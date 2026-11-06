"""Talking to a SimpleFIN server: https://www.simplefin.org/protocol.html

A setup token is a one-time, Base64-encoded claim URL. Claiming it returns an access URL
with credentials inside, so that URL is treated as a password: it's never logged or put
in an error message, and credentials are never sent over anything but verified HTTPS.
"""
from __future__ import annotations

import base64
import binascii
import json
import re
import socket
import ssl
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta

import certifi

from .parse import RawRow, parse_money
from .storage import BudgetError

TIMEOUT = 45
MAX_DAYS = 90  # the longest date range the server accepts in one request
USER_AGENT = "Budgetier (personal budgeting app)"  # the server's firewall refuses Python's default


class SimpleFinError(BudgetError):
    """Worded for the person; it never contains the access URL."""


@dataclass
class FeedAccount:
    key: str
    connection: str
    name: str
    currency: str
    balance: int
    balance_date: date
    rows: list[RawRow] = field(default_factory=list)


@dataclass
class Feed:
    accounts: list[FeedAccount] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)


class _NoRedirects(urllib.request.HTTPRedirectHandler):
    """urllib would repeat the password header to wherever a redirect points."""

    def redirect_request(self, *args, **kwargs):
        return None


def tls_context() -> ssl.SSLContext:
    """Certificates come with the app: a packaged Mac app can't rely on the system's."""
    return ssl.create_default_context(cafile=certifi.where())


def certificate_count() -> int:
    return len(tls_context().get_ca_certs())


def _opener():
    return urllib.request.build_opener(_NoRedirects, urllib.request.HTTPSHandler(context=tls_context()))


def _clean(text) -> str:
    """Server text ends up on screen, so it's kept short and printable."""
    return re.sub(r"[\x00-\x20\x7f]+", " ", str(text)).strip()[:300]


def _require_https(url: str) -> urllib.parse.SplitResult:
    parts = urllib.parse.urlsplit(url)
    if parts.scheme != "https" or not parts.hostname:
        raise SimpleFinError("That doesn't look like a SimpleFIN connection, so it wasn't used.")
    return parts


def claim_url(token: str) -> str:
    text = re.sub(r"\s+", "", token or "")
    if not text:
        raise SimpleFinError("Paste your SimpleFIN setup token.")
    try:
        url = base64.b64decode(text + "=" * (-len(text) % 4), validate=True).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError) as e:
        raise SimpleFinError("That isn't a SimpleFIN setup token. Copy the whole token and try again.") from e
    _require_https(url)
    return url


def _blocked(e: urllib.error.HTTPError) -> bool:
    """A firewall's refusal also arrives as 403, but says nothing about the token."""
    return e.read(200).decode("utf-8", "replace").lstrip().lower().startswith("error code")


def _firewall() -> SimpleFinError:
    return SimpleFinError("SimpleFIN's firewall turned this request away before it reached your account, so "
                          "nothing was used. Try again later, and update Budgetier if it keeps happening.")


def _unreachable(e: Exception) -> SimpleFinError:
    return SimpleFinError(f"SimpleFIN couldn't be reached. Check your connection and try again. ({type(e).__name__})")


def claim(token: str) -> str:
    """Swap a setup token for an access URL. Works once, ever."""
    request = urllib.request.Request(claim_url(token), data=b"", method="POST",
                                     headers={"Content-Length": "0", "User-Agent": USER_AGENT})
    try:
        with _opener().open(request, timeout=TIMEOUT) as response:
            access = response.read().decode("utf-8").strip()
    except urllib.error.HTTPError as e:
        if e.code == 403 and _blocked(e):
            raise _firewall() from None
        if e.code == 403:
            raise SimpleFinError("That setup token doesn't exist or was already used. If you didn't use it, "
                                 "someone else may have: disable it on the SimpleFIN site, then make a new "
                                 "one.") from None
        raise SimpleFinError(f"SimpleFIN refused the setup token (error {e.code}).") from None
    except (urllib.error.URLError, TimeoutError, socket.timeout, ssl.SSLError) as e:
        raise _unreachable(e) from None
    _require_https(access)
    if not urllib.parse.urlsplit(access).username:
        raise SimpleFinError("SimpleFIN sent back something unexpected. Make a new setup token and try again.")
    return access


def _split_access(access: str) -> tuple[str, str]:
    """(URL without credentials, Authorization header)."""
    parts = _require_https(access)
    login = f"{urllib.parse.unquote(parts.username or '')}:{urllib.parse.unquote(parts.password or '')}"
    host = parts.hostname + (f":{parts.port}" if parts.port else "")
    base = urllib.parse.urlunsplit((parts.scheme, host, parts.path.rstrip("/"), "", ""))
    return base, "Basic " + base64.b64encode(login.encode()).decode()


def _epoch(day: date) -> int:
    return int(datetime(day.year, day.month, day.day, tzinfo=UTC).timestamp())


def _day(timestamp) -> date:
    return datetime.fromtimestamp(int(timestamp), UTC).date()


def _rows(account: dict, name: str, problems: list[str]) -> list[RawRow]:
    rows, unreadable = [], 0
    for item in account.get("transactions") or []:
        if item.get("pending") or not item.get("posted"):
            continue  # posts later, often changed; counting it now would double up
        cents = parse_money(str(item.get("amount", "")))
        if cents is None or not item.get("id"):
            unreadable += 1
            continue
        if cents:
            rows.append(RawRow(date=_day(item["posted"]), description=re.sub(r"\s+", " ", _clean(item.get("description", ""))),
                               cents=cents, sync_id=str(item["id"])))
    if unreadable:
        problems.append(f"{name}: skipped {unreadable} transaction(s) that couldn't be read.")
    return sorted(rows, key=lambda r: r.date)


def parse_feed(data: dict) -> Feed:
    feed = Feed()
    for item in data.get("errlist") or []:
        feed.problems.append(_clean(item.get("msg") or item.get("code") or "") if isinstance(item, dict) else _clean(item))
    if not feed.problems:
        feed.problems = [_clean(text) for text in data.get("errors") or []]
    names = {c.get("conn_id"): c.get("name") or c.get("org_name") for c in data.get("connections") or []}
    for account in data.get("accounts") or []:
        org = account.get("org") or {}
        connection = account.get("conn_id") or org.get("domain") or org.get("name") or ""
        name = _clean(account.get("name") or "Account")
        balance = parse_money(str(account.get("balance", "")))
        if not account.get("id") or balance is None:
            feed.problems.append(f"{name}: skipped because its details couldn't be read.")
            continue
        feed.accounts.append(FeedAccount(
            key=f"{connection}/{account['id']}", connection=_clean(names.get(connection) or org.get("name") or connection),
            name=name, currency=_clean(account.get("currency") or "USD"), balance=balance,
            balance_date=_day(account.get("balance-date") or 0), rows=_rows(account, name, feed.problems)))
    return feed


def fetch(access: str, start: date, end: date) -> Feed:
    """Transactions from start up to and including end, at most MAX_DAYS of them."""
    base, authorization = _split_access(access)
    query = urllib.parse.urlencode({"version": 2, "start-date": _epoch(start), "end-date": _epoch(end + timedelta(days=1))})
    request = urllib.request.Request(f"{base}/accounts?{query}",
                                     headers={"Authorization": authorization, "User-Agent": USER_AGENT})
    try:
        with _opener().open(request, timeout=TIMEOUT) as response:
            return parse_feed(json.loads(response.read().decode("utf-8")))
    except urllib.error.HTTPError as e:
        if e.code == 402:
            raise SimpleFinError("SimpleFIN says payment is needed. Check your SimpleFIN subscription.") from None
        if e.code == 403 and _blocked(e):
            raise _firewall() from None
        if e.code == 403:
            raise SimpleFinError("SimpleFIN refused the connection, so it may have been disabled. Disconnect "
                                 "here and connect again with a new setup token.") from None
        raise SimpleFinError(f"SimpleFIN had a problem (error {e.code}). Try again later.") from None
    except (urllib.error.URLError, TimeoutError, socket.timeout, ssl.SSLError) as e:
        raise _unreachable(e) from None
    except (ValueError, AttributeError, TypeError, KeyError) as e:
        raise SimpleFinError("SimpleFIN sent something unreadable. Try again later.") from e
