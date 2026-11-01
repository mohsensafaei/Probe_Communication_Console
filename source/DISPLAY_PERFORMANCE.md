# Display pipeline review — 1.4.2

The previous structural split left transport-to-UI buffering and retained history
inside widgets. This change moves those ownership rules into independently tested
models and addresses overload correctness as well as rendering cost.

## Findings and changes

| Finding in 1.4.1 | Result in 1.4.2 |
| --- | --- |
| A full 1,024-event FIFO evicted any oldest event, including disconnect/error status. Payload size was not bounded. | Separate ordered data/control lanes; data limited by count and estimated bytes including HID metadata. Status cannot be evicted by data. |
| Framing joined surviving chunks across display data loss. | Data ordinals detect discontinuities; pending frames are flushed as partial, terminal/plot parsers reset, then retained data resumes. |
| Each generated frame was formatted, searched, inserted and often immediately deleted. | Lazy frame generation; retention runs first; only surviving new rows touch Tk. |
| History had a dictionary plus a separately mutable list using `pop(0)`. | One ordered mapping with constant-time oldest-entry removal and explicit batch deltas. |
| A row larger than the retention budget was evicted from the model and then still inserted into the table. | Only retained IDs can be rendered. |
| UDP/new peer identities could leave unlimited framers and full last-read payloads attached to metadata. | At most 64 stream states; evicted partial bytes remain labelled; metadata excludes the original payload. |
| UI backlog could be mistaken for a wire idle gap; wall-clock jumps affected live grouping. | Consume queued acquisition timestamps first and use monotonic timestamps for live events. |
| Hex/decimal previews decoded text they did not display. | Format the selected representation only. |
| One poll could process 180 expensive reads before yielding. | Check an 8 ms cooperative budget between reads; follow up after 5 ms while behind. |

Recording remains upstream of this display pipeline. An integration test fills the
display queue, drops 99 of 100 UI events, and verifies all 100 original payloads
and unchanged metadata in the recording. This does not make the recorder immune
to disk errors or its own queue limits; those continue to report incomplete files.

## Measurement

Measured 2026-11-02 with CPython 3.12.14, Tk 9.0.4 and Xvfb on Linux. The same
benchmark, interpreter and display were used for baseline and updated source.
The baseline display code is identical in Windows `5764c81` and Linux `2c51623`.
These are Linux measurements, not native Windows results.

One 64 KiB RX event, fixed one-byte framing, 2,000 retained rows, three runs per
version. Includes terminal/plot ingestion, traffic processing and Tk idle work.

| Metric | Before | After |
| --- | ---: | ---: |
| Median elapsed time | 2,011.161 ms | 236.527 ms |
| Table insertions per read | 65,536 | 2,000 |
| Final retained rows | 2,000 | 2,000 |

This workload improved **8.50×**. It is deliberately stressful small-frame display
work, not a claim that every operation or transport became 8.50× faster. Timings
vary with host load. Raw samples are in `performance-results/display-1.4.2.json`.

Run from `source/` with an X display on Linux (native console on Windows):

```sh
python benchmarks/display_benchmark.py /path/to/baseline/source
python benchmarks/display_benchmark.py
python -m unittest discover -s tests -v
python -m unittest discover -s tests -p ui_smoke.py -v
python run_probe.py --self-test
```

Local verification: 163 backend tests, 155 passed and 8 platform/hardware skips;
49 native Tk tests passed; built-in transport diagnostics passed for TCP,
UDP, serial loopback, Linux PTY/proxies, simulator, sequences, recording and
protocol/HID parsing. No physical COM, USB or native Windows timing was measured
locally. PR workflows separately run native tests and frozen builds on each OS.
The original narrow JSON search value field failed its existing layout test on
this Tk host too; reducing the adjacent field entry width makes that test pass.

## Limits and remaining architectural work

- The poll budget is checked between input events. A single expensive payload,
  terminal parse, JSON search or retained widget batch can exceed 8 ms. The stress
  case above still takes about 237 ms. There is no hard real-time UI guarantee.
- Search/rebuild, export and some analysis actions still execute synchronously on
  the UI thread. These need cancellation-aware workers or incremental rendering
  before very large interactive sessions can be described as fully responsive.
- Application connection/settings coordination and sequence editors remain large.
  The headless display boundary is now concrete; the whole application has not
  been rewritten into independent controllers.
- Display data retains up to 1,024 events within an 8 MiB estimate; controls retain
  their latest 128 events. Control-only floods are bounded and explicitly counted.
  History retains up to 2,000 rows / 8 MiB of payload; stream buffers are separately
  bounded. These are not an exact whole-process RSS cap.
- Clearing terminal/plot parsers after a known gap is conservative across peers.
  Recorded files are the source for complete stream analysis under display overload.
