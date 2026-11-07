"""Finding out about a new version and fetching it.

The app asks GitHub for the latest release and sends nothing else. Nothing is downloaded
until someone chooses to update, and a download must match the release's checksums before
it's run. Checksums catch a damaged download, not a tampered release: they come from the
same place as the installer, so that protection would have to come from code signing.
"""
from __future__ import annotations

import ctypes
import hashlib
import json
import logging
import platform
import re
import shutil
import subprocess
import sys
import urllib.request
from dataclasses import dataclass
from http.client import HTTPException
from pathlib import Path

from .simplefin import USER_AGENT, tls_context
from .storage import BudgetError, write_files

log = logging.getLogger("budgetier")

REPO = "mrwhalen22/budgetier"
LATEST = f"https://api.github.com/repos/{REPO}/releases/latest"
DOWNLOADS = f"https://github.com/{REPO}/releases/download/"
CHECKSUMS = "SHA256SUMS.txt"
TIMEOUT = 15
MOST_BYTES = 500_000_000
CHUNK = 1_048_576
UPDATE_FLAG = "--update"  # packaging/setup_main.py waits for the app to close, then reopens it


class UpdateError(BudgetError):
    pass


@dataclass(frozen=True)
class Release:
    version: str
    installer: str
    url: str
    checksums: str


class _HttpsOnly(urllib.request.HTTPRedirectHandler):
    """GitHub sends downloads to another host, which is fine as long as it stays encrypted."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not newurl.startswith("https://"):
            raise UpdateError("The download tried to leave a secure connection, so it was stopped.")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _open(url: str, timeout: int = TIMEOUT):
    opener = urllib.request.build_opener(_HttpsOnly, urllib.request.HTTPSHandler(context=tls_context()))
    return opener.open(urllib.request.Request(url, headers={"User-Agent": USER_AGENT}), timeout=timeout)


def installer_name() -> str | None:
    """The release file for this computer. These names come from packaging/build_installer.py."""
    if sys.platform == "win32":
        return "Budgetier-Windows.exe"
    if sys.platform == "darwin":
        return {"arm64": "Budgetier-macOS-Apple-Silicon.dmg", "x86_64": "Budgetier-macOS-Intel.dmg"}.get(platform.machine())
    if sys.platform == "linux" and platform.machine() == "x86_64":
        return "Budgetier-Linux.tar.gz"
    return None


def parts(version: str) -> tuple[int, ...] | None:
    found = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)", version.strip())
    return tuple(int(n) for n in found.groups()) if found else None


def is_newer(latest: str, current: str) -> bool:
    new, old = parts(latest), parts(current)
    return bool(new and old and new > old)


def latest_release() -> Release | None:
    """What GitHub says is newest, or None if it doesn't include a file for this computer."""
    name = installer_name()
    try:
        with _open(LATEST) as reply:
            data = json.load(reply)
        files = {a["name"]: a["browser_download_url"] for a in data["assets"]}
        version = data["tag_name"].lstrip("v")
    except (OSError, HTTPException, ValueError, KeyError, TypeError) as e:
        raise UpdateError("Couldn't check for updates. Try again when you're online.") from e
    urls = (files.get(name), files.get(CHECKSUMS))
    if not all(url and url.startswith(DOWNLOADS) for url in urls):
        return None
    return Release(version, name, *urls)


def checksum_for(text: str, name: str) -> str:
    """Reads sha256sum's output, which marks a binary file with a * before its name."""
    for line in text.splitlines():
        found = re.fullmatch(r"([0-9a-fA-F]{64}) [ *](.+)", line.strip())
        if found and found.group(2) == name:
            return found.group(1).lower()
    raise UpdateError("This update has no checksum, so it wasn't installed.")


def _run_installer(path: Path) -> None:
    if sys.platform == "win32":
        # ShellExecute, because plain process creation can't show the permission prompt.
        result = ctypes.windll.shell32.ShellExecuteW(None, "runas", str(path), UPDATE_FLAG, None, 1)
        if result <= 32:
            raise UpdateError("The update didn't start, so nothing changed. Windows needs your permission to install it.")
    else:
        subprocess.run(["open" if sys.platform == "darwin" else "xdg-open", str(path)], check=True)


class Updater:
    def __init__(self, home: Path, version: str):
        self.settings_path = Path(home) / "updates.json"
        self.folder = Path(home) / "updates"
        self.version = version
        self.release: Release | None = None

    @property
    def supported(self) -> bool:
        """Only an installed copy can be replaced; running from source has nothing to update."""
        return bool(getattr(sys, "frozen", False) and installer_name() and parts(self.version))

    @property
    def automatic(self) -> bool:
        try:
            return json.loads(self.settings_path.read_text(encoding="utf-8"))["automatic"] is not False
        except (OSError, ValueError, KeyError, TypeError):
            return True

    def set_automatic(self, on: bool) -> None:
        write_files({self.settings_path: json.dumps({"automatic": bool(on)}) + "\n"})

    def status(self) -> dict:
        return {"supported": self.supported, "automatic": self.automatic, "system": sys.platform}

    def check(self, by_hand: bool = False) -> dict:
        """A startup check stays quiet about failing: being offline isn't worth a message."""
        nothing = {"available": False, "version": "", "reopens": sys.platform == "win32"}
        if not self.supported or not (by_hand or self.automatic):
            return nothing
        try:
            release = latest_release()
        except UpdateError as e:
            log.info("update check failed: %s", e.__cause__)
            if by_hand:
                raise
            return nothing
        if not release or not is_newer(release.version, self.version):
            self.release = None
            return nothing
        self.release = release
        return {**nothing, "available": True, "version": release.version}

    def _fetch(self, release: Release) -> Path:
        with _open(release.checksums) as reply:
            expected = checksum_for(reply.read(CHUNK).decode("utf-8", "replace"), release.installer)
        self.folder.mkdir(parents=True, exist_ok=True)
        path, partial = self.folder / release.installer, self.folder / f"{release.installer}.part"
        digest, size = hashlib.sha256(), 0
        try:
            with _open(release.url, 120) as reply, partial.open("wb") as out:
                while chunk := reply.read(CHUNK):
                    size += len(chunk)
                    if size > MOST_BYTES:
                        raise UpdateError("This update is much larger than expected, so it wasn't installed.")
                    digest.update(chunk)
                    out.write(chunk)
            if digest.hexdigest() != expected:
                raise UpdateError("The download didn't match its checksum, so it wasn't installed. Try again.")
            partial.replace(path)
        finally:
            partial.unlink(missing_ok=True)
        return path

    def install(self) -> dict:
        if not self.release:
            raise UpdateError("Check for updates first.")
        try:
            _run_installer(self._fetch(self.release))
        except (OSError, HTTPException, subprocess.CalledProcessError) as e:
            log.exception("update failed")
            raise UpdateError("Couldn't download the update. Nothing changed, so try again later.") from e
        return {"closing": sys.platform == "win32"}

    def clean(self) -> None:
        """An installer that already ran is just taking up space."""
        shutil.rmtree(self.folder, ignore_errors=True)
