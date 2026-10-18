# Probe 1.1.1 Windows validation

## Native Windows gate

The `Windows tests and portable builds` workflow on the `windows` branch uses
Windows Server 2022 x64 and CPython 3.12, with pinned pySerial 3.5, pyte 0.8.2,
wcwidth 0.2.13 and PyInstaller 6.22.3. Exact runner/tool versions and test results:

https://github.com/mohsensafaei/Probe_Communication_Console/actions/workflows/windows.yml

The gate runs the Windows batch source/build launchers, backend tests and native
Tk GUI tests. It builds folder and single-executable ZIPs, extracts each under a
temporary path containing spaces outside the repository, and runs frozen I/O and
GUI diagnostics. JSON reports must confirm the current version and success.
Folder bundles are checked for a PE executable, Tcl/Tk DLLs, `_tkinter.pyd`, fonts,
licenses and sample models/sequences. Both ZIPs exclude `probe-data`. Artifacts
upload only after verification. A committed workflow alone is not a passing run;
consult its run conclusion and individual executed steps.

GUI checks cover all eight transport panels, visible Test lab, Appearance removal,
sequence editing/import/export/run, model building and the COM pair's advertised
application endpoint. POSIX-only PTY/permission checks skip explicitly on Windows.
Physical hardware tests are opt-in.

## Local cross-platform checks

On the Linux development host, 64 backend tests passed (71 total,
6 attached-device tests and one unprivileged-permission check skipped). COM-pair tests use actual pySerial `socket://`
endpoints: all 256 byte values, duplex proxying, both injection sides, exact
captures, ordered stateful replies, reset, endpoint ownership and disconnect
cleanup. These verify the shared serial path, not a Windows kernel COM driver.

All 16 local GUI tests passed with an isolated X display and temporary preferences. The COM
configuration test presents the Windows panel and exchanges real serial socket
bytes. Native CI provides the evidence for Windows UI and executable packaging.

Sequence-specific checks cover default RX and optional TX selection, subset
order, unchanged destination, exact binary bytes, shared 100 ms timing on the
wire, Run/Save/table consistency, independent composer timing, preserved mixed
imported delays and reply checks, legacy defaults, editor validation/cancel,
continuous Stop and editing locks. Minimum layouts were visually checked at
980×680 (sequence page), 800×500 (capture picker), 700×480 (simple editor) and
760×560 (advanced editor), including visible action buttons and status. This is
Linux Tk evidence; the Windows workflow must pass separately for native builds.

## Physical USB and COM-pair drivers

This environment has no Windows USB host or installed Windows COM-pair driver.
Earlier Samsung CDC ACM / AT direct, proxy, capture, bridge, GUI and recorded
emulation tests passed on Linux; they are not Windows hardware results.

The six opt-in `tests/test_serial_hardware.py` checks now support Windows.
Set `PROBE_TEST_SERIAL_PORT=COM3`, `PROBE_TEST_APP_PORT=COM20`,
`PROBE_TEST_PEER_PORT=COM21`, and `PROBE_TEST_GUI=1` after attaching an AT-capable
USB device and installing the COM20/COM21 pair. Direct/bridge/GUI direct and
recorded TCP emulation also work without the pair; COM proxy checks require it.
Only read-only `AT` attention commands are sent. Captures/settings are temporary.
USB HID, MTP and arbitrary bulk interfaces are outside this serial backend.

A COM pair is a driver prerequisite. Probe opens one end and the other application
opens its partner. Drivers are not installed automatically. Physical RTS/CTS,
vendor protocols, hard real-time timing and a real RFC2217 server still require
device-specific validation.

## Windows timing correction

The first native run reproduced a real timing defect: CPython 3.12's coarse
Windows monotonic clock let short asyncio sleeps finish before their requested
5–10 ms delays. The sequence now measures durations with `perf_counter` and uses
bounded worker sleeps on coarse clocks, preserving minimum delays without blocking
the event loop. Cancellation leaves at most a 50 ms sleep to finish. Reply timeouts
and delayed simulated responses share this timer. Tests use the performance clock
for duration measurements and verify minimum waits, early-reply interruption and
cancelling a one-hour delay. OS scheduling may still make a delay longer.

Python documents the clock-resolution behavior in its
[event loop reference](https://docs.python.org/3.12/library/asyncio-eventloop.html#asyncio.loop.call_later).
