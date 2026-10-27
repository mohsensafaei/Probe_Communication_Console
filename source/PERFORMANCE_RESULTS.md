# Probe 1.2.1 baseline transport benchmark — 2026-10-27

**Measured outcome: byte integrity passed in these TCP tests; exact 1 ms periodic timing did not. No nanosecond timing guarantee is supported.**

Runs used unmodified Probe transport/Sequence code with Python 3.12 on hosted Windows Server 2022 and Ubuntu 24.04 x86-64 runners. Real TCP sockets were connected over localhost. No Tk window was instantiated; these are engine/capture tests, not a GUI responsiveness test, physical LAN measurement or UART test. A single run per case is evidence for that run, not a hardware-independent bound.

## TCP byte integrity

On both systems all of the following matched the expected complete byte stream; recorded data was independently re-read from disk and checked using SHA-256. Receive-call boundaries were not treated as message boundaries.

* Receive 16 MiB without recording.
* Receive 16 MiB with JSONL recording.
* Receive 100,000 individually sent, indexed 32-byte frames (3,200,000 bytes), with recording.
* Proxy echo of 8 MiB in each direction, with TX and RX captures checked.
* Sequence delivery of 1,000 repeated 32-byte messages per idle case, plus 500 under deliberate Python CPU contention.

No missing, added or reordered bytes were detected in these streams. This does not prove loss-free operation under every load. Serial driver overruns, physical links, UDP loss and UI queue drops are not covered.

## Sequence requesting 1 ms

Timestamps here are application observations after `writer.write`; receiver timestamps mark availability of a full 32-byte frame. These are **not electrical/wire timestamps**. Intervals include the current relative-wait sequence behavior and application overhead. P99 is the observed 99th-percentile interval, not a guarantee.

| OS | JSONL record | Extra CPU thread | Sends | Mean interval (ms) | P99 interval (ms) | Max interval (ms) | Cumulative drift (ms) |
|---|---|---|---:|---:|---:|---:|---:|
| windows | False | False | 1000 | 1.440 | 1.867 | 11.528 | 439.704 |
| windows | True | False | 1000 | 1.507 | 1.957 | 10.427 | 506.137 |
| windows | True | True | 500 | 125.665 | 236.937 | 273.500 | 62207.930 |
| linux | False | False | 1000 | 1.110 | 1.173 | 1.243 | 109.934 |
| linux | True | False | 1000 | 1.132 | 1.176 | 1.257 | 132.336 |
| linux | True | True | 500 | 25.566 | 57.096 | 67.236 | 12258.394 |

The contending thread deliberately runs a tight Python calculation loop **inside the same process**. It is a stress case, not a prediction for every busy PC. No messages were lost in that case, but periodicity deteriorated severely. The interval error is interval minus 1 ms. Cumulative drift compares the first-to-last TX span with `(count - 1) * 1 ms`.

## Serial: 115200 baud, assumed 8N1

No physical serial device was available. These are wire-capacity calculations, not measured UART results. PTY and `loop://` do not enforce physical baud rate. With 1 start + 8 data + 1 stop bit, the theoretical full-duplex limit is 11,520 bytes/s **per direction** before protocol gaps or flow control.

| Total message bytes | Minimum serialization time (ms) | Theoretical max messages/s |
|---:|---:|---:|
| 1 | 0.087 | 11520.00 |
| 8 | 0.694 | 1440.00 |
| 11 | 0.955 | 1047.27 |
| 12 | 1.042 | 960.00 |
| 32 | 2.778 | 360.00 |
| 64 | 5.556 | 180.00 |
| 128 | 11.111 | 90.00 |
| 256 | 22.222 | 45.00 |

At 1,000 messages/s there is room for at most 11 total bytes/message in this ideal 8N1 capacity calculation; headers, checksums and line endings count. A 32-byte message every 1 ms cannot be sustained at 115200 baud regardless of programming language. This capacity condition is not a timing guarantee.

## Baseline 1.2.1 implementation findings

* Sequence waits after sends/processing rather than following fixed absolute deadlines, allowing accumulated drift.
* Capture writes and flushes happen on the transport path and add overhead.
* The main composer Repeat control currently enforces a minimum 50 ms interval. The 1 ms tests above use Sequence.
* UI events can be dropped under overload independently of transport capture. This benchmark does not certify the GUI display as lossless.

Improvement candidates: absolute-deadline scheduling with explicit lateness reporting; separating disk I/O and CPU-heavy work from the transport/scheduler; then repeating the benchmark on the target Windows/Linux PC with the actual LAN and UART adapter. These changes would need validation and would not by themselves establish a nanosecond wire-launch guarantee.

## Reproduce and inspect

These historical results used the source commits recorded in each raw JSON. For the updated scheduler and current reproduction instructions, see [1.2.2 validation](PERFORMANCE_1_2_2.md).

* [Benchmark implementation](benchmarks/transport_benchmark.py)
* [Raw Windows results](performance-results/transport-windows-2026-10-27.json)
* [Raw Linux results](performance-results/transport-linux-2026-10-27.json)
* [Windows run](https://github.com/mohsensafaei/Probe_Communication_Console/actions/runs/40495066190)
* [Linux run](https://github.com/mohsensafaei/Probe_Communication_Console/actions/runs/40495032077)
