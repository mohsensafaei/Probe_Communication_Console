"""Build on the target OS. Default onedir starts faster and avoids temp extraction."""
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import zipfile
from importlib.metadata import distribution

root=Path(__file__).resolve().parent
parser=argparse.ArgumentParser()
parser.add_argument("--onefile",action="store_true",help="Single executable; slower startup due to extraction")
args=parser.parse_args()
# Refuse to package a Python installation without its GUI bindings.
import tkinter
tkinter.Tcl()
cmd=[sys.executable,"-m","PyInstaller","--noconfirm","--clean",str(root/"Probe.spec")]
if args.onefile:cmd.extend(["--distpath",str(root/"dist"/"onefile-bin")])
env=dict(os.environ,PROBE_BUNDLE_MODE="onefile" if args.onefile else "folder")
subprocess.run(cmd,cwd=root,env=env,check=True)
platform=("windows-x64" if sys.maxsize>2**32 else "windows-x86") if os.name=="nt" else "linux-"+os.uname().machine
if args.onefile:
    executable=root/"dist"/"onefile-bin"/("Probe.exe" if os.name=="nt" else "Probe")
    folder=root/"dist"/("Probe-"+platform)
    folder.mkdir(exist_ok=True);shutil.copy2(executable,folder/executable.name)
else:folder=root/"dist"/"Probe"
executable=folder/("Probe.exe" if os.name=="nt" else "Probe")
with tempfile.TemporaryDirectory(prefix="probe-bundle-check-") as check_dir:
    subprocess.run([str(executable),"--self-test"],cwd=check_dir,check=True,timeout=60)
for name in ("README.md","FEATURE_MATRIX.md","VALIDATION.md","CHANGELOG.md","LICENSE","THIRD_PARTY_NOTICES.md"):
    shutil.copy2(root/name,folder/name)
shutil.copytree(root/"examples", folder/"examples", dirs_exist_ok=True,
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
(folder/"probe-data").mkdir(exist_ok=True)
licenses=folder/"licenses";licenses.mkdir(exist_ok=True)
shutil.copy2(root/"licenses"/"pyserial-LICENSE.txt",licenses/"pyserial-LICENSE.txt")
for path in (root/"assets"/"fonts").glob("*-OFL.txt"):
    shutil.copy2(path,licenses/path.name)
for package in ("pyserial","pyte","wcwidth"):
    dist=distribution(package)
    for item in dist.files or []:
        if "LICENSE" in item.name.upper() or "COPYING" in item.name.upper():
            path=dist.locate_file(item)
            if path.is_file():shutil.copy2(path,licenses/(package+"-"+item.name))
# Include the small terminal libraries' source for replacement/rebuilding.
import pyte,wcwidth
thirdparty=folder/"third-party-source";thirdparty.mkdir(exist_ok=True)
for module in (pyte,wcwidth):
    shutil.copytree(Path(module.__file__).parent,thirdparty/module.__name__,dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns("__pycache__","*.pyc"))
if os.name!="nt":
    launcher=folder/"start-probe.sh"
    launcher.write_text('#!/bin/sh\ncd "$(dirname "$0")" || exit 1\nexec ./Probe "$@"\n')
    launcher.chmod(0o755)
output=root/"dist"/("Probe-"+platform+("-onefile" if args.onefile else "")+".zip")
with zipfile.ZipFile(output,"w",zipfile.ZIP_DEFLATED,compresslevel=9) as archive:
    for path in sorted(folder.rglob("*")):
        if path.is_file() and "probe-data" not in path.relative_to(folder).parts:
            archive.write(path,Path(folder.name)/path.relative_to(folder))
print(f"Portable archive: {output}")
