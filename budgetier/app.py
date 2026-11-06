"""The desktop window: the dashboard page plus native file dialogs."""
from __future__ import annotations

import ctypes
import logging
import msvcrt
import os
import sys
from functools import wraps
from pathlib import Path

import webview

from .service import Budget, BudgetError, app_home

log = logging.getLogger("budgetier")


def _alert(text: str) -> None:
    ctypes.windll.user32.MessageBoxW(None, text, "Budgetier", 0x10)


def _reply(method):
    """Everything the page calls returns {ok, ...}, so errors reach the screen."""
    @wraps(method)
    def call(self, *args):
        try:
            return {"ok": True, **(method(self, *args) or {})}
        except BudgetError as e:
            return {"ok": False, "error": str(e)}
        except Exception:
            log.exception("%s failed", method.__name__)
            return {"ok": False, "error": "Something went wrong. Your data wasn't changed. "
                                          f"Details are in {self._budget.home / 'logs'}."}
    return call


class Api:
    """Exposed to the page. Underscored names are hidden from it."""

    def __init__(self, budget: Budget):
        self._budget = budget
        self._window = None

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
        os.startfile(self._budget.home)


def _hold_single_instance(home: Path):
    """Two windows would each overwrite the other's saves."""
    lock = (home / "app.lock").open("a+")
    try:
        msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        return None
    return lock


def main() -> int:
    home = app_home()
    home.mkdir(parents=True, exist_ok=True)
    (home / "logs").mkdir(exist_ok=True)
    logging.basicConfig(filename=home / "logs" / "app.log", level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    lock = _hold_single_instance(home)
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
        webview.start(gui="edgechromium", private_mode=False, storage_path=str(home / "webview"))
    except Exception:
        log.exception("startup failed")
        _alert(f"Budgetier couldn't start. Details are in {home / 'logs' / 'app.log'}.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
