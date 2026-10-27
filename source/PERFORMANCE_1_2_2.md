# Probe 1.2.2 timing validation — 2026-10-27

**Absolute deadlines greatly reduced idle cumulative drift in these runs. This is not hard real-time scheduling, and not every latency metric improved. All tested TCP streams and queued captures matched.**

## What changed

Sequence intervals follow fixed `perf_counter_ns` deadlines across repeats and cycles, rather than adding processing time to a relative sleep after every send. If preparation has already missed a deadline, the payload moves to the next future slot; the payload is preserved and missed slots are counted. A late OS wakeup can still dispatch late. There is no final trailing interval. Reply gates retain the requested post-reply delay and re-anchor the following schedule.

Capture hex/JSON serialization and file writes now run in a dedicated spawned process. The transport enqueues without waiting for disk; a bounded 4096-event / 64 MiB estimated-byte budget prevents unlimited backlog. Normal stop drains and closes the capture. Disk/worker/queue failures explicitly disarm recording and report an incomplete capture. Dynamic template rendering and reply extraction run in a separate process pool. Routine interval-mode progress reports are throttled to reduce UI event traffic.

## Recorded idle Sequence: before and after

1,000 messages of 32 bytes, requested interval 1 ms, JSONL recording enabled. Intervals are application TX observations after `writer.write`, not wire-launch measurements. Drift compares the first-to-last span with 999 ms. P99 is an observed percentile, not a bound.

| OS | Version | Mean interval (ms) | P99 (ms) | Maximum (ms) | Drift (ms) |
|---|---|---:|---:|---:|---:|
| windows | 1.2.1 | 1.506643 | 1.957100 | 10.426900 | 506.136600 |
| windows | 1.2.2 | 1.001384 | 1.439700 | 1.547000 | 1.382300 |
| linux | 1.2.1 | 1.132468 | 1.176404 | 1.257405 | 132.335599 |
| linux | 1.2.2 | 1.001064 | 1.123024 | 2.489423 | 1.062867 |

The Linux recorded maximum interval increased despite improved mean/drift/P99. The Windows recorded case happened to perform better than its unrecorded case; this is normal host-scheduling variability, not evidence that recording improves timing. Each case is one run on hosted Windows Server 2022 or Ubuntu 24.04 x86-64, Python 3.12. Hosted hardware/load can differ between runs. This is not a controlled same-machine A/B study. No Tk GUI was instantiated in the benchmark.

## 1.2.2 load and scheduler diagnostics

Every row below used recording. Idle cases used 1,000 messages; stress cases used 500. “Same-process Python thread” deliberately competes for the GIL. “Separate process” runs a busy calculation worker with a readiness barrier; it demonstrates isolation from that GIL contention but does not simulate every real protocol workload.

| OS | CPU load | Mean interval (ms) | P99 (ms) | Maximum (ms) | Drift (ms) | Missed slots | Max dispatch lateness (ms) |
|---|---|---:|---:|---:|---:|---:|---:|
| windows | none | 1.001384 | 1.439700 | 1.547000 | 1.382300 | 1 | 1.121600 |
| windows | same-process Python thread | 100.707401 | 173.236300 | 190.034800 | 49753.992900 | 49691 | 146.899500 |
| windows | separate process | 1.021260 | 1.603400 | 1.680200 | 10.608800 | 10 | 1.170700 |
| linux | none | 1.001064 | 1.123024 | 2.489423 | 1.062867 | 1 | 1.713816 |
| linux | same-process Python thread | 33.949982 | 82.208743 | 108.319568 | 16442.040817 | 16412 | 76.900640 |
| linux | separate process | 1.000330 | 1.131499 | 1.316467 | 0.164825 | 0 | 0.419891 |

Same-process Python CPU contention remains severe. Its Linux mean/max were worse than the baseline stress run; there is no across-the-board latency improvement claim. GUI work or third-party threads still sharing the main process can interfere. Minimum intervals can be below 1 ms when a late send is followed by the next scheduled slot; neither a precise minimum spacing nor nanosecond interval error is guaranteed. `skipped_slots` counts missed schedule opportunities, not dropped messages. Dispatch lateness is measured before the transport call and is distinct from the TX event timestamp and physical delivery.

## Byte integrity and capture draining

Both systems passed all eight benchmark cases, including:

- 16 MiB TCP receive with and without recording.
- 100,000 indexed 32-byte sends with recording; full reconstructed byte stream checked.
- TCP proxy echo of 8 MiB each direction; both captures verified independently.
- All Sequence messages in idle, thread-load and process-load cases, including capture replay checks after draining.

SHA-256 and byte counts matched the expected streams; no missing, additional or reordered bytes were found in these tests. This does not certify physical links, UART driver overruns, UDP or GUI display retention. UI history remains bounded independently of disk capture.

With asynchronous recording, RX observation time excludes part of disk work. The raw results therefore also include `capture_drained_elapsed_s` for the receive tests. Do not interpret the RX-only `MiB_s` as sustained persisted-disk throughput. Normal flush/close does not establish fsync or power-loss durability.

## Native validation and reproduction

Native Windows/Linux backend, GUI, real transport diagnostics and PyInstaller package tests passed, including dynamic reply templates and capture subprocess startup inside the frozen application. Windows folder and one-file bundles were both verified; Linux's extracted portable package was verified.

- [Windows native tests and portable builds](https://github.com/mohsensafaei/Probe_Communication_Console/actions/runs/40531724181)
- [Linux native tests and portable build](https://github.com/mohsensafaei/Probe_Communication_Console/actions/runs/40531675382)
- [Windows benchmark run](https://github.com/mohsensafaei/Probe_Communication_Console/actions/runs/40531723992)
- [Linux benchmark run](https://github.com/mohsensafaei/Probe_Communication_Console/actions/runs/40531675469)
- [Raw Windows 1.2.2 results](performance-results/transport-windows-1.2.2-2026-10-27.json)
- [Raw Linux 1.2.2 results](performance-results/transport-linux-1.2.2-2026-10-27.json)
- [Historical 1.2.1 baseline and 115200 baud capacity calculations](PERFORMANCE_RESULTS.md)

Run from `source`: `python benchmarks/transport_benchmark.py --output transport-benchmark.json`. The workflow is `.github/workflows/transport-benchmark.yml`. Each raw result records its exact source commit. Re-run on the laboratory PC with its normal GUI workload and actual adapter; use an external logic analyzer or hardware timestamps when physical timing matters. No physical serial hardware was connected here. At 115200 8N1, 32 bytes still require at least 2.778 ms on the wire, independently of this scheduling change.
