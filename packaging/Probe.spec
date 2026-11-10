import os
import sys
from importlib.metadata import distribution
from pathlib import Path

root = Path(SPECPATH).resolve().parent
package = root / "src" / "probe"
sys.path.insert(0, str(root / "src"))
windows = os.name == "nt"
mode = os.environ.get("PROBE_BUNDLE_MODE", "folder")
if mode not in ("folder", "onefile"):
    raise ValueError("PROBE_BUNDLE_MODE must be folder or onefile")

licenses = []
for name in ("pyserial", "pyte", "wcwidth") + (("hidapi",) if windows else ()):
    dependency = distribution(name)
    for item in dependency.files or ():
        if "LICENSE" in item.name.upper() or "COPYING" in item.name.upper():
            path = dependency.locate_file(item)
            if path.is_file():licenses.append((str(path), "licenses/" + name))

binaries = []
if not windows:
    for pattern in ("libtcl*.so*", "libtk*.so*"):
        binaries.extend((str(path), ".") for path in (Path(sys.base_prefix)/"lib").glob(pattern) if path.is_file())
drivers = []
if windows:
    from probe.hid.capture import bundled_installer
    bundled_installer()
    drivers = [(str(package/"drivers/windows"), "drivers/windows")]

analysis = Analysis(
    [str(root/"packaging/entrypoint.py")], pathex=[str(root/"src")], binaries=binaries,
    datas=[(str(package/"assets"), "assets"), (str(root/"LICENSE"), "licenses"),
           (str(root/"THIRD_PARTY_NOTICES.md"), "licenses"),
           (str(root/"licenses/pyserial-LICENSE.txt"), "licenses/pyserial")] + licenses + drivers,
    hiddenimports=["serial.tools.list_ports", "serial.urlhandler.protocol_loop",
                   "serial.urlhandler.protocol_rfc2217", "serial.urlhandler.protocol_socket",
                   "json", "struct", "hashlib", "hmac", "base64", "binascii", "re", "math",
                   "statistics", "decimal", "datetime", "collections", "itertools", "functools",
                   "zlib", "csv", "string"] + (["hid"] if windows else []),
    excludes=["numpy", "matplotlib", "PIL", "pytest", "IPython"],
)
archive = PYZ(analysis.pure)
options = dict(name="Probe", console=False, strip=not windows, upx=False,
               uac_admin=False, uac_uiaccess=False,
               icon=str(package/"assets/probe.ico") if windows else None)
if mode == "onefile":
    executable = EXE(archive, analysis.scripts, analysis.binaries, analysis.datas, [], **options)
else:
    executable = EXE(archive, analysis.scripts, [], exclude_binaries=True, **options)
    bundle = COLLECT(executable, analysis.binaries, analysis.datas, strip=not windows, upx=False, name="Probe")
