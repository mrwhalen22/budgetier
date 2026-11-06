# Built by packaging/build_installer.py and packed inside the installer.
analysis = Analysis(["uninstall_main.py"], pathex=["."], datas=[("../VERSION", ".")],
                    excludes=["tkinter", "unittest", "pydoc", "pytest"])
pyz = PYZ(analysis.pure)
EXE(pyz, analysis.scripts, analysis.binaries, analysis.datas, name="uninstall",
    console=False, icon="Budgetier.ico", uac_admin=True)
