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

## Attached USB hardware verification

A Samsung Android phone (USB VID:PID `04e8:6860`) was subsequently attached.
Its CDC ACM communication/data interfaces bind to Linux `cdc_acm` and expose
`/dev/ttyACM0`. Read/write access for the current user was confirmed, including
the effective device ACL. No phone serial number or personal data is recorded
in these tests or this report.

**All 5 opt-in hardware tests passed** using the real phone:

* Direct USB serial: `AT\r` transmitted and `AT\r\r\nOK\r\n` received;
  JSONL capture preserved the exact transmitted/received bytes.
* USB serial proxy: a separate pySerial application opened Probe's generated
  PTY, sent `AT\r` through the physical USB port, and received the phone's `OK`.
  Device-side injection also reached the phone; app-side injection reached only
  the application. JSONL and raw RX captures matched the delivered bytes.
* Serial-to-TCP: a real loopback TCP client received the physical phone's AT
  response through the bridge with matching transport capture bytes.
* GUI direct serial: the composer sent the command and the traffic table and
  ANSI terminal displayed the physical phone's response.
* GUI serial proxy: the application opened the PTY advertised by the UI,
  exchanged AT/OK with the phone, and disconnected cleanly.

Reproduce from the `source` directory with an explicitly selected AT-capable
device (only the read-only AT attention command is sent to the phone):

```sh
PROBE_TEST_SERIAL_PORT=/dev/ttyACM0 PROBE_TEST_GUI=1 xvfb-run -a \
  .venv/bin/python -m unittest discover -s tests -p test_serial_hardware.py -v
```

Hardware tests are skipped by default. They use temporary captures and isolated
GUI preferences. The normal 36 backend and 7 GUI tests remain the hardware-free
regression gate. The initial setup reproduced permission errors on unused
`/dev/ttyS*` ports; those entries must not be confused with the phone's ACM port.

These results validate the phone's USB **serial** interface. Its separate MTP
file-transfer interface is not proxied by Probe. Physical RTS/CTS wiring,
vendor-specific modem commands and an actual RFC2217 server remain outside
these checks. Windows and older Linux distributions were not validated.
