# Probe for Linux 1.2.2

TCP, UDP and USB/serial communications console with an ANSI terminal, binary
inspector, capture/replay, serial proxy and Serial-to-TCP bridge.

```sh
./source/start_linux.sh
```

The launcher selects an installed Python 3.10+ with Tkinter, creates a local
virtual environment and installs the pinned runtime dependencies on first use.
Internet access is needed for that initial install. On Debian/Ubuntu, install
`python3-tk` and `python3-venv` if needed. Set `PROBE_PYTHON=/path/to/python`
to choose an interpreter explicitly.

For a hardware-free serial check, select **USB / Serial**, enter `loop://`,
and connect. To test the runtime from a terminal:

```sh
./source/start_linux.sh --self-test
```

For USB hardware, enter `/dev/ttyUSB0`, `/dev/ttyACM0` or the stable path under
`/dev/serial/by-id/`, with the device's baud and line settings. The listed
`/dev/ttyS*` entries may be unused motherboard UARTs, not USB adapters.

If opening a port reports **Permission denied**, inspect its owning group with
`ls -l /dev/ttyUSB0`. On Debian/Ubuntu the usual fix is:

```sh
sudo usermod -aG dialout "$USER"
```

Log out of the desktop session and back in before restarting Probe. Group
changes do not affect already running desktop applications. Probe reports the
actual owning group in its permission error. See the
[pySerial permission documentation](https://pyserial.readthedocs.io/en/latest/appendix.html#permission-denied-errors).

Build a native portable Linux bundle (Python is included):

```sh
./source/build_linux.sh
```

Extract `source/dist/Probe-linux-<architecture>.zip` and run `./start-probe.sh`.
The build runs real serial loopback, Linux PTY, TCP, UDP, terminal and capture
checks against the frozen executable before packaging it. Build on the oldest
Linux distribution you intend to support.

Only Linux source, assets, runtime/build scripts, documentation and regression
tests are tracked on this branch. Local settings, environments, build output,
portable binaries and Windows launchers are excluded.

See [the full guide](source/README.md) and [validation results](source/VALIDATION.md).

Opt-in tests for an attached AT-capable USB serial device (including supported
phone CDC ACM interfaces) are available under `source/tests/test_serial_hardware.py`.
From `source`, select the device explicitly:

```sh
PROBE_TEST_SERIAL_PORT=/dev/ttyACM0 PROBE_TEST_GUI=1 xvfb-run -a \
  .venv/bin/python -m unittest discover -s tests -p test_serial_hardware.py -v
```

They check direct serial, PTY proxy, injection, byte-exact captures, Serial-to-TCP
and the actual GUI using only the read-only `AT` attention command. Normal test
runs skip these tests. USB serial proxying does not intercept a phone's separate
MTP file-transfer interface.

## Hardware test lab

Open **Test lab** at the bottom of the control panel.

* **Device simulator:** record TX/RX with the real device using Record, then load
  that JSONL/CSV capture (or use retained traffic history). Choose one peer and
  expose the model as a TCP socket or a Linux virtual serial PTY. Connect the
  other application to the displayed endpoint. The original hardware is not
  opened. Exact requests produce their recorded replies and timing. Save a model
  to reuse it later; rules and reply bytes can also be edited manually.
* **Test sequences:** add a composer payload or create steps in Text/Hex/Escaped/
  Decimal/Hercules format. Set a separate delay after each step in milliseconds,
  per-step repeats, optional expected reply bytes and a timeout. Choose a finite
  cycle count or 0 to run until stopped. Reorder, duplicate, import and export
  complete sequences. Connect a transport in the main window before running.

The simulator preserves conversation order by default, including different replies
for repeated identical requests. Match requests mode supports independent rules
in any order and rejects ambiguous rules. Unknown request bytes are ignored and
reported. Leading RX chatter is excluded when building from a capture; dynamic
transaction IDs, cryptographic handshakes and device-specific state need explicit
models. Timings are best effort on the host OS, not hard real-time.

Try `source/examples/device-model.json` with `source/examples/test-sequence.json`
using two Probe instances: one simulates a TCP device, the other runs the sequence
as a TCP Client. These are synthetic PING/BUY examples; replace their payloads with
the actual protocol bytes for your own hardware.

## Updated workbench

All shared features through Windows commit `660536e` are available on Linux:
reply-gated sequences, RX/TX capture selection, dynamic variables and routing,
Protocol Inspector, Capture Diff, and the simplified Traffic / Live plot / Terminal workspace.
Single-click selects a transaction; double-click opens Analyze with Decoded text,
Hex + ASCII and Every byte. Export offers Hex and Decoded text checkboxes.
Capture Diff compares Reference (A) with Message (B) automatically and shows
hex and decoded text for the selected difference.

Live plot accepts numeric RX lines ending in LF (for example `1,2,3\n`).
Terminal displays RX immediately; enable **Send keyboard** to transmit keys.
Linux automatic PTY support and the native portable build scripts are retained.

## Probe visual identity

The interface uses an original hardware test-probe emblem, satin-edged blue
instrument panels and mint readouts. Geometric Michroma headings, Rajdhani
controls and Share Tech Mono data fonts are bundled with OFL notices.
The light palette preserves the same controls and message workflows.
No vendor logo or proprietary skin is used.
