import argparse
import hashlib
from importlib.metadata import distribution
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/"src"))
from probe import __version__


def build(onefile=False):
    output = ROOT/"dist"
    binaries = output/"onefile-bin" if onefile else output
    environment = dict(os.environ, PROBE_BUNDLE_MODE="onefile" if onefile else "folder")
    subprocess.run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
                    "--distpath", str(binaries), "--workpath", str(ROOT/"build"),
                    str(ROOT/"packaging/Probe.spec")], cwd=ROOT, env=environment, check=True)
    system = "windows" if os.name == "nt" else "linux"
    machine = platform.machine().lower()
    architecture = "x86_64" if machine in ("amd64", "x86_64") else machine
    name = f"Probe-{__version__}-{system}-{architecture}" + ("-onefile" if onefile else "")
    with tempfile.TemporaryDirectory(prefix="probe-package-") as temporary:
        folder = Path(temporary)/name
        if onefile:
            folder.mkdir()
            shutil.copy2(binaries/("Probe.exe" if os.name == "nt" else "Probe"), folder)
        else:
            shutil.copytree(output/"Probe", folder, ignore=shutil.ignore_patterns("probe-data", "__pycache__", "*.pyc"))
        executable = folder/("Probe.exe" if os.name == "nt" else "Probe")
        subprocess.run([str(executable), "--self-test"], cwd=temporary, check=True, timeout=90)
        for filename in ("README.md", "LICENSE", "THIRD_PARTY_NOTICES.md", "CHANGELOG.md"):
            shutil.copy2(ROOT/filename, folder)
        for directory in ("docs", "examples", "licenses"):
            shutil.copytree(ROOT/directory, folder/directory,
                            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        for path in (ROOT/"src/probe/assets/fonts").glob("*-OFL.txt"):
            shutil.copy2(path, folder/"licenses"/path.name)
        for name_ in ("pyserial", "pyte", "wcwidth") + (("hidapi",) if os.name == "nt" else ()):
            dependency = distribution(name_)
            for item in dependency.files or ():
                if "LICENSE" in item.name.upper() or "COPYING" in item.name.upper():
                    path = dependency.locate_file(item)
                    if path.is_file():shutil.copy2(path, folder/"licenses"/(name_+"-"+item.name))
        import pyte
        import wcwidth
        for module in (pyte, wcwidth):
            shutil.copytree(Path(module.__file__).parent, folder/"third-party-source"/module.__name__,
                            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        if os.name == "nt":
            shutil.copytree(ROOT/"src/probe/drivers", folder/"drivers")
        else:
            launcher = folder/"start-probe.sh"
            launcher.write_text('#!/bin/sh\ncd "$(dirname "$0")" || exit 1\nexec ./Probe "$@"\n')
            launcher.chmod(0o755)
        archive = output/(name+".zip")
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zipped:
            for path in sorted(folder.rglob("*")):
                if path.is_file():zipped.write(path, path.relative_to(folder.parent))
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    archive.with_suffix(".zip.sha256").write_text(f"{digest}  {archive.name}\n")
    return archive


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build and self-test a native portable Probe archive.")
    parser.add_argument("--onefile", action="store_true")
    print(build(parser.parse_args().onefile))
