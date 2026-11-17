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

## Packet capture binding comparison

Use an isolated Python environment and install `libpcap==1.11.0b29` from PyPI.
From `source`, run the offline checks and timing without capture privileges:

```sh
python -m pip install libpcap==1.11.0b29
python benchmarks/pcap_binding_benchmark.py --output pcap-binding-benchmark.json
```

Both bindings use the same native library. Use `--library /absolute/path/to/libpcap.so`
to test a specific Linux build. Add `--live lo` on Linux when your environment
permits capture on loopback. Windows additionally requires Npcap; pass the
loopback device name (as reported by the Probe interface list) instead of `lo`.
The live trial opens only local sockets and sends a known synthetic TCP payload
and an unrelated UDP datagram. The Linux transport benchmark workflow also runs
this comparison and saves the JSON report.

| Check | What the result tells you |
| --- | --- |
| Offline correctness | Matching bytes, timestamps, link types, snap lengths, and original lengths; rejection of other TCP ports and UDP; useful errors on invalid filters and missing files. |
| Offline timing | Wall time, thread CPU time, and matching packets per second. Python copies and constructs the same `Packet` in both cases. Orders alternate between repeats. |
| Live correctness | Both bindings enumerate the selected loopback, apply the TCP filter, and reconstruct exact request and reply bytes using Probe's stream code. In the paced case (8 KiB with a 3 ms pause between writes), gaps, skipped packets and filter leaks fail the check. |
| Burst pressure | The same TCP workload without pacing. Compare reconstructed bytes, gaps and driver drops, even when a socket transfer succeeds but the capture is incomplete. Burst loss is reported, not used as a CI gate. |
| Live responsiveness | Nonblocking idle read, idle CPU, stop/join with and without recent traffic, plus the delay from socket round trip to complete capture. Loopback round trip is a workload observation, not a binding speed guarantee. |
| Development and packaging | Extra APIs already exposed by the wrapper, installed package size excluding dependencies, and dependency list. A prototype calls the nanosecond PCAP API and checks the exact timestamp integer when available. It does not establish live hardware timestamp accuracy. |

The harness reuses Probe's ctypes signatures and native loader. It keeps the
read loop, filter, payload copy, and stream logic equal; it does not benchmark
the GUI, disk recording, or maximum physical-network capture capacity. A zero
drop count does not establish that a real network was captured completely.
The wrapper saves C signatures and structure definitions, but a switch still
needs a frozen-package check on both platforms with and without the native
driver available.

To compare both bindings at identical buffer sizes and polling intervals, run:

```sh
python benchmarks/pcap_binding_benchmark.py --live lo --tune-live --packets 4000 --output pcap-tuning-benchmark.json
```

The sweep repeats the unpaced 1 MiB-per-direction loopback test with the
current `pcap_open_live` path (10 ms wait) and with `pcap_create` plus every
combination of driver-default, 4 MiB and 8 MiB buffer requests and waits of
10, 1 and 0.25 ms. The capture timeout stays at 25 ms. Case order rotates
between rounds, and the two bindings alternate which runs first for each case.
The output file keeps raw trials and summaries for each binding: recovered bytes,
exact runs, driver drops, idle CPU and stop latency. Buffer sizes and waits
are requested settings; they are not measured allocations or wakeup periods.
Incomplete burst capture is an observation rather than a test failure.
