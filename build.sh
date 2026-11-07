#!/bin/sh
# Builds the macOS disk image or the Linux archive in dist. Needs Python 3.12. On Linux,
# run packaging/linux_deps.sh first, or install the same things for your system.
cd "$(dirname "$0")" || exit 1
[ -x .venv/bin/python ] || python3 -m venv .venv || exit 1
.venv/bin/python -m pip install -q -r requirements-dev.txt || exit 1
if [ "$(uname)" = Linux ]; then .venv/bin/python -m pip install -q -r requirements-linux.txt || exit 1; fi
.venv/bin/python packaging/build_installer.py
