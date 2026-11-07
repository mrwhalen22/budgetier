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


def read_text(path: Path) -> str:
    """Read a file a person may have edited. Excel saves CSV in the old Windows encoding,
    or as UTF-8 with a marker at the start, and neither should stop the app."""
    raw = path.read_bytes()
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return raw.decode("cp1252", errors="replace")


def write_files(files: dict[Path, str]) -> None:
    """Save files that belong together. Each is written in full beside its target and only
    then swapped in, so a crash or a full disk leaves the old versions intact."""
    written = {}
    try:
        for path, text in files.items():
            written[path] = path.with_name(path.name + ".tmp")
            with written[path].open("w", newline="", encoding="utf-8") as f:
                f.write(text)
                f.flush()
                os.fsync(f.fileno())
        for path, temp in written.items():
            os.replace(temp, path)
    finally:
        for temp in written.values():
            temp.unlink(missing_ok=True)


def unique_path(folder: Path, name: str) -> Path:
    """A path in folder for this file name that won't overwrite anything."""
    target = folder / name
    if target.exists():
        target = folder / f"{Path(name).stem}.{datetime.now():%Y%m%d-%H%M%S-%f}{Path(name).suffix}"
    return target
