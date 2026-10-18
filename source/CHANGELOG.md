# Changes

## 1.1.1 (Windows)

* Simplify Sequences to choose messages, set timing and send; show the actual destination and separate message editing into a Save/Cancel dialog.
* Replace TX-only capture conversion with an RX/TX picker, initially RX, with source/peer filters, previews, selection and loading a capture without replacing the main traffic view.
* One shared interval immediately controls the table, Run and Save; individual recorded/file timing is explicit and preserved, alongside repeats and expected replies.
* Replace numeric infinite-cycle configuration with Run once, Repeat a set number and Repeat until stopped. Keep advanced per-message options in the editor.
* Preserve original capture bytes/order and composer transforms; keep source direction independent of the outgoing destination.
* Lock sequence editing while running, keep Stop visible on short windows and decouple timing from the composer's Repeat interval.
* Add RX/TX binary capture, bounds, GUI selection, timing-on-wire, legacy import, exact edit/cancel and continuous-stop regressions.

## 1.1.0 (Windows)

* Bring all recording/replay, Test lab device models, timed/reply-checked sequences and Appearance removal to Windows.
* Simulate a recorded device through an installed virtual COM pair as well as TCP; the physical device is unnecessary.
* Correct Serial Proxy endpoint reporting: display/copy the application-side partner, never the COM opened by Probe. Reject aliased COM names.
* Isolated Windows source/build launchers install pinned dependencies, select Python explicitly and preserve failure exit codes without pausing CI.
* Native Windows x64 CI tests source, GUI and both extracted portable ZIPs before artifact upload. Windowed diagnostics can write JSON reports.
* Correct early 5–10 ms sequence/reply delays on coarse Windows asyncio clocks; use high-resolution duration checks and cancellable bounded worker sleeps.
* Version visible in the window title. Windows hardware tests accept explicit physical and virtual-pair COM ports.

## 1.1.0 (Linux)

* Hardware Test lab with a recorded device simulator on TCP or an independent Linux virtual serial PTY.
* Capture-to-model conversion, peer selection, ordered stateful conversations, independent request rules, editable response bytes/timing and model JSON import/export.
* Up to 1000 editable test steps with per-step millisecond delays, repeats, optional reply checks/timeouts, finite or continuous cycles, progress and cancellation.
* Sequence import/export, retained TX conversion, composer snapshots, duplicate/reorder and legacy shelf migration.
* Appearance button replaced by Test lab.
* Close accepted connections before server cancellation so Stop remains responsive with clients still connected.
* Regression coverage for emulation after original device closure, stream splits/coalescing, independent clients, timing, reply failures, long loops and GUI workflows.

## 1.0.0 (Linux)

* Linux launcher creates an isolated environment, installs pinned dependencies and selects Python with working Tkinter.
* Serial permission errors name the device's actual group and explain how to enable access; unused `n/a` UARTs are no longer selected automatically.
* Added executable `--self-test` for real serial loopback, Linux PTY direct/proxy/TCP bridging, TCP/UDP, captures and ANSI terminal support.
* Portable builds run the executable self-test and exclude personal settings from archives.
* Bundle Tcl/Tk shared libraries from standalone Python installations so the Linux executable starts without system Python/Tk.
* Added Linux serial permission, unplug and GUI device reconnect regression tests.

## 0.3.0

* ASUS PC Probe II-inspired silver chassis, blue instrument panels, recessed LCD readouts and original geometric Probe wordmark.
* Bundled Michroma headings, Rajdhani controls and Share Tech Mono data fonts, privately loaded on Windows/Linux; full OFL notices included.
* Compact controls, equal-width status readouts, responsive short-window layout and practical traffic/inspector sizing. Terminal selection expands its screen and restores the composer when leaving the tab.
* Portable, hand-authored `Probe.spec` with default Windows onefile EXE output, optional folder mode, icon, fonts and serial handlers. No hardcoded machine paths, console window or UPX requirement.
* Build scripts now reuse the spec without replacing it and keep folder/onefile output paths separate.

## 0.2.0

* Live ANSI/VT-style screen, colors, cursor controls, scrollback, alternate screen and a pop-out terminal window.
* Direct keyboard sends, configurable Enter and Backspace, control/function keys, paste and optional local echo.
* Incremental character decoding and bounded terminal escape strings. Raw capture remains byte-exact.
* Offline JSONL/CSV capture import, timed TX/RX replay with speed control and cancellation.
* Double-click payload reuse and a traffic context menu.
* Hercules-style decimal/hex/control tokens and LRC8 checksum.
* Whole-command-shelf looping and byte-counter reset.
* Bounded pending-send memory and automatic replay cancellation on disconnect.
* Window starts at a size appropriate for the display rather than always requesting 900 pixels of height.
* Terminal library licenses and replacement/rebuild source included in portable bundles.
* STM32 programming is explicitly excluded from scope at the user's request.

HW-group's proprietary UDP Setup/TEA/I/O support is still not implemented; accessible verified protocol/SDK information and hardware validation are needed.
