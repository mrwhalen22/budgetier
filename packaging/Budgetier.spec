# Built by packaging/build_installer.py. Makes dist/Budgetier on Windows and Linux, and
# dist/Budgetier.app as well on macOS. The window is Qt Widgets, the same on every system.
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all

# What PyInstaller can't find by following imports: data files, and the secure storage
# each system's keyring loads by name.
packages = ["pdfplumber", "keyring", "certifi"]
packages += {"win32": ["win32ctypes"], "linux": ["secretstorage", "jeepney"]}.get(sys.platform, [])
datas, binaries, hiddenimports = [("../VERSION", ".")], [], []
for package in packages:
    d, b, h = collect_all(package)
    datas += d
    binaries += b
    hiddenimports += h

analysis = Analysis(["../run_app.py"], pathex=[".."], datas=datas, binaries=binaries,
                    hiddenimports=hiddenimports, excludes=["tkinter", "unittest", "pytest"])

# Left out: Qt's translations, since the window is in English, and on Linux Qt's GTK theme
# with the copy of GTK it pulls in, which could clash with the desktop's own.
GTK = ("libqgtk3.so", "libgtk-3.so", "libgdk-3.so")


def needed(entry) -> bool:
    path = "/" + entry[0].replace("\\", "/")
    return "/Qt/translations/" not in path and not path.rsplit("/", 1)[-1].startswith(GTK)


analysis.datas = [entry for entry in analysis.datas if needed(entry)]
analysis.binaries = [entry for entry in analysis.binaries if needed(entry)]
# Linux libraries can carry debug symbols the app never uses. Stripping a Mac app would
# break its signature, and Windows has nothing to strip.
strip = sys.platform == "linux"
pyz = PYZ(analysis.pure)
exe = EXE(pyz, analysis.scripts, [], exclude_binaries=True, name="Budgetier", console=False,
          icon="Budgetier.ico", strip=strip)
collected = COLLECT(exe, analysis.binaries, analysis.datas, name="Budgetier", strip=strip)
if sys.platform == "darwin":
    version = (Path(SPECPATH).parent / "VERSION").read_text(encoding="utf-8-sig").strip()
    BUNDLE(collected, name="Budgetier.app", icon="Budgetier.ico",
           bundle_identifier="com.github.mrwhalen22.budgetier", version=version,
           info_plist={"NSHighResolutionCapable": True})
