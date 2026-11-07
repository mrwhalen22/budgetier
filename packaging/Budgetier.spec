# Built by packaging/build_installer.py. Makes dist/Budgetier on Windows, and
# dist/Budgetier.app as well on macOS.
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all

packages = ["webview", "pdfplumber", "keyring", "certifi"]
packages += ["clr_loader", "pythonnet", "win32ctypes"] if sys.platform == "win32" else []
datas, binaries, hiddenimports = [("../budgetier/dashboard", "budgetier/dashboard"), ("../VERSION", ".")], [], []
for package in packages:
    d, b, h = collect_all(package)
    datas += d
    binaries += b
    hiddenimports += h

analysis = Analysis(["../run_app.py"], pathex=[".."], datas=datas, binaries=binaries,
                    hiddenimports=hiddenimports, excludes=["tkinter", "unittest", "pytest"])
pyz = PYZ(analysis.pure)
exe = EXE(pyz, analysis.scripts, [], exclude_binaries=True, name="Budgetier", console=False,
          icon="Budgetier.ico")
collected = COLLECT(exe, analysis.binaries, analysis.datas, name="Budgetier")
if sys.platform == "darwin":
    version = (Path(SPECPATH).parent / "VERSION").read_text(encoding="utf-8-sig").strip()
    BUNDLE(collected, name="Budgetier.app", icon="Budgetier.ico",
           bundle_identifier="com.github.mrwhalen22.budgetier", version=version,
           info_plist={"NSHighResolutionCapable": True})
