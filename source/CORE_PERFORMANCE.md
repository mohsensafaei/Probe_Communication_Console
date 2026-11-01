# Core processing performance — 1.4.1

Measured locally on CPython 3.12.14, Linux, 2026-11-01. Values are medians of five
runs using `python benchmarks/core_benchmark.py`. Compare against parent 1.4.0
on the same host. This is CPU processing time, not network/UART latency, scheduling
precision, memory usage or an end-to-end UI benchmark.

| Workload | Before (ms) | After (ms) | Speedup |
| --- | ---: | ---: | ---: |
| display_64k | 6.938 | 3.635 | 1.9× |
| fixed_frames_64k | 9.094 | 7.319 | 1.2× |
| diff_equal_256k | 273.4 | 0.002 | 136700.0× |
| diff_changed_256k | 267.303 | 26.236 | 10.2× |

The equal-payload case now returns immediately without allocating per-byte token
and span lists. Its microsecond measurement is near timer overhead; the large
ratio is not representative of changed payloads. Changed ordinary byte comparisons
use bytes directly. Comparisons with ignored fields still build offset maps and
must validate missing/overlapping masks, even for equal inputs.

Control-character labels are precomputed, framing deletes the consumed prefix once
per feed, and a Traffic rebuild snapshots search/view settings once. Tk insertion,
large protocol parsing and SequenceMatcher's changing middle can still be costly.
There is no hard real-time or general throughput claim. Re-run the benchmark on the
laboratory machine; use `benchmarks/transport_benchmark.py` for actual I/O timing.

Correctness gates cover arbitrary split/coalesced framing, original comparison
ranges, all export choices and metadata, legacy simulator models, cancellation,
serial/TCP flows, native GUI and extracted portable packages.
