#!/bin/sh
set -eu
cd "$(dirname "$0")" || exit 1
. ./linux_python.sh
if [ ! -x .venv/bin/python ]; then
    choose_python
    "$PROBE_PYTHON" -m venv .venv || {
        echo "Could not create .venv. Install python3-venv for the selected interpreter." >&2
        exit 1
    }
fi
if ! .venv/bin/python -c 'import tkinter; tkinter.Tcl()' 2>/dev/null; then
    echo "The existing .venv has no working Tkinter. Recreate it with PROBE_PYTHON pointing to Python with Tkinter." >&2
    exit 1
fi
if ! .venv/bin/python - 2>/dev/null <<'PY'
from importlib.metadata import version
from pathlib import Path
for line in Path("requirements.txt").read_text().splitlines():
    if line.strip() and not line.startswith("#"):
        name, expected = line.strip().split("==")
        assert version(name) == expected
import serial, serial.tools.list_ports, pyte, wcwidth
assert hasattr(serial, "serial_for_url"), "Install pyserial, not the unrelated serial package"
PY
then
    .venv/bin/python -m pip install -r requirements.txt
fi
exec .venv/bin/python run_probe.py "$@"
