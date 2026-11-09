"""Open the built app on fake data and confirm it really works, then close it.

    python packaging/self_check.py

Run after build_installer.py. Every tab must draw, and the monthly totals the window shows
must match the workbook's to the cent. Bank sync's packaged parts must be present too:
secure storage, and certificates for HTTPS. The data folder has a space in its name, as the
real one on macOS does. On Linux with no screen, Qt draws offscreen.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from budgetier import analyze  # noqa: E402
from budgetier.ledger import Ledger  # noqa: E402

DEMO = ROOT / "samples" / "demo"
APP = {"darwin": ROOT / "dist" / "Budgetier.app" / "Contents" / "MacOS" / "Budgetier",
       "win32": ROOT / "dist" / "Budgetier" / "Budgetier.exe", "linux": ROOT / "dist" / "Budgetier" / "Budgetier"}


def run(*args: object) -> None:
    subprocess.run([sys.executable, *map(str, args)], check=True, cwd=ROOT, stdin=subprocess.DEVNULL,
                   stdout=subprocess.DEVNULL)


def python_totals() -> list[list]:
    """What the workbook reports for the demo data. The window works this out separately."""
    ledger = Ledger(DEMO)
    rows = analyze.classify(ledger.rows, ledger.accounts, analyze.load_rules(DEMO / "rules.csv"))
    return [[m["month"], m["income"], m["spending"]] for m in analyze.monthly_summary(rows)]


def main() -> int:
    run(ROOT / "samples" / "make_samples.py")
    run("-m", "budgetier", "--home", DEMO)
    with tempfile.TemporaryDirectory() as folder:
        home, result = Path(folder) / "Budget Data", Path(folder) / "result.json"
        shutil.copytree(DEMO, home)
        env = {**os.environ, "BUDGETIER_HOME": str(home), "BUDGETIER_SELF_CHECK": str(result)}
        if sys.platform == "linux" and not os.environ.get("DISPLAY"):
            env["QT_QPA_PLATFORM"] = "offscreen"
        try:
            code = subprocess.run([APP[sys.platform]], env=env, timeout=120).returncode
        except subprocess.TimeoutExpired:
            code = "timed out"
        log = home / "logs" / "app.log"
        if log.exists():
            print(log.read_text(encoding="utf-8"))
        report = json.loads(result.read_text(encoding="utf-8")) if result.exists() else {"failed": ["no result"]}
    print(f"exit: {code}, report: {report}")
    totals = python_totals()
    matched = report.get("months") == totals
    if not matched:
        print(f"Totals differ. Python: {totals}")
    syncing = report.get("certificates", 0) > 0 and "fail" not in report.get("secure_store", "fail").lower()
    good = (code == 0 and report.get("window") == "Window" and report.get("rows", 0) > 0 and not report["failed"]
            and matched and syncing and report.get("encryption") is True)
    print("Self check passed." if good else "Self check FAILED.")
    return 0 if good else 1


if __name__ == "__main__":
    sys.exit(main())
