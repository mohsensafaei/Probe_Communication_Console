# Repeatable benchmarks

Install the project with `python -m pip install -e ".[dev]"` and run from the
repository root. Results are local observations and are intentionally not tracked.

| Command | Measures |
| --- | --- |
| `python benchmarks/core_benchmark.py` | Byte formatting, framing, comparison and trace scans |
| `python benchmarks/plugin_benchmark.py` | Worker throughput/latency and bounded analysis behavior |
| `python benchmarks/transport_benchmark.py --output transport-benchmark.json` | Byte-exact TCP receive/proxy/sequence tests with and without recording |
| `python benchmarks/display_benchmark.py` | Native Tk traffic display and bounded retention |
| `python benchmarks/multi_probe_benchmark.py` | Simultaneous acquisition and hidden-workspace rendering cost |

GUI benchmarks require a desktop or `xvfb-run -a` on Linux. Backend checks compare
complete streams/captures, not receive-call counts. Transport timing collects host
send/receive observations; multiple frames in a read share an observation time.
It does not measure physical packet spacing or electrical UART timings.

The transport harness includes 16 MiB receive, 100,000 short frames, bidirectional
proxy echo, 1 ms sequence requests, and contention with a Python thread/process.
Absolute deadlines avoid accumulated relative-wait drift, but do not make the
host OS real-time. Record mean/P99/max error and missed slots on the lab machine.

At 115200 baud 8N1, ten bits are needed per byte: at most 11,520 bytes/s per
direction before protocol/USB/driver overhead. A software loopback or PTY does not
enforce this limit. See [testing](../docs/testing.md) for physical-device opt-ins.
