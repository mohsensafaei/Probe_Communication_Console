# Project structure and ownership

`source/` is the application root. Launchers, `Probe.spec` and portable build scripts
remain here so existing offline workflows keep working. Run tests from this directory.

| Module | Responsibility |
| --- | --- |
| `probe/app.py` | Application lifecycle, connection coordination, settings and callbacks |
| `probe/ui/layout.py` | Workbench widgets, styling and layout |
| `probe/ui/traffic.py` | Traffic rendering/filtering, retention and export dialog |
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
