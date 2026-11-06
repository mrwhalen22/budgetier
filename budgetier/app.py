"""The desktop window: the dashboard page plus native file dialogs."""
from __future__ import annotations

import ctypes
import json
import logging
import logging.handlers
import os
import subprocess
import sys
import threading
import time
from functools import wraps
from pathlib import Path

import webview

from . import credentials, simplefin
from .service import Budget, BudgetError
from .storage import DataError, app_home, hold_lock

log = logging.getLogger("budgetier")

# Run in the page by the self check: every tab must draw, and the app must be reachable.
SELF_CHECK = """JSON.stringify({
  api: typeof window.pywebview.api.save_budget,
  rows: TX.length,
  months: monthly(TX, MONTHS).map(m => [m.month, Math.round(m.income * 100), Math.round(m.spending * 100)]),
  failed: TABS.filter(t => { try { S.tab = t; render(); return false; } catch { return true; } }),
})"""


def _alert(text: str) -> None:
    if sys.platform == "win32":
        ctypes.windll.user32.MessageBoxW(None, text, "Budgetier", 0x10)
    else:
        subprocess.run(["osascript", "-e", "on run argv", "-e",
                        'display alert "Budgetier" message (item 1 of argv) as critical',
                        "-e", "end run", text], check=False)


def _show_folder(folder: Path) -> None:
    if sys.platform == "win32":
        os.startfile(folder)
    else:
        subprocess.run(["open", str(folder)], check=True)


def _reply(method):
    """Everything the page calls returns {ok, ...}, so errors reach the screen. Each call
    arrives on its own thread, so they take turns: a double click mustn't race itself."""
    @wraps(method)
    def call(self, *args):
        with self._turn:
            try:
                return {"ok": True, **(method(self, *args) or {})}
            except BudgetError as e:
                return {"ok": False, "error": str(e)}
            except Exception:
                log.exception("%s failed", method.__name__)
                return {"ok": False, "error": "Something went wrong, so that didn't finish. "
                                              f"Details are in {self._budget.home / 'logs'}."}
    return call


class Api:
    """Exposed to the page. Underscored names are hidden from it."""

    def __init__(self, budget: Budget):
        self._budget = budget
        self._window = None
        self._turn = threading.Lock()

    @_reply
    def pick_files(self):
        chosen = self._window.create_file_dialog(
            webview.FileDialog.OPEN, allow_multiple=True,
            file_types=("Bank files (*.csv;*.pdf)", "All files (*.*)"))
        return {"paths": list(chosen or [])}

    @_reply
    def inspect(self, paths):
        return self._budget.inspect(paths)

    @_reply
    def commit(self, answers):
        return {"results": self._budget.commit(answers)}

    @_reply
    def cancel(self):
        self._budget.cancel()

    @_reply
    def remove_import(self, key):
        return self._budget.remove_import(key)

    @_reply
    def remove_account(self, account):
        return self._budget.remove_account(account)

    @_reply
    def update_account(self, account, name, kind, balance, as_of):
        self._budget.update_account(account, name, kind, balance, as_of)

    @_reply
    def preview_rule(self, text, advanced=False):
        return self._budget.preview_rule(text, advanced)

    @_reply
    def save_rule(self, original, text, category, merchant, advanced=False):
        self._budget.save_rule(original, text, category, merchant, advanced)

    @_reply
    def delete_rule(self, line):
        self._budget.delete_rule(line)

    @_reply
    def save_budget(self, category, mode, value):
        self._budget.save_budget(category, mode, value)

    @_reply
    def delete_budget(self, category):
        self._budget.delete_budget(category)

    @_reply
    def connect_bank(self, token):
        return self._budget.sync.connect(token)

    @_reply
    def review_bank(self):
        return self._budget.sync.review()

    @_reply
    def link_bank(self, choices):
        return self._budget.sync.link(choices)

    @_reply
    def sync_bank(self, automatic=False):
        return self._budget.sync.sync(automatic)

    @_reply
    def disconnect_bank(self):
        self._budget.sync.disconnect()

    @_reply
    def export_workbook(self):
        chosen = self._window.create_file_dialog(
            webview.FileDialog.SAVE, save_filename="Budgetier.xlsx",
            file_types=("Excel workbook (*.xlsx)",))
        if not chosen:
            return {"saved": ""}
        path = chosen if isinstance(chosen, str) else chosen[0]
        self._budget.export_workbook(Path(path))
        return {"saved": path}

    @_reply
    def open_data_folder(self):
        _show_folder(self._budget.home)


def _self_check(window, result: str) -> None:
    """For automated builds, where nobody can look at the window: write down what the
    page reports, then close. packaging/self_check.py judges the result."""
    report, deadline = "", time.monotonic() + 60
    while not report and time.monotonic() < deadline:
        try:
            report = window.evaluate_js(SELF_CHECK)
        except Exception as e:
            report = ""
            log.info("self check not ready: %s", e)
            time.sleep(1)
    found = json.loads(report) if report else {"failed": ["page never answered"]}
    found.update(secure_store=credentials.backend(), certificates=simplefin.certificate_count())
    Path(result).write_text(json.dumps(found), encoding="utf-8")
    window.destroy()


def main() -> int:
    home = app_home()
    home.mkdir(parents=True, exist_ok=True)
    (home / "logs").mkdir(exist_ok=True)
    logging.basicConfig(handlers=[logging.handlers.RotatingFileHandler(
                            home / "logs" / "app.log", maxBytes=1_000_000, backupCount=2, encoding="utf-8")],
                        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    lock = hold_lock(home)
    if lock is None:
        _alert("Budgetier is already open.")
        return 1
    try:
        budget = Budget(home)
        page = budget.refresh()
        api = Api(budget)
        api._window = webview.create_window("Budgetier", url=page.as_uri(), js_api=api,
                                            width=1340, height=900, min_size=(900, 620),
                                            background_color="#101A17")
        check = os.environ.get("BUDGETIER_SELF_CHECK")
        webview.start(_self_check if check else None, (api._window, check) if check else None,
                      gui="edgechromium" if sys.platform == "win32" else None,
                      private_mode=False, storage_path=str(home / "webview"))
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


if __name__ == "__main__":
    sys.exit(main())
