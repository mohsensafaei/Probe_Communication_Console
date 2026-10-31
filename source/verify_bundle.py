"""Extract and exercise the actual portable ZIP outside the source tree."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import tempfile
import zipfile

from probe import __version__


def verify(archive: Path) -> None:
    with tempfile.TemporaryDirectory(prefix="Probe extracted bundle ") as directory:
        temporary = Path(directory)
        with zipfile.ZipFile(archive) as bundle:
            names = bundle.namelist()
            if any("probe-data" in Path(name).parts for name in names):
                raise RuntimeError("Bundle contains local application data")
            bundle.extractall(temporary)
        roots = list(temporary.iterdir())
        if len(roots) != 1 or not roots[0].is_dir():
            raise RuntimeError("Bundle must contain exactly one portable folder")
        root = roots[0]
        executable = root / ("Probe.exe" if os.name == "nt" else "Probe")
        for required in (executable, root/"README.md", root/"LICENSE", root/"licenses"/"pyserial-LICENSE.txt",
                         root/"examples"/"device-model.json", root/"examples"/"test-sequence.json",
                         root/"examples"/"lab-protocol.json", root/"examples"/"variable-sequence.json",
                         root/"examples"/"variable-device.json"):
            if not required.is_file():
                raise RuntimeError(f"Missing bundle input: {required.name}")
        if os.name == "nt":
            from probe.hid_capture import INSTALLER,INSTALLER_SHA256
            import hashlib
            installer=root/"drivers"/"windows"/INSTALLER
            if not installer.is_file() or hashlib.sha256(installer.read_bytes()).hexdigest()!=INSTALLER_SHA256:
                raise RuntimeError("Missing or corrupt offline USBPcap installer")
            for name in ("USBPcap-1.5.4.0-source.zip","GPL-2.0.txt","BSD-2-Clause.txt","README.md"):
                if not (installer.parent/name).is_file():raise RuntimeError("Missing USBPcap redistribution input: "+name)
            with executable.open("rb") as stream:
                if stream.read(2) != b"MZ":
                    raise RuntimeError("Windows bundle does not contain a PE executable")
            if "onefile" not in archive.stem:
                for pattern in ("**/_tkinter.pyd", "**/tcl*.dll", "**/tk*.dll", "**/*.ttf"):
                    if not list(root.glob(pattern)):
                        raise RuntimeError(f"Missing GUI runtime: {pattern}")
        else:
            executable.chmod(0o755)
        environment = dict(os.environ, PYTHONNOUSERSITE="1")
        environment.pop("PYTHONPATH", None)
        environment.pop("PYTHONHOME", None)
        for check in ("self-test", "smoke-test"):
            report = temporary/(check+".json")
            subprocess.run([str(executable), "--"+check, "--diagnostic-report", str(report)],
                           cwd=temporary, env=environment, check=True, timeout=90)
            result = json.loads(report.read_text(encoding="utf-8"))
            if result.get("success") is not True or result.get("version") != __version__ or result.get("check") != check:
                raise RuntimeError(f"Frozen diagnostic failed: {result}")
        print(f"Verified extracted {archive.name}: version {__version__}, real I/O self-test and GUI/Test lab")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archives", type=Path, nargs="+")
    for archive in parser.parse_args().archives:
        verify(archive.resolve())
