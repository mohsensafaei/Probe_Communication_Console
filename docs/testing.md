# Tests and measurements

Install with `python -m pip install -e ".[dev]"`. Run from the repository root:

```sh
python -m ruff check src tests scripts packaging
python scripts/check_docs.py
python -m unittest discover -s tests -v
python -m probe --self-test
python -m unittest discover -s tests -p "ui_*.py" -v
python -m probe --smoke-test
```

The `test_*.py` suite covers codecs, capture validation, real loopback networking,
software serial/PTYs, recording workers, sequences, simulator rules, plugins, HID
binary fixtures and package boundaries. `ui_*.py` covers actual Tk workflows,
multiple simultaneous probes, Analyze/Diff, plugins, search, traces, terminal,
plots and simulator editors. Hardware tests skip unless explicitly configured.

On headless Debian/Ubuntu install `xvfb` and `xauth`, then use:

```sh
xvfb-run -a python -m unittest discover -s tests -p "ui_*.py" -v
xvfb-run -a python -m probe --smoke-test
```

CI runs Linux and Windows with Python 3.10 and 3.12. The native portable builds are
also extracted into a temporary directory and exercised without the checkout on
`PYTHONPATH`. A green software test does not prove physical UART/HID behavior or
hard real-time performance. Tests using fake Windows serial endpoints validate
routing/contracts, not a driver or physical COM pair.

## Optional physical serial test

Use an explicitly selected AT-capable serial device only. These tests transmit
read-only `AT` attention commands; this is not appropriate for every device protocol.
Read [the test](../tests/test_serial_hardware.py) first. On Linux:

```sh
PROBE_TEST_SERIAL_PORT=/dev/ttyACM0 PROBE_TEST_GUI=1 xvfb-run -a \
  python -m unittest discover -s tests -p test_serial_hardware.py -v
```

Tests exercise direct serial, PTY proxy, injection, capture, Serial ↔ TCP and GUI
paths where available. Live HID capture requires a suitable device, host driver
and permissions; see [HID monitor](hid.md). Normal tests never install a driver or
request elevation.

## Benchmarks

Keep benchmark code, not machine-specific result dumps, in version control.
See [the benchmark guide](../benchmarks/README.md). Examples:

```sh
python benchmarks/core_benchmark.py
python benchmarks/plugin_benchmark.py
python benchmarks/transport_benchmark.py --output transport-benchmark.json
xvfb-run -a python benchmarks/display_benchmark.py
xvfb-run -a python benchmarks/multi_probe_benchmark.py
```

Measure on the actual lab computer and transport. Compare complete byte streams
with hashes, not packet/read-call counts. Record offered rate, frame size, queue
loss, recording/plugin state, CPU load and timing percentiles. Loopback TCP does
not measure physical network launch times. PTYs and `loop://` do not enforce UART
baud limits. At 115200 8N1, the theoretical maximum is 11,520 bytes/s per direction.

Sequence timing uses absolute deadlines and reports missed slots. A deadline is an
application scheduling target, not proof that the last UART bit or Ethernet packet
left at that instant. Do not infer nanosecond accuracy from timestamp resolution.
