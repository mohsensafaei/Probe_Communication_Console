# Probe for Linux 1.0.0

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
