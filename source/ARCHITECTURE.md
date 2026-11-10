# Project structure and ownership

Run commands and tests from `source/`. `run_probe.py` and `python -m probe` share
`probe/cli.py`; PyInstaller still uses `Probe.spec` and the existing assets.

| Location | Responsibility |
| --- | --- |
| `probe/cli.py` | Arguments, helper mode and diagnostic entry points; loads Tk only for GUI startup |
| `probe/app.py` | Workspace state, connection lifecycle, event dispatch and send controls |
| `probe/settings.py` | Defaults, writable data directory and atomic settings persistence |
| `probe/engine.py` | Async lifecycle, recording, send limits, plugin transforms and sequence coordination |
| `probe/transports/config.py` | Endpoint validation and display-framer configuration without widgets |
| `probe/transports/network.py` | TCP client/server/proxy, UDP and network client cleanup |
| `probe/transports/serial.py` | Serial ports, full-duplex I/O, virtual serial endpoints and bridge reads |
| `probe/ui/layout.py` | Widgets, transport controls, styling and responsive layout |
| `probe/ui/traffic.py` | Traffic rendering, selection, search, export, capture import and replay |
| `probe/ui/analysis.py` | Analysis window and byte/text views |
| `probe/ui/inspector.py`, `comparison.py`, `traffic_picker.py` | Protocol fields, Capture Diff and message selection |
| `probe/ui/widgets.py` | Small controls and validation feedback shared by analysis editors |
| `probe/ui/sequence.py`, `sequence_capture.py`, `sequence_flow.py` | Sequence editing, capture selection and response rules |
| `probe/ui/plot.py`, `terminal.py`, `plugin.py` | Plot, terminal and plugin presentation |
| `probe/ui/testlab.py`, `simulator.py`, `hid.py` | Hardware-test and device-monitor controls |
| `probe/ui/workspaces.py` | Root window, probe tabs and global shortcuts |
| `probe/ui/skin.py`, `typography.py` | Instrument artwork and privately loaded fonts |
| `probe/ui/diagnostics.py` | GUI smoke test, separate from normal startup |
| `tests/`, `benchmarks/` | Regression tests and repeatable performance checks |

Core modules remain small files named for their work: `codec`, `protocol`,
`comparison`, `capture`, `traffic_search`, `trace_path`, `traffic_model`,
`plot_model`, `plot_extract`, `terminal`, `plugins`, `scenario`, `sequence_flow`,
`simulation`, `simulator_rules`, `timing`, `recording` and the HID modules.
They can be tested without a Tk interpreter. The plugin API and capture,
profile, sequence and simulator file formats retain their existing contracts.

## Boundaries

`ProbeWorkspace` owns one Engine, display queue, history, settings file and its
Tk callbacks. Its two presentation mixins share that workspace's widgets.
`WorkspaceWindow` owns the single Tk interpreter, tabs, fonts and global keys.
Network and serial functions receive the engine explicitly and use its common
recording/transform path. Core modules never import presentation modules.

Tk widgets stay on the GUI thread. Transport I/O stays on the engine's asyncio
thread. Recording and plugin processes retain their cancellation and byte-order
contracts. Moving UI code does not add polling, processes or runtime dependencies.

## Capture and display

Engine records transport events before GUI grouping or filtering. The display
queue bounds data to 1,024 events / 8 MiB and keeps a separate control FIFO.
`TrafficHistory` owns retained rows; `DisplayFraming` owns bounded stream buffers.
Framing and Trace distinguish session, direction, peer and proxy client.
Equal-length transforms preserve original bytes through splitting and joining.
Length-changing transforms keep their exact chunk provenance and partial label.
A display gap flushes pending frames before more data is grouped.

Each probe cancels its own callbacks and dialogs on close. Hidden probes keep
collecting bounded models; selecting one refreshes its visible table. Trace uses
an on-demand snapshot and the existing comparison view.

## Verification

Run `python -m unittest discover -s tests -v`, GUI tests with `-p 'ui_*.py'`,
`python run_probe.py --self-test`, and `--smoke-test` with a display.
`test_structure.py` checks headless imports, the UI boundary, settings roundtrips
and widget-free configuration validation. After packaging, run both diagnostics
on the target operating system. Physical HID/serial and native Windows paths need
an appropriate target machine.
