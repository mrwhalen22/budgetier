"""Open the built app on fake data and confirm it really works, then close it.

    python packaging/self_check.py

Run after build_installer.py. Every tab must draw and the page must reach the app. The
data folder has a space in its name, as the real one on macOS does.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEMO = ROOT / "samples" / "demo"
APP = {"darwin": ROOT / "dist" / "Budgetier.app" / "Contents" / "MacOS" / "Budgetier",
       "win32": ROOT / "dist" / "Budgetier" / "Budgetier.exe"}


def run(*args: object) -> None:
    subprocess.run([sys.executable, *map(str, args)], check=True, cwd=ROOT, stdin=subprocess.DEVNULL,
                   stdout=subprocess.DEVNULL)


def main() -> int:
    run(ROOT / "samples" / "make_samples.py")
    run("-m", "budgetier", "--home", DEMO)
    with tempfile.TemporaryDirectory() as folder:
        home, result = Path(folder) / "Budget Data", Path(folder) / "result.json"
        shutil.copytree(DEMO, home)
        env = {**os.environ, "BUDGETIER_HOME": str(home), "BUDGETIER_SELF_CHECK": str(result)}
        try:
            code = subprocess.run([APP[sys.platform]], env=env, timeout=120).returncode
        except subprocess.TimeoutExpired:
            code = "timed out"
        log = home / "logs" / "app.log"
        if log.exists():
            print(log.read_text(encoding="utf-8"))
        report = json.loads(result.read_text(encoding="utf-8")) if result.exists() else {"failed": ["no result"]}
    print(f"exit: {code}, report: {report}")
    good = code == 0 and report.get("api") == "function" and report.get("rows", 0) > 0 and not report["failed"]
    print("Self check passed." if good else "Self check FAILED.")
    return 0 if good else 1


if __name__ == "__main__":
    sys.exit(main())
