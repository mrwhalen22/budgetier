"""The SimpleFIN access URL, which is a password: it can read your transactions.

It goes in Windows Credential Manager or the macOS Keychain, never in the data folder,
because people copy that folder to back it up. Each data folder has its own entry, so
trying the app on sample data can't touch the real connection.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import keyring

from .storage import BudgetError

SERVICE = "Budgetier"


class CredentialError(BudgetError):
    """The system's secure storage didn't work."""


def _name(home: Path) -> str:
    return "simplefin-" + hashlib.sha256(str(Path(home).resolve()).encode()).hexdigest()[:16]


def _failed(e: Exception) -> CredentialError:
    return CredentialError("This computer's secure storage couldn't be used, so the bank connection "
                           f"can't be kept safely ({type(e).__name__}).")


def backend() -> str:
    return type(keyring.get_keyring()).__name__


def check(home: Path) -> None:
    """Prove storage works before spending a setup token, which only works once."""
    probe = _name(home) + "-check"
    try:
        keyring.set_password(SERVICE, probe, "check")
        stored = keyring.get_password(SERVICE, probe)
        keyring.delete_password(SERVICE, probe)
    except Exception as e:
        raise _failed(e) from e
    if stored != "check":
        raise CredentialError("This computer's secure storage didn't keep a test value, so the bank "
                              "connection can't be kept safely.")


def save(home: Path, secret: str) -> None:
    try:
        keyring.set_password(SERVICE, _name(home), secret)
    except Exception as e:
        raise _failed(e) from e


def load(home: Path) -> str | None:
    try:
        return keyring.get_password(SERVICE, _name(home))
    except Exception as e:
        raise _failed(e) from e


def forget(home: Path) -> None:
    try:
        if keyring.get_password(SERVICE, _name(home)) is not None:
            keyring.delete_password(SERVICE, _name(home))
    except Exception as e:
        raise _failed(e) from e
