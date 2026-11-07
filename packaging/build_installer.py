"""Build the one file that installs Budgetier: dist/Budgetier-Windows.exe on Windows, a
disk image on macOS, or dist/Budgetier-Linux.tar.gz on Linux. A build only works for the
system it was made on.

    python packaging/build_installer.py

Run from any folder. Needs the packages in requirements-dev.txt, and on Linux what
packaging/linux_deps.sh installs.
"""
import platform
import shutil
import subprocess
import sys
import tarfile
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUILD, DIST = ROOT / "build", ROOT / "dist"
MAC_NAMES = {"arm64": "Budgetier-macOS-Apple-Silicon.dmg", "x86_64": "Budgetier-macOS-Intel.dmg"}
LINUX_NAME = "Budgetier-Linux.tar.gz"
# Far under what the app will download as an update. Going over means something the app
# doesn't use was bundled, as when the Linux download held all of Qt and reached 300 MB.
MOST_MB = 200


def pyinstaller(spec: str, work: str, dist: Path = DIST) -> None:
    subprocess.run([sys.executable, "-m", "PyInstaller", str(ROOT / "packaging" / spec), "--noconfirm",
                    "--distpath", str(dist), "--workpath", str(BUILD / work)], check=True, cwd=ROOT)


def report(installer: Path) -> int:
    size = installer.stat().st_size / 1_048_576
    print(f"\nInstaller: {installer} ({size:.0f} MB)")
    if size > MOST_MB:
        raise SystemExit(f"{installer.name} is {size:.0f} MB, over the {MOST_MB} MB limit. Check what the build "
                         "bundled: it's likely something the app doesn't use.")
    return 0


def disk_image(folder: Path, image: Path) -> None:
    """hdiutil sometimes reports the disk busy on a fresh machine, and then works."""
    command = ["hdiutil", "create", "-volname", "Budgetier", "-srcfolder", str(folder),
               "-format", "UDZO", "-ov", str(image)]
    for attempt in range(4):
        if attempt:
            time.sleep(5)
        if subprocess.run(command).returncode == 0:
            return
    raise SystemExit("hdiutil couldn't make the disk image.")


def build_mac() -> int:
    pyinstaller("Budgetier.spec", "app")
    app = DIST / "Budgetier.app"
    subprocess.run(["codesign", "--verify", "--deep", "--strict", str(app)], check=True)

    stage = BUILD / "dmg"
    shutil.rmtree(stage, ignore_errors=True)
    stage.mkdir(parents=True)
    subprocess.run(["ditto", str(app), str(stage / app.name)], check=True)
    (stage / "Applications").symlink_to("/Applications")
    image = DIST / MAC_NAMES[platform.machine()]
    disk_image(stage, image)
    return report(image)


def build_linux() -> int:
    pyinstaller("Budgetier.spec", "app")
    archive = DIST / LINUX_NAME
    with tarfile.open(archive, "w:gz") as tar:
        tar.add(DIST / "Budgetier", arcname="Budgetier")
    return report(archive)


def main() -> int:
    if sys.platform == "darwin":
        return build_mac()
    if sys.platform == "linux":
        return build_linux()
    pyinstaller("Budgetier.spec", "app")
    pyinstaller("Uninstall.spec", "uninstall", BUILD / "uninstaller")

    app = DIST / "Budgetier"
    payload = BUILD / "payload.zip"
    with zipfile.ZipFile(payload, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(p for p in app.rglob("*") if p.is_file()):
            archive.write(path, path.relative_to(app))
        archive.write(BUILD / "uninstaller" / "uninstall.exe", "uninstall.exe")

    pyinstaller("Setup.spec", "setup")
    return report(DIST / "Budgetier-Windows.exe")


if __name__ == "__main__":
    sys.exit(main())
