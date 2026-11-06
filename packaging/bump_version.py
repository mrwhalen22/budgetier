"""Raise the number in the VERSION file and print the new one.

    python packaging/bump_version.py patch|minor|major
"""
import re
import sys
from pathlib import Path

VERSION_FILE = Path(__file__).resolve().parents[1] / "VERSION"
PARTS = ("major", "minor", "patch")


def bump(version: str, part: str) -> str:
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise ValueError(f"VERSION should look like 1.2.3, not {version!r}")
    if part not in PARTS:
        raise ValueError(f"Choose one of {', '.join(PARTS)}, not {part!r}")
    major, minor, patch = (int(n) for n in version.split("."))
    return {"major": f"{major + 1}.0.0", "minor": f"{major}.{minor + 1}.0", "patch": f"{major}.{minor}.{patch + 1}"}[part]


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__, file=sys.stderr)
        return 2
    new = bump(VERSION_FILE.read_text(encoding="utf-8-sig").strip(), sys.argv[1])
    VERSION_FILE.write_text(new + "\n", encoding="utf-8", newline="\n")
    print(new)
    return 0


if __name__ == "__main__":
    sys.exit(main())
