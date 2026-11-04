# Project structure and ownership

`source/` is the application root. Launchers, `Probe.spec` and portable build scripts
remain here so existing offline workflows keep working. Run tests from this directory.

| Module | Responsibility |
| --- | --- |
| `probe/app.py` | Application lifecycle, connection coordination, settings and callbacks |
| `probe/ui/layout.py` | Workbench widgets, styling and layout |
| `probe/ui/traffic.py` | Traffic rendering/filtering and export dialog |
| `probe/event_buffer.py` | Thread-safe display handoff and shared queue cost estimation |
| `probe/traffic_model.py` | Headless retained history and bounded per-stream display framing |
| `probe/exporting.py` | Pure CSV, JSONL and readable-text serialization |
| `probe/plot_model.py` | Bounded numeric acquisition, independent of Tk |
| `probe/plot_ui.py` | Plot controls and drawing; re-exports NumericSamples for compatibility |
| `probe/engine.py`, `simulator.py` | Thread-contained asyncio endpoints and simulation |
| `probe/scenario.py`, `timing.py` | Sequence execution and absolute deadlines |
| `probe/recording.py` | Bounded recording worker process |
| `probe/protocol.py`, `comparison.py`, `codec.py` | Payload interpretation, comparison and framing |
| `tests/`, `benchmarks/` | Correctness gates and reproducible measurements |

The two UI mixins share Probe-owned widgets/state; they are presentation components,
not independent application controllers. Neither imports Probe, avoiding a circular
import. Core modules must not import the UI. `test_core_refactor.py` checks headless
imports in a fresh interpreter, serialization and byte integrity.

Transport acquisition and recording are independent of Traffic filtering, pause and
retention. Tk widgets stay on the UI thread. The changes do not introduce a new event
loop, runtime dependency or worker. File formats and the existing public callbacks
remain compatible. PyInstaller follows the new package imports, checked by actual
frozen self-test and GUI smoke runs on each target OS.

This is an incremental separation, not a claim that every class now has one small
responsibility. Application connection/settings code and sequence UI are still large.
A further split should preserve their ownership and cancellation behavior, backed by
native GUI tests; moving files alone would not establish those boundaries.

## Display ownership in 1.4.2

Engine records original events before handing them to `DisplayEventBuffer`. Data
uses a 1,024-event / 8 MiB estimated-memory rolling budget; controls have their own
128-event FIFO so data cannot evict a disconnect or recording error. The dequeue
operation merges their sequence numbers to preserve arrival order. Control-only
overflow is also counted. These budgets are display limits, not recording limits.

Only the UI thread owns `TrafficHistory` and `DisplayFraming`. History has one
ordered mapping, O(1) oldest-row eviction and a batch delta for widgets. `order`
is a compatibility snapshot for selection/export consumers, not a second mutable
source of truth. A frame batch is consumed lazily and trimmed before widgets are
created. Framing retains at most 64 streams; metadata never retains the original
read's payload. Stream-limit flushes and display-loss flushes are visibly partial.

A dropped data ordinal resets display framing, terminal and plot state before
the next retained read; the queue does not mutate shared recorder/observer events.
Monotonic acquisition timestamps drive idle gaps for live Engine events. Wall-time
fallback preserves imported/demo events without monotonic timestamps. Idle checks
are deferred while the queue is behind. The 8 ms poll budget is cooperative between
events: one expensive payload or widget batch can exceed it. It is not a real-time
latency guarantee. See `DISPLAY_PERFORMANCE.md` for measurements and remaining work.


## Multiple connection workspaces

`WorkspaceWindow` in `workspaces.py` owns the root interpreter, probe tabs, shared
fonts/styles and global key/wheel dispatch. `ProbeWorkspace` is a Frame with its
own Engine, queue, history, settings file, dialogs and tracked timer callbacks.
Closing a Frame cancels only its timers and destroys its descendants; it never
cancels all Tcl timers. Variable traces are released after owned dialogs finish
their destruction cleanup. The `Probe` entry point remains a root window and
forwards legacy read/callback access to the selected workspace; new code uses
`current_probe` explicitly. Hidden workspaces keep bounded models current and
materialize their table on selection. Runtime dependencies are unchanged.
