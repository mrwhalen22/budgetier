"""Encrypting your data folder with a passcode.

Every file Budgetier keeps about your money is encrypted on the disk: the ledger, accounts,
rules, budgets, goals, notes, bank sync's settings, the window's settings, the backups, and
the copies of the files you imported. Only this vault's own header, the program's lock file
and its log stay readable, and none of those hold financial details.

How the keys fit together:
- One random data key encrypts the files, with AES-256-GCM, which also notices any change
  to a file, so a damaged or tampered one is refused rather than misread.
- Your passcode doesn't encrypt them itself. It's stretched with scrypt, slowly on purpose,
  into a key that locks the data key away in vault.json. So changing the passcode only
  locks the same data key again, and nothing has to be rewritten.
- A recovery key, shown once when encryption is turned on, locks the data key away a second
  time. With either one, the data key comes back. With neither, nobody can read the files,
  including us: there's no way around it, which is the point.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

HEADER = "vault.json"
MAGIC = b"BUDGETIER-ENCRYPTED-1\n"  # at the start of every encrypted file
_AAD = b"budgetier data"
SCRYPT = {"n": 2 ** 15, "r": 8, "p": 1}  # about a tenth of a second here; every guess costs the same
SHORTEST = 6  # characters in a passcode
RECOVERY_GROUPS = 5
# Kept readable: the header itself, what says the folder is in use, the log, and what's
# only ever on the way to being written.
PLAIN = {HEADER, "app.lock", "updates.json"}
# output: workbooks you asked to export, to open elsewhere. inbox: files waiting for the
# command line to import them, which moves them into imported/, encrypted.
PLAIN_FOLDERS = {"logs", "updates", "output", "inbox"}


class WrongKey(Exception):
    """The passcode or recovery key doesn't open this vault."""


def _stretch(secret: str, salt: bytes, settings: dict) -> bytes:
    return hashlib.scrypt(secret.encode("utf-8"), salt=salt, n=settings["n"], r=settings["r"], p=settings["p"],
                          maxmem=128 * 1024 * 1024, dklen=32)


def _lock_away(data_key: bytes, secret: str) -> dict:
    salt, nonce = secrets.token_bytes(16), secrets.token_bytes(12)
    sealed = AESGCM(_stretch(secret, salt, SCRYPT)).encrypt(nonce, data_key, _AAD)
    return {"salt": salt.hex(), "nonce": nonce.hex(), "key": sealed.hex(), **SCRYPT}


def _bring_back(locked: dict, secret: str) -> bytes:
    try:
        settings = {k: int(locked[k]) for k in ("n", "r", "p")}
        key = _stretch(secret, bytes.fromhex(locked["salt"]), settings)
        return AESGCM(key).decrypt(bytes.fromhex(locked["nonce"]), bytes.fromhex(locked["key"]), _AAD)
    except (InvalidTag, KeyError, TypeError, ValueError) as e:
        raise WrongKey from e


def normal_recovery(text: str) -> str:
    """A recovery key as typed: dashes, spaces and case don't matter."""
    return "".join(ch for ch in text.upper() if ch.isalnum())


def new_recovery_key() -> str:
    """25 letters and digits in five groups: 125 bits, too many to guess, few enough to copy."""
    text = base64.b32encode(secrets.token_bytes(16)).decode("ascii")[:RECOVERY_GROUPS * 5]
    return "-".join(text[i:i + 5] for i in range(0, len(text), 5))


def header_path(home: Path) -> Path:
    return Path(home) / HEADER


def read_header(home: Path) -> dict | None:
    """The vault's header, or None when the folder isn't encrypted."""
    path = header_path(home)
    if not path.exists():
        return None
    try:
        header = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise WrongKey("vault.json can't be read") from e
    return header if isinstance(header, dict) and isinstance(header.get("passcode"), dict) else None


def _write_header(home: Path, header: dict) -> None:
    path = header_path(home)
    temp = path.with_name(path.name + ".tmp")
    with temp.open("w", encoding="utf-8") as f:
        f.write(json.dumps(header, indent=2, sort_keys=True))
        f.flush()
        os.fsync(f.fileno())
    os.replace(temp, path)


class Vault:
    """An open vault: what encrypts and decrypts the files under home."""

    def __init__(self, home: Path, data_key: bytes):
        self.home = Path(home).resolve()
        self._cipher = AESGCM(data_key)
        self._data_key = data_key

    def covers(self, path: Path) -> bool:
        try:
            inside = Path(path).resolve().relative_to(self.home)
        except ValueError:
            return False
        parts = inside.parts
        return bool(parts) and parts[-1] not in PLAIN and parts[0] not in PLAIN_FOLDERS and not parts[-1].endswith(".tmp")

    def encrypt(self, data: bytes) -> bytes:
        nonce = secrets.token_bytes(12)
        return MAGIC + nonce + self._cipher.encrypt(nonce, data, _AAD)

    def decrypt(self, data: bytes) -> bytes:
        body = data[len(MAGIC):]
        try:
            return self._cipher.decrypt(body[:12], body[12:], _AAD)
        except InvalidTag as e:
            raise WrongKey("this file is damaged, or was encrypted with another key") from e

    # ---- the header

    def change_passcode(self, passcode: str) -> None:
        header = read_header(self.home) or {}
        header["passcode"] = _lock_away(self._data_key, passcode)
        _write_header(self.home, header)

    def new_recovery_key(self) -> str:
        key = new_recovery_key()
        header = read_header(self.home) or {}
        header["recovery"] = _lock_away(self._data_key, normal_recovery(key))
        _write_header(self.home, header)
        return key

    def set_option(self, **options) -> None:
        """Settings the lock screen needs before anything is decrypted, like when to lock."""
        header = read_header(self.home) or {}
        header.update(options)
        _write_header(self.home, header)


def create(home: Path, passcode: str) -> tuple[Vault, str]:
    """A new vault for home: its header only. The files are encrypted afterwards, one at a time,
    which is safe to stop partway, since a reader takes either kind."""
    data_key = AESGCM.generate_key(bit_length=256)
    recovery = new_recovery_key()
    _write_header(home, {"version": 1, "passcode": _lock_away(data_key, passcode),
                         "recovery": _lock_away(data_key, normal_recovery(recovery))})
    return Vault(home, data_key), recovery


def open_with(home: Path, passcode: str) -> Vault:
    header = read_header(home)
    if header is None:
        raise WrongKey("this folder isn't encrypted")
    return Vault(home, _bring_back(header["passcode"], passcode))


def open_with_recovery(home: Path, recovery: str) -> Vault:
    header = read_header(home)
    if header is None or not isinstance(header.get("recovery"), dict):
        raise WrongKey("there's no recovery key for this folder")
    return Vault(home, _bring_back(header["recovery"], normal_recovery(recovery)))


def check(home: Path, passcode: str) -> bool:
    try:
        open_with(home, passcode)
    except WrongKey:
        return False
    return True


def self_test() -> bool:
    """For the packaged app's own check: the cipher is there and works."""
    vault = Vault(Path.cwd(), AESGCM.generate_key(bit_length=256))
    return vault.decrypt(vault.encrypt(b"budgetier")) == b"budgetier"
