# Optional transport benchmark

Run from `source`: `python benchmarks/transport_benchmark.py --output transport-benchmark.json`.
Install `requirements.txt` first. This runs the unmodified Probe Engine and Sequence
runner through real TCP loopback sockets, without Tk. It creates temporary captures
and checks complete byte streams and capture contents with SHA-256, not receive-call
or packet counts. No physical serial port is opened. CI runs natively on the branch's
OS; hosted-runner results are observations, not limits for a user's machine.

Tests: 16 MiB receive with/without recording; 100,000 individually sent 32-byte
frames with recording; 8 MiB proxy echo in each direction with recording; 1,000
32-byte Sequence sends requesting 1 ms delays with/without recording; and 500 sends
with recording plus a deliberately contending Python CPU thread, and 500 with
the CPU workload moved to a separate process. Both TX application
observations and receiver full-frame observations are collected. Multiple frames
in a single read share an RX observation timestamp. The benchmark does not measure
wire launch times, actual packet spacing, GUI rendering or UI drop counters.

Timing percentiles describe this run only. The runner uses absolute send deadlines from 1.2.2; missed slots are reported and
messages are preserved. Prior baseline results used relative waits after sends. Mean interval, P99,
maximum error and cumulative drift must not be confused with a real-time guarantee.
An early peer close must not cancel the last send before its final completion event.

Serial capacity assumes 115200 baud, 8 data bits, no parity, 1 stop bit: ten bits
per byte, at most 11,520 bytes/s **per direction** in full duplex. Frame transmission
time is `bytes * 10 / 115200` seconds. Protocol overhead, inter-frame gaps, USB/driver
latency and flow control reduce usable throughput. A software `loop://` or PTY does
not enforce a physical 115200-baud line and is not accepted as hardware evidence.
