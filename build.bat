@echo off
rem Builds dist\BudgetierSetup.exe, the single-file installer.
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe python -m venv .venv
.venv\Scripts\python -m pip install -q -r requirements-dev.txt || exit /b 1
.venv\Scripts\python packaging\build_installer.py || exit /b 1
