# Probe 1.0.0 Linux validation

Validated on 2026-10-15: Debian 13 x86_64, glibc 2.41, CPython 3.12.13,
Tcl/Tk 9.0.3, pySerial 3.5, pyte 0.8.2, wcwidth 0.2.13 and PyInstaller 6.22.3.

## Source checks

```sh
./start_linux.sh --self-test
.venv/bin/python -m unittest discover -s tests -v
xvfb-run -a .venv/bin/python -m unittest discover -s tests -p ui_smoke.py -v
```

**36 transport/codec/terminal/capture tests and 7 GUI tests passed.** The tests
use actual loopback TCP/UDP, pySerial loopback and Linux PTYs. They cover binary
duplex traffic, proxy injection and half-close, multiple clients, captures,
checksums/framing, ANSI rendering, import/replay, serial permission errors,
unplug cleanup and GUI serial reconnect. GUI tests use isolated preferences.

The default system Python here lacks Tkinter and pySerial. The Linux launcher
successfully selected the installed Python 3.12 with Tkinter, created `.venv`,
installed the pinned requirements and passed the full runtime self-test.

## Frozen bundle checks

```sh
./build_linux.sh
xvfb-run -a ./dist/Probe/Probe --smoke-test
./dist/Probe/Probe --version
```

The builder executes the frozen program's `--self-test` from a temporary working
directory outside the source tree. It exercises serial loopback, direct PTY,
PTY serial proxy, Serial-to-TCP, TCP client/server/proxy, UDP, JSONL capture and
ANSI terminal support. The frozen GUI smoke check opens all seven mode panels.

An initial native build reproduced missing `libtcl9.0.so` / `libtcl9tk9.0.so`.
The spec now includes the shared libraries from standalone Python installations;
the rebuilt executable passes both the runtime and GUI checks. ZIP contents are
checked for the executable, launcher, native Tcl/Tk libraries and pySerial
license. Local `probe-data` preferences are excluded.

## Physical-device limit

No USB UART/CDC device was attached during validation. The available
`/dev/ttyS0`–`/dev/ttyS3` entries reported `n/a`, are owned by `root:dialout`, and
opening them as `mrrobot` reproduced `EACCES`. This user's current session is not
in `dialout`; adding that membership requires the user's sudo password and a
desktop logout/login. Probe now displays the owning group and the corrective
command instead of an unexplained transport failure. It no longer automatically
selects `n/a` devices.

PTY tests verify Linux byte transport, not physical wiring, hardware flow control,
USB driver behavior, vendor-specific modem lines or an actual RFC2217 server.
Windows support and older Linux distributions were not validated for this release.
