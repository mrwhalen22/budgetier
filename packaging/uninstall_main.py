"""uninstall.exe: what Windows' Installed Apps page runs. Add --silent for no prompts."""
import ctypes
import sys
from pathlib import Path

import setup_main

YES_NO, QUESTION, INFO, ERROR, YES = 0x4, 0x20, 0x40, 0x10, 6


def ask(text: str, flags: int) -> int:
    return ctypes.windll.user32.MessageBoxW(None, text, "Uninstall Budgetier", flags)


def main() -> int:
    quiet = "--silent" in sys.argv
    setup_main.start_log()
    if not quiet and ask("Remove Budgetier from this PC?\n\nYour accounts and transactions stay in your "
                         "user folder, so reinstalling brings them back.", YES_NO | QUESTION) != YES:
        return 1
    try:
        setup_main.uninstall(Path(sys.executable).resolve().parent)
    except setup_main.SetupError as e:
        if not quiet:
            ask(str(e), ERROR)
        return 1
    if not quiet:
        ask("Budgetier was removed.", INFO)
    return 0


if __name__ == "__main__":
    sys.exit(main())
