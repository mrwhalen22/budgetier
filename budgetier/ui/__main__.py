"""Open Budgetier on another data folder, such as made-up data, for development.

    python -m budgetier.ui --home samples/demo
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ..app import main as open_app


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m budgetier.ui", description=__doc__.splitlines()[0])
    parser.add_argument("--home", help="the data folder to open, instead of your own")
    args = parser.parse_args(argv)
    return open_app(Path(args.home) if args.home else None)


if __name__ == "__main__":
    sys.exit(main())
