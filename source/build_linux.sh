#!/bin/sh
set -eu
cd "$(dirname "$0")"
. ./linux_python.sh
choose_python
"$PROBE_PYTHON" -m venv .build-venv
.build-venv/bin/python -m pip install -r requirements.txt pyinstaller==6.22.3
.build-venv/bin/python build_portable.py "$@"
