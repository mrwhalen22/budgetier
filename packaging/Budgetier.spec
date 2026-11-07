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

analysis = Analysis(["../run_app.py"], pathex=[".."], datas=datas, binaries=binaries,
                    hiddenimports=hiddenimports, excludes=["tkinter", "unittest", "pytest"])
if sys.platform == "linux":
    # Qt's browser links to Qt Quick, so PyInstaller adds every QML plugin Qt has, which the
    # window never loads. Translations are left out too, except the browser's English text.
    def needed(entry) -> bool:
        path = "/" + entry[0].replace("\\", "/")
        if "/Qt/qml/" in path:
            return False
        return "/Qt/translations/" not in path or path.endswith("/qtwebengine_locales/en-US.pak")

    analysis.datas = [entry for entry in analysis.datas if needed(entry)]
    analysis.binaries = [entry for entry in analysis.binaries if needed(entry)]
pyz = PYZ(analysis.pure)
exe = EXE(pyz, analysis.scripts, [], exclude_binaries=True, name="Budgetier", console=False,
          icon="Budgetier.ico")
collected = COLLECT(exe, analysis.binaries, analysis.datas, name="Budgetier")
if sys.platform == "darwin":
    version = (Path(SPECPATH).parent / "VERSION").read_text(encoding="utf-8-sig").strip()
    BUNDLE(collected, name="Budgetier.app", icon="Budgetier.ico",
           bundle_identifier="com.github.mrwhalen22.budgetier", version=version,
           info_plist={"NSHighResolutionCapable": True})
