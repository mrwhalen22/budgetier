# Built by packaging/build_installer.py. Makes dist/Budgetier on Windows and Linux, and
# dist/Budgetier.app as well on macOS.
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all

packages = ["webview", "pdfplumber", "keyring", "certifi"]
packages += ["clr_loader", "pythonnet", "win32ctypes"] if sys.platform == "win32" else []
packages += ["secretstorage", "jeepney"] if sys.platform == "linux" else []
datas, binaries, hiddenimports = [("../budgetier/dashboard", "budgetier/dashboard"), ("../VERSION", ".")], [], []
for package in packages:
    d, b, h = collect_all(package)
    datas += d
    binaries += b
    hiddenimports += h
if sys.platform == "linux":
    # Only the Qt parts the window uses, found through qtpy. Collecting all of qtpy would
    # bring in every Qt module it wraps, 3D and multimedia included, and triple the download.
    QT = ("QtCore", "QtGui", "QtWidgets", "QtNetwork", "QtWebChannel", "QtWebEngineCore", "QtWebEngineWidgets",
          "QtPrintSupport")
    hiddenimports += ["qtpy", *(f"qtpy.{name}" for name in QT), *(f"PySide6.{name}" for name in QT)]
    # Qt's browser links to Qt Quick, so PyInstaller would add Quick's Python modules too, and
    # their hooks bring every QML plugin Qt has, with the libraries those need: 3D, charts and
    # more. The window never loads QML. Quick's own library still comes, as the browser needs it.
    excludes = ["PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtQuickWidgets", "PySide6.QtDataVisualization"]
else:
    excludes = []

analysis = Analysis(["../run_app.py"], pathex=[".."], datas=datas, binaries=binaries,
                    hiddenimports=hiddenimports, excludes=["tkinter", "unittest", "pytest", *excludes])
if sys.platform == "linux":
    # Left out: anything QML that still arrives, every translation but the browser's English
    # text, the browser's developer tools, and Qt's GTK theme with the copy of GTK it pulls in,
    # which could clash with the desktop's own. Qt draws its own file dialog without it.
    GTK = ("libqgtk3.so", "libgtk-3.so", "libgdk-3.so")

    def needed(entry) -> bool:
        path = "/" + entry[0].replace("\\", "/")
        if "/Qt/qml/" in path or path.endswith("/qtwebengine_devtools_resources.pak"):
            return False
        if path.rsplit("/", 1)[-1].startswith(GTK):
            return False
        return "/Qt/translations/" not in path or path.endswith("/qtwebengine_locales/en-US.pak")

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
