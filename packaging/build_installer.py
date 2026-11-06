"""Build dist/BudgetierSetup.exe, the one file that installs Budgetier.

    .venv/Scripts/python packaging/build_installer.py

Run from any folder. Needs the packages in requirements-dev.txt.
"""
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUILD, DIST = ROOT / "build", ROOT / "dist"


def pyinstaller(spec: str, work: str, dist: Path = DIST) -> None:
    subprocess.run([sys.executable, "-m", "PyInstaller", str(ROOT / "packaging" / spec), "--noconfirm",
                    "--distpath", str(dist), "--workpath", str(BUILD / work)], check=True, cwd=ROOT)


def main() -> int:
    pyinstaller("Budgetier.spec", "app")
    pyinstaller("Uninstall.spec", "uninstall", BUILD / "uninstaller")

    app = DIST / "Budgetier"
    payload = BUILD / "payload.zip"
    with zipfile.ZipFile(payload, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(p for p in app.rglob("*") if p.is_file()):
            archive.write(path, path.relative_to(app))
        archive.write(BUILD / "uninstaller" / "uninstall.exe", "uninstall.exe")

    pyinstaller("Setup.spec", "setup")
    setup = DIST / "BudgetierSetup.exe"
    print(f"\nInstaller: {setup} ({setup.stat().st_size / 1_048_576:.0f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
