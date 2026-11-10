# Install and update

## Portable application

Download the Windows x64 or Linux x64 ZIP from
[Releases](https://github.com/mohsensafaei/Probe_Communication_Console/releases/latest).
Extract the entire folder. Run `Probe.exe` on Windows, or `./start-probe.sh` on Linux.
Do not move the executable away from its `_internal` directory. No Python install
is needed. For Linux archives extracted by tools that discard executable permissions,
run `chmod +x Probe start-probe.sh`.

Official Linux builds use Ubuntu 22.04 runners. Other distributions must provide
compatible glibc and desktop libraries; test on your target system or build there.
Windows builds target current x64 Windows desktop systems. Builds are unsigned;
organization policies may require administrator approval to run them. Normal TCP,
serial and simulator use does not request elevation.

Check the downloaded checksum before running a new archive:

```sh
sha256sum -c Probe-<version>-linux-x86_64.zip.sha256
```

On Windows, compare `Get-FileHash .\Probe-<version>-windows-x86_64.zip -Algorithm SHA256`
in PowerShell with the adjacent `.sha256` file. Checksums detect changed downloads;
they are not code-signing certificates.

## Source installation

Install Python 3.10+ including Tkinter. On Debian/Ubuntu:

```sh
sudo apt-get install python3-tk python3-venv
```

Clone `main` or extract a release source archive, then create a virtual environment:

```sh
python -m venv .venv
```

Activate `.venv\Scripts\activate` on Windows Command Prompt or
`source .venv/bin/activate` on Linux. Run:

```sh
python -m pip install -e .
python -m probe
```

Use `python -m tkinter` to verify Tk independently. `probe` is the command-line
entry point; `probe-gui` avoids a console window on Windows. Dependencies are
pinned in [pyproject.toml](../pyproject.toml). Probe is not yet published to PyPI.
For contributor tools install `python -m pip install -e ".[dev]"` instead.

## Offline use

Portable applications run offline. The Windows USBPcap installer and matching source
are included for optional HID setup; no runtime download is performed. Linux uses
its kernel's usbmon module and an installed `pkexec` or `sudo` helper.

For an offline source install, prepare wheels on a connected machine with the same
OS, architecture and Python version:

```sh
python -m pip download -d wheelhouse .
```

Copy `wheelhouse` to the target and run:

```sh
python -m pip install --no-index --find-links wheelhouse probe-communication-console
```

This installs a local wheel, not a PyPI package. Native build dependencies must
also be available if your download step produces source distributions.

## Settings and updates

Portable builds store settings, commands and plugins in `probe-data` next to the
executable when writable. Source/pip installations use `%LOCALAPPDATA%\Probe` on
Windows and `$XDG_DATA_HOME/Probe` or `~/.local/share/Probe` on Linux. Set
`PROBE_DATA_DIR` to override this directory. An unwritable portable folder falls
back to the per-user directory.

To update a portable build, extract the new version into a new folder and copy your
`probe-data` folder while Probe is closed. Keep the old version until the new one
has been checked with your hardware. For source installs, pull `main` and rerun
`python -m pip install -e .`. Read the [changelog](../CHANGELOG.md) first. When moving from the historical
`linux`/`windows` layout, copy your old `source/probe-data` contents into the new
data directory before starting, or point `PROBE_DATA_DIR` at that existing folder.
