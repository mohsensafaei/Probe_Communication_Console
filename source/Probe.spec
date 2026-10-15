# -*- mode: python ; coding: utf-8 -*-
"""Portable Probe build. Run on Windows to produce dist/Probe.exe.

python -m PyInstaller --clean --noconfirm Probe.spec

Default: one executable. Set PROBE_BUNDLE_MODE=folder for the faster-starting
folder bundle at dist/Probe/Probe.exe (or dist/Probe/Probe on Linux).
Paths resolve from this spec, not from a particular machine or cwd.
"""
import os
import sys
from pathlib import Path
from importlib.metadata import distribution

root = Path(SPECPATH).resolve()
mode = os.environ.get("PROBE_BUNDLE_MODE", "onefile")
if mode not in ("onefile", "folder"):
    raise ValueError("PROBE_BUNDLE_MODE must be onefile or folder")
windows = os.name == "nt"
license_data = []
# Standalone Python distributions (including uv) keep Tcl/Tk beside libpython,
# outside ldconfig's search path. Include these native libraries explicitly.
tk_binaries = []
if not windows:
    libdir = Path(sys.base_prefix) / "lib"
    for pattern in ("libtcl*.so*", "libtk*.so*"):
        tk_binaries.extend((str(path), ".") for path in sorted(libdir.glob(pattern)) if path.is_file())
for package in ("pyserial", "pyte", "wcwidth"):
    dist = distribution(package)
    for item in dist.files or []:
        if "LICENSE" in item.name.upper() or "COPYING" in item.name.upper():
            path = dist.locate_file(item)
            if path.is_file():license_data.append((str(path), "licenses/" + package))

a = Analysis(
    [str(root / "run_probe.py")],
    pathex=[str(root)],
    binaries=tk_binaries,
    datas=[(str(root / "assets" / "probe.png"), "assets"),
           (str(root / "assets" / "fonts"), "assets/fonts"),
           (str(root / "LICENSE"), "licenses"),
           (str(root / "THIRD_PARTY_NOTICES.md"), "licenses"),
           (str(root / "licenses" / "pyserial-LICENSE.txt"), "licenses/pyserial")] + license_data,
    hiddenimports=["serial.tools.list_ports", "serial.urlhandler.protocol_loop",
                   "serial.urlhandler.protocol_rfc2217", "serial.urlhandler.protocol_socket"],
    hookspath=[], hooksconfig={}, runtime_hooks=[],
    excludes=["numpy", "matplotlib", "PIL", "pytest", "IPython"],
    noarchive=False, optimize=0,
)
pyz = PYZ(a.pure)
options = dict(name="Probe", debug=False, bootloader_ignore_signals=False,
               strip=not windows, upx=False, console=False,
               disable_windowed_traceback=False,
               icon=str(root / "assets" / "probe.ico") if windows else None)
if mode == "onefile":
    exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], **options)
else:
    exe = EXE(pyz, a.scripts, [], exclude_binaries=True, **options)
    coll = COLLECT(exe, a.binaries, a.datas,
                   strip=not windows, upx=False, name="Probe")
