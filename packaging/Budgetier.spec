# Build with: .venv\Scripts\pyinstaller packaging\Budgetier.spec --noconfirm
from PyInstaller.utils.hooks import collect_all

datas, binaries, hiddenimports = [("../budgetier/dashboard.html", "budgetier"), ("../VERSION", ".")], [], []
for package in ("webview", "clr_loader", "pythonnet", "pdfplumber"):
    d, b, h = collect_all(package)
    datas += d
    binaries += b
    hiddenimports += h

analysis = Analysis(["../run_app.py"], pathex=[".."], datas=datas, binaries=binaries,
                    hiddenimports=hiddenimports, excludes=["tkinter", "unittest", "pytest"])
pyz = PYZ(analysis.pure)
exe = EXE(pyz, analysis.scripts, [], exclude_binaries=True, name="Budgetier", console=False,
          icon="Budgetier.ico")
COLLECT(exe, analysis.binaries, analysis.datas, name="Budgetier")
