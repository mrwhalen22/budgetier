"""Where your data lives, and how it reaches the disk without being damaged."""
from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path

if sys.platform == "win32":
    import msvcrt
else:
    import fcntl


class BudgetError(Exception):
    """A problem to show the person, in words they can act on."""


class DataError(Exception):
    """A saved file can't be read. The text says which one and what to do."""


class Locked(DataError):
    """An encrypted file, read before the passcode was given."""


_vault = None  # the open vault, while the data folder is encrypted and unlocked


def use_vault(vault) -> None:
    """From now on, read and write the vault's folder through it. None: no encryption."""
    global _vault
    _vault = vault


def open_vault():
    return _vault


def app_home() -> Path:
    """User data lives here, not beside the program: ordinary programs can't write to
    Program Files, and an update must never touch your history."""
    override = os.environ.get("BUDGETIER_HOME")
    if override:
        return Path(override)
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Budgetier"
    if sys.platform == "linux":
        return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / "Budgetier"
    return Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "Budgetier"


def hold_lock(home: Path):
    """Only one program may hold your data at a time: each would overwrite the other's
    saves. Returns the open lock, or None if something else has it."""
    lock = (home / "app.lock").open("a+")
    try:
        if sys.platform == "win32":
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        lock.close()
        return None
    return lock


def read_bytes(path: Path) -> bytes:
    """A file's contents, decrypted if it's encrypted. Either kind can be read, so a folder
    partway through being encrypted or decrypted still opens."""
    from .vault import MAGIC, WrongKey
    raw = Path(path).read_bytes()
    if not raw.startswith(MAGIC):
        return raw
    if _vault is None:
        raise Locked(f"{Path(path).name} is encrypted, and Budgetier wasn't given the passcode.")
    try:
        return _vault.decrypt(raw)
    except WrongKey as e:
        raise DataError(f"{Path(path).name} in your data folder can't be decrypted: it may be damaged. Put back "
                        "its .bak copy, or a backup, and open Budgetier again.") from e


def read_text(path: Path) -> str:
    """Read a file a person may have edited. Excel saves CSV in the old Windows encoding,
    or as UTF-8 with a marker at the start, and neither should stop the app."""
    raw = read_bytes(path)
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return raw.decode("cp1252", errors="replace")


def write_files(files: dict[Path, str | bytes]) -> None:
    """Save files that belong together. Each is written in full beside its target and only
    then swapped in, so a crash or a full disk leaves the old versions intact. In an
    encrypted folder, each is encrypted on the way."""
    written = {}
    try:
        for path, text in files.items():
            data = text.encode("utf-8") if isinstance(text, str) else text
            if _vault is not None and _vault.covers(path):
                data = _vault.encrypt(data)
            written[path] = path.with_name(path.name + ".tmp")
            with written[path].open("wb") as f:
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
        for path, temp in written.items():
            os.replace(temp, path)
    finally:
        for temp in written.values():
            temp.unlink(missing_ok=True)


def copy_in(source: Path, target: Path) -> None:
    """A copy of a file from outside, kept in the data folder: encrypted, if the folder is."""
    write_files({target: Path(source).read_bytes()})


def _replace(path: Path, data: bytes) -> None:
    """Swap a file's contents for these, all or nothing, keeping its date."""
    stat = path.stat()
    temp = path.with_name(path.name + ".tmp")
    try:
        with temp.open("wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp, path)
        os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    finally:
        temp.unlink(missing_ok=True)


def _files(vault) -> list[Path]:
    return sorted(p for p in vault.home.rglob("*") if p.is_file() and vault.covers(p))


def seal_folder(vault) -> int:
    """Encrypt every file the vault covers that isn't yet. One at a time, each all or nothing,
    so stopping partway leaves a folder that still opens. Returns how many it encrypted."""
    from .vault import MAGIC
    done = 0
    for path in _files(vault):
        raw = path.read_bytes()
        if not raw.startswith(MAGIC):
            _replace(path, vault.encrypt(raw))
            done += 1
    return done


def unseal_folder(vault) -> int:
    """Decrypt every encrypted file, the same careful way. Returns how many it decrypted."""
    from .vault import MAGIC
    done = 0
    for path in _files(vault):
        raw = path.read_bytes()
        if raw.startswith(MAGIC):
            _replace(path, vault.decrypt(raw))
            done += 1
    return done


def unique_path(folder: Path, name: str) -> Path:
    """A path in folder for this file name that won't overwrite anything."""
    target = folder / name
    if target.exists():
        target = folder / f"{Path(name).stem}.{datetime.now():%Y%m%d-%H%M%S-%f}{Path(name).suffix}"
    return target
