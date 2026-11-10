# Architecture

Probe is a desktop application, not a framework. Small feature packages work on
bytes and plain Python values; the GUI combines them into independent workspaces.

## Repository map

| Location | Responsibility |
| --- | --- |
| `src/probe/cli.py`, `__main__.py` | Entry points, diagnostics and HID helper mode; lazy GUI startup |
| `src/probe/app.py` | One probe workspace, connection lifecycle, event dispatch and sending |
| `src/probe/settings.py`, `resources.py` | Defaults, atomic settings and source/frozen asset paths |
| `src/probe/transports/` | Engine lifecycle, TCP/UDP, serial, virtual endpoints and config validation |
| `src/probe/traffic/` | Bounded buffers/history, recording, capture import/export, search and tracing |
| `src/probe/analysis/` | Byte codecs, framing, protocol fields, checksums and comparison |
| `src/probe/sequences/` | Step validation, rendering, reply variables/routing and monotonic deadlines |
| `src/probe/simulator/` | Device models, semantic rules/faults and server behavior |
| `src/probe/hid/` | USB capture adapters, authenticated helper, monitor and report decoding |
| `src/probe/plotting/`, `terminal/` | Bounded numeric extraction and ANSI terminal state |
| `src/probe/plugins/` | Metadata, worker lifecycle and API 1 execution |
| `src/probe/ui/` | Tk widgets and feature presentation; no acquisition ownership |
| `src/probe/assets/`, `drivers/` | Licensed fonts/artwork and optional offline Windows USBPcap resources |
| `tests/`, `benchmarks/`, `examples/` | Regression coverage, repeatable measurements and synthetic samples |
| `packaging/`, `scripts/`, `.github/` | Freeze spec, build/check commands and contributor automation |
| `docs/` | User and developer guides, with no stored benchmark result dumps |

UI modules are grouped in one presentation package because they share Tk lifecycle;
core modules are grouped by capability. A one-module feature can remain a small
package rather than being mixed into the application root.

## Runtime ownership

`WorkspaceWindow` owns the Tk interpreter, up to eight tabs, fonts and global keys.
Each `ProbeWorkspace` owns an Engine, display queue, history, settings slot and its
Tk callbacks. `ui/layout.py` and `ui/traffic.py` are presentation mixins around that
workspace, not separate copies of its state. Closing one probe cancels its jobs
and closes its endpoints without stopping other probes.

Tk widgets stay on the GUI thread. Each connected Engine runs asyncio transport
I/O on its own thread. Heavy sequence rendering is offloaded from the event loop.
Recording serialization/disk writes use a bounded process queue when recording is
active. A plugin worker starts lazily only when enabled; analysis is asynchronous,
while explicitly enabled transforms must finish before sending/forwarding.
The HID helper is a separate narrowly scoped process and never loads user plugins.

## Data flow and limits

Transport events are recorded before display grouping/filtering. The display queue
bounds data to 1,024 events / 8 MiB and maintains control events separately.
`TrafficHistory` retains a bounded rolling window. `DisplayFraming` assembles
per-flow byte streams and flushes partial frames across gaps/disconnects.
Hidden probes update bounded models without rendering their entire Traffic table.
Selecting a probe refreshes its visible table from history.

Flows distinguish session, direction, peer and proxy client. Original input bytes
and resulting wire bytes remain distinguishable after transforms. Length-changing
transforms retain source-chunk provenance rather than inventing byte offsets.
Trace works on explicit snapshots, off the acquisition path. Plugins, captures and
imports have explicit byte/count/time limits; overload is surfaced in status events.
A bounded GUI is not a lossless archive; use raw recording for long sessions.

## Change boundaries

Core packages do not import `ui`, `app` or Tk. Transport adapters receive their
Engine explicitly and reuse its event/recording/transform path. New protocols should
normally be an inspector/profile or plugin; new connection types belong in
`transports`. Keep parsing testable without a desktop and preserve the documented
file/plugin contracts when moving modules.

[test_structure.py](../tests/test_structure.py) checks headless imports, the UI
boundary, settings roundtrips and configuration validation. See [testing](testing.md)
and [building](building.md) before changing worker or frozen-resource paths.
