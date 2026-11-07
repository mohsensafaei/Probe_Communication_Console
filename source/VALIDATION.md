# Linux synchronization validation

## Plugin API 1 validation (1.7.0)

Local CPython 3.12.14 / Linux checks cover plugin metadata without execution,
per-flow/session state, relative helper imports, RX/TX permissions, ordered and
framed transforms, timeout/import/close failures, analysis priority, binary/JSON
examples, real TCP proxy transformations, blocked sends and original RX recording.
Native Tk checks cover installation, live fields, editing/rebuild/action previews,
manual-analysis plot isolation, named plot sources and missing-plugin recovery.
The shared implementation passes 183 backend checks (8 environment-dependent skips)
and 67 GUI checks. Both branch source trees were exercised on Linux; native Windows
execution remains a separate CI gate after publication.

The Linux PyInstaller folder build executes a newly written external Python plugin
with bundled hashlib/hmac/struct, transforms serial loopback data, checks preserved
original bytes and runs the existing transport/HID-helper diagnostics. The extracted
bundle verifier additionally checks the guide/examples and GUI without PYTHONPATH.

`benchmarks/plugin_benchmark.py` measures warm 1 KiB RPC overhead and worker throughput.
One local run measured 0.071 ms median / 0.451 ms p99 for a trivial transform and
13,359 analyses/second; this excludes startup and is not a real-time guarantee.
A before/after disabled-plugin GUI comparison retained zero background table
insertions and roughly 34.6 MiB of Python allocations with four probes. Synthetic
batch times varied by approximately 3–7%; measure on the laboratory host.

Shared application code and regression tests synchronized from Windows commit
`660536e`. Linux launchers, portable builder and automatic PTY support retained.
Windows-specific validation below records upstream evidence; it is not a Linux
build claim. The Linux CI workflow runs source diagnostics, backend tests, native
Tk GUI tests under Xvfb, and a frozen portable build. Physical hardware tests are
opt-in.

# Probe 1.2.1 Windows validation

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

On the Linux development host, 88 backend tests passed (95 total,
6 attached-device tests and one unprivileged-permission check skipped). COM-pair tests use actual pySerial `socket://`
endpoints: all 256 byte values, duplex proxying, both injection sides, exact
captures, ordered stateful replies, reset, endpoint ownership and disconnect
cleanup. These verify the shared serial path, not a Windows kernel COM driver.

All 28 local GUI tests passed with an isolated X display and temporary preferences. The COM
configuration test presents the Windows panel and exchanges real serial socket
bytes. Native CI provides the evidence for Windows UI and executable packaging.

Sequence-specific checks cover default RX and optional TX selection, subset
order, unchanged destination, exact binary bytes, shared 100 ms timing on the
wire, Run/Save/table consistency, independent composer timing, preserved mixed
imported delays and reply checks, legacy defaults, editor validation/cancel,
continuous Stop and editing locks. Minimum layouts were visually checked at
980×680 (sequence page), 800×500 (capture picker), 700×480 (simple editor) and
700×620 (advanced editor), including visible action buttons and status. This is
Linux Tk evidence; the Windows workflow must pass separately for native builds.

Reply-mode regressions cover withheld replies blocking the following send,
selected-peer isolation, ignored startup/outgoing/empty data, immediate and split
matching replies, physical-serial and downstream bridge replies, repeat/cycle
counts, timeout halting the run and cancellation of a one-hour reply wait.
GUI checks verify on-wire gating, waiting status, Stop, disabled timing controls,
mode switching without baking reply flags into messages, JSON round trips and
button text contrast of at least 4.5:1, including disabled hover states. Buttons
retain keyboard focus with a solid border and no dotted label overlay.

Version 1.2 checks also cover exact JSON byte spans with nested UTF-8/escapes,
length mismatch/partial data, TLV/BER nesting and bounds, custom integer/length/
checksum fields, additions/removals and ignored JSON values of different lengths.
Reports are verified to preserve both original byte streams. Sequence checks
exercise actual TCP fragmented replies, extraction/conditional goto, dynamic
JSON escaping, rebuilt lengths/checksums, binary variables, timeout routing,
stale-value clearing, missing variables stopping before send and Stop during a
structured reply wait. GUI tests include the captured-field picker, Save/Cancel,
stable target IDs after reordering, v3 export/import with initial variables,
offline analysis not starting a transport and actual templated TCP sending.

Minimum new layouts were inspected at 920×680 (analysis), 820×680 (both response
rule tabs), 720×540 (variables) and 620×410 (frame options). The advanced message
editor reserves Save/Cancel before other content and enforces a taller minimum.
Frozen self-test exercises protocol/comparison and a dynamic TCP conversation;
frozen GUI diagnostics instantiate both analysis tabs and response/variable
dialogs so missing lazily imported modules cannot pass the portable gate.

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

## Workspace consolidation (1.2.1)

Main pages are Traffic, Live plot and Terminal. GUI regressions use native Tk
mouse press/release events on tab labels and traffic cells, not just programmatic
selection. They verify all message views in one reused Analyze window, source
snapshot preservation, every-byte pagination, explicit composer loading, and no
popups from programmatic selection/filtering. The 1060×700 main window and
920×700 Analyze window were visually inspected.

Real serial loopback tests assert plotted CSV curves, live terminal RX, keyboard
focus and key transmission. A Serial-to-TCP test selects a concrete TCP client
and verifies physical serial replies still reach Terminal. A TCP server test
types before the first RX and preserves the screen after its client disconnects.
Numeric model tests cover split lines, peer isolation, invalid/binary/non-finite
inputs, oversized-line recovery and bounded peers/samples. Terminal actions use
two rows so history, Paste, Reset and Pop out remain visible on narrow windows.
Frozen GUI diagnostics select all three workspace pages and verify plot curves,
terminal text and the consolidated Analyze views.


## HID Monitor 1.3.0 — 2026-10-31

Native Windows and Linux backend/GUI checks passed. The Windows folder and
single-file EXE packages, and the Linux extracted portable package, passed frozen
self-tests and GUI smoke tests. The self-test launches the actual capture helper
without elevation in diagnostic-only mode; it does not install a driver or start
USB capture. The Windows bundle verifier checks the included offline USBPcap
installer hash, corresponding source archive and licenses.

- Windows runtime: `90f1ba304b8c3e492c9d4be908b73d82b35a33d4`.
  https://github.com/mohsensafaei/Probe_Communication_Console/actions/runs/41181862133
- Linux runtime: `170f845b8221dd256b77f26030c507614d417e40`.
  https://github.com/mohsensafaei/Probe_Communication_Console/actions/runs/41181881085

Tests cover capture format fixtures, signed bit fields, report IDs, keyboard
arrays, Input/Output/Feature reconstruction, composite endpoints, metadata import, nested-field recording memory budgets,
unelevated helper IPC, source validation, read-only UI controls and permission
cancellation followed by normal serial use. Synthetic HID previews are generated
by `tests/hid_visual_preview.py`, with no device access or authentication prompt.

**Physical HID capture, actual UAC/Polkit dialogs and driver installation were not
exercised on connected lab hardware.** They require target-system validation;
passing these automated tests is not a hardware capture or throughput guarantee.
See HID_MONITOR.md for setup and limitations.


## 1.4 simulator rules and recovery coverage

The platform gates exercise complete-message request matching with fragmented and
coalesced JSON, length prefixes, TLV/BER-TLV, text and byte ranges; missing fields,
malformed lengths/checksums and ambiguous rules. Fault checks cover all response
transformations, independent per-client Nth-match triggers, TCP reconnection and
Reset/Stop cancellation. POSIX additionally exercises semantic matching and
faults through a real PTY at 115200 baud configuration. This is a virtual byte
stream test, not a physical UART timing measurement.

Native Tk checks create/save/reopen field rules and fault settings, configure
binary framing, retain original capture chunk delays and keep Save visible on
every fault type. Simulator previews are uploaded by the native workflows.
Frozen self-tests perform a semantic JSON request and duplicated reply over real
localhost TCP; frozen GUI smoke opens both the rule and framing editors. See the
corresponding workflow conclusion for actual executed-platform results.


## 1.4.1 structural and processing regression coverage

Core checks additionally cover fresh-interpreter headless imports, all byte values
and multiple display encodings, arbitrary framing boundaries, comparison offset
partitions and all export choices with retained metadata. Native GUI and frozen
checks exercise the extracted presentation package. Core microbenchmarks run in
both platform workflows as informational measurements, without flaky timing gates.


## 1.5 concurrent probe coverage

Native GUI tests additionally exercise independent settings/history/terminal
models, three simultaneous TCP/TCP/serial-loopback endpoints, recording while
hidden, active shortcut routing, isolated connection/timer shutdown, reopening
slot preferences, owned popup destruction and garbage collection after repeated
open/close. The frozen smoke test opens two independent serial loopbacks and
checks that closing one leaves the other connected. No physical serial/HID
hardware timing claim is made. The informational 1/2/4-probe benchmark checks
hidden table insertion counts and separates Python allocation instrumentation
from elapsed-time measurements.

## 1.6 trace and explicit search coverage

Headless tests cover binary split/coalesced spans, peer/direction/client isolation,
bounded duplicate occurrences, strict scalar JSON IDs and manual byte preservation.
Native GUI checks cover changed-ID comparison, correct A/B probe pickers, ambiguous
matches, snapshot refresh/disposal, empty histories and draft/invalid search input.
The core benchmark includes 2000 rows / about 8 MiB of retained stream data. Frozen
smoke tests open Trace and compare payloads using the packaged modules.
