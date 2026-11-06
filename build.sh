#!/bin/sh
# Builds the macOS disk image in dist. Needs Python 3.12.
cd "$(dirname "$0")" || exit 1
[ -x .venv/bin/python ] || python3 -m venv .venv || exit 1
.venv/bin/python -m pip install -q -r requirements-dev.txt || exit 1
.venv/bin/python packaging/build_installer.py
