"""Open the Qt window, for development while the move to Qt is under way.

    python -m budgetier.ui              your own data
    python -m budgetier.ui --home DIR   another data folder, such as made-up data
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ..storage import app_home, hold_lock


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m budgetier.ui", description=__doc__.splitlines()[0])
    parser.add_argument("--home", help="the data folder to open, instead of your own")
    args = parser.parse_args(argv)
    home = Path(args.home) if args.home else app_home()
    home.mkdir(parents=True, exist_ok=True)
    lock = hold_lock(home)
    if lock is None:  # two windows on one folder would overwrite each other's saves
        print("Budgetier is already open on that data folder.", file=sys.stderr)
        return 1
    try:
        from ..service import Budget
        from .app import Window, application

        app = application()
        window = Window(Budget(home))
        window.show()
        return app.exec()
    finally:
        lock.close()


if __name__ == "__main__":
    sys.exit(main())
