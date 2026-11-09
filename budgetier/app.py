"""The desktop app: one Qt window on your data folder."""
from __future__ import annotations

import json
import logging
import logging.handlers
import os
import sys
import traceback
from pathlib import Path

from . import credentials, simplefin, vault, views
from .storage import DataError, app_home, hold_lock

log = logging.getLogger("budgetier")
FINISH_WAIT = 60  # seconds: longer than a sync's slowest request, so leaving can't cut one short


def _alert(text: str) -> None:
    from PySide6.QtWidgets import QMessageBox

    from .ui.app import application
    application()
    QMessageBox.critical(None, "Budgetier", text)


def self_check(window, result: str) -> None:
    """For automated builds, where nobody can look at the window: draw every tab, write down
    what the window shows, then close. packaging/self_check.py judges the result."""
    from .ui.app import TABS
    failed = []
    for tab in TABS:
        try:
            window.show_tab(tab)
            window.grab()
        except Exception:
            log.exception("self check: %s didn't draw", tab)
            failed.append(tab)
    txns = window.snapshot.txns
    months = sorted({t.month for t in txns})
    report = {"window": type(window).__name__, "rows": len(txns), "failed": failed,
              "months": [[m.month, m.income, m.spending] for m in views.monthly(txns, months)],
              "secure_store": credentials.backend(), "certificates": simplefin.certificate_count(),
              "encryption": vault.self_test()}
    Path(result).write_text(json.dumps(report), encoding="utf-8")
    window.close()


def main(home: Path | None = None) -> int:
    home = Path(home) if home else app_home()
    home.mkdir(parents=True, exist_ok=True)
    (home / "logs").mkdir(exist_ok=True)
    logging.basicConfig(handlers=[logging.handlers.RotatingFileHandler(
                            home / "logs" / "app.log", maxBytes=1_000_000, backupCount=2, encoding="utf-8")],
                        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    lock = hold_lock(home)
    if lock is None:  # two windows on one folder would overwrite each other's saves
        _alert("Budgetier is already open.")
        return 1
    try:
        from PySide6.QtCore import QTimer

        from .service import Budget
        from .ui import locking
        from .ui.app import Window, application
        app = application()
        if not locking.unlock_at_start(home):  # encrypted, and you chose not to open it
            return 0
        budget = Budget(home)
        budget.updates.clean()
        window = Window(budget)
        check = os.environ.get("BUDGETIER_SELF_CHECK")
        if check:
            QTimer.singleShot(0, lambda: self_check(window, check))
        window.show()
        app.exec()
        window.runner.pool.waitForDone(FINISH_WAIT * 1000)  # anything still saving finishes first
    except DataError as e:
        log.error("saved data can't be read: %s", e)
        _alert(str(e))
        return 1
    except Exception:
        log.exception("startup failed")
        _alert(f"Budgetier couldn't start. Details are in {home / 'logs' / 'app.log'}.")
        return 1
    finally:
        lock.close()
    return 0


def run() -> None:
    try:
        code = main()
    except Exception:  # the log may not exist yet, so this is the only word on what went wrong
        traceback.print_exc()
        code = 1
    logging.shutdown()
    sys.exit(code)


if __name__ == "__main__":
    run()
