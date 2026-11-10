# Build portable Probe

Build on the target operating system: Windows produces Windows executables and
Linux produces Linux executables. Cross-compiling a Windows EXE from Linux is not
supported by this build. Use Python 3.10+ including Tkinter and install dev tools:

```sh
python -m venv .venv
```

Activate the environment and run from the repository root:

```sh
python -m pip install -e ".[dev]"
python scripts/build.py
```

The single command uses [packaging/Probe.spec](../packaging/Probe.spec), runs the
frozen I/O self-test and writes a versioned ZIP and SHA-256 file in `dist`:

```text
Probe-1.7.1-windows-x86_64.zip
Probe-1.7.1-windows-x86_64.zip.sha256
```

Linux uses `linux` in the filename. Folder mode is the default for fast startup
and straightforward redistribution. It includes `_internal`, documentation,
examples and third-party notices/source. The executable does not request UAC at
startup. Windows bundles the offline USBPcap prerequisite for opt-in HID use.

## Verify the actual archive

```sh
python packaging/verify_bundle.py dist/Probe-*.zip
```

On headless Linux use `xvfb-run -a` before Python. Verification extracts into a new
folder, checks required inputs and launches the frozen self-test and GUI smoke
test with source paths removed. It does not install USBPcap or capture real HID.
A successful source run is not a substitute for testing the frozen package.

## Single-file option

```sh
python scripts/build.py --onefile
```

This produces a separate `-onefile.zip`. PyInstaller extracts its runtime on every
launch, so startup is slower and temporary disk space is needed. Settings still
live outside the executable. Test it independently; official releases use folder
mode unless explicitly stated.

## Spec-only build and resources

```sh
python -m PyInstaller --noconfirm --clean packaging/Probe.spec
```

This makes the raw runtime folder, not the complete redistributable archive. Use
`scripts/build.py` to add documentation, source/license notices, offline drivers
and checksums. Do not ship an incomplete raw folder instead.

The spec includes fonts/artwork and explicitly required standard-library modules
for portable user plugins. It excludes large unrelated libraries. Frozen resources
are found through `probe.resources.resource_root`; local writable data is separate.
The Windows build validates the bundled USBPcap installer's fixed SHA-256.

## Python distributions and compatibility

```sh
python -m build
```

This writes a source distribution and wheel. Both include packaged assets and
optional offline driver resources. Install the wheel in a clean environment outside
the repository, then run `python -m probe --self-test`. Tk must come from the Python
installation/system; wheels do not bundle Tcl/Tk like a portable executable does.
No automated PyPI publishing is configured.

For Linux, build on the oldest distribution/glibc version you intend to support;
newer glibc builds may not run on older hosts. CI uses Ubuntu 22.04 for that reason.
Build separately for other architectures. Current official artifacts are x86_64;
manual ARM builds need target-machine verification. See [releasing](releasing.md).
