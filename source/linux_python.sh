#!/bin/sh
# Sourced by the Linux launch/build scripts after changing to this directory.
choose_python() {
    if [ -n "${PROBE_PYTHON:-}" ]; then
        if "$PROBE_PYTHON" -c 'import sys, tkinter; assert sys.version_info >= (3, 10); tkinter.Tcl()' 2>/dev/null; then
            return
        fi
        echo "PROBE_PYTHON must point to Python 3.10+ with working Tkinter." >&2
        exit 1
    fi
    for candidate in python3 python3.13 python3.12 python3.11 python3.10; do
        if command -v "$candidate" >/dev/null 2>&1 &&
           "$candidate" -c 'import sys, tkinter; assert sys.version_info >= (3, 10); tkinter.Tcl()' 2>/dev/null; then
            PROBE_PYTHON=$candidate
            return
        fi
    done
    echo "Python 3.10+ with Tkinter is required. On Debian/Ubuntu: sudo apt install python3-tk python3-venv" >&2
    echo "Or set PROBE_PYTHON to an installed Python that includes Tkinter." >&2
    exit 1
}
