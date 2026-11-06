# Built by packaging/build_installer.py, which makes the payload first.
analysis = Analysis(["setup_main.py"],
                    datas=[("../build/payload.zip", "."), ("Budgetier.ico", "."), ("../VERSION", ".")],
                    excludes=["unittest", "pydoc", "pytest"])
pyz = PYZ(analysis.pure)
EXE(pyz, analysis.scripts, analysis.binaries, analysis.datas, name="BudgetierSetup",
    console=False, icon="Budgetier.ico", uac_admin=True)
