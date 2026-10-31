"""Create isolated Windows environments for source launch and native builds."""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
BUILDER = "pyinstaller==6.22.3"


def requirements(build: bool) -> list[str]:
    entries = [line.split(";",1)[0].strip() for line in (ROOT / "requirements.txt").read_text().splitlines()
               if line.strip() and not line.lstrip().startswith("#")]
    return entries + ([BUILDER] if build else [])


def main() -> int:
    if os.name != "nt":
        raise RuntimeError("Use start_linux.sh / build_linux.sh on Linux.")
    if sys.version_info < (3, 10):
        raise RuntimeError("Python 3.10+ with Tkinter is required. Install Python from python.org.")
    import tkinter
    tkinter.Tcl()
    arguments = sys.argv[1:]
    build = bool(arguments and arguments[0] == "--build")
    if build:
        arguments.pop(0)
    environment = ROOT / (".windows-build-venv" if build else ".windows-venv")
    python = environment / "Scripts" / "python.exe"
    if not python.is_file():
        subprocess.run([sys.executable, "-m", "venv", str(environment)], check=True)
    subprocess.run([str(python), "-c", "import sys, tkinter; assert sys.version_info >= (3,10); tkinter.Tcl()"], check=True)
    expected = requirements(build)
    check = (
        "from importlib.metadata import version; import sys; "
        "assert all(version(n)==v for n,v in (s.split('==') for s in sys.argv[1:])); "
        "import serial, serial.tools.list_ports, pyte, wcwidth, hid; assert hasattr(serial,'serial_for_url')"
    )
    result = subprocess.run([str(python), "-c", check, *expected], capture_output=True)
    if result.returncode:
        subprocess.run([str(python), "-m", "pip", "install", "-r", str(ROOT / "requirements.txt"),
                        *([BUILDER] if build else [])], check=True)
        subprocess.run([str(python), "-c", check, *expected], check=True)
    script = ROOT / ("build_portable.py" if build else "run_probe.py")
    return subprocess.run([str(python), str(script), *arguments], cwd=ROOT).returncode


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, ImportError, subprocess.CalledProcessError) as error:
        print(f"Probe: {error}", file=sys.stderr)
        raise SystemExit(1)
