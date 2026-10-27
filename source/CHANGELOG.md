# Changes

## Focused workspace workflows

* Detach/dock Terminal without two visible terminal screens.
* Remember Analyze pages; default comparison to selected message direction.
* Simplify protocol choices to Auto / Raw Bytes and remove global Choose traffic.
* Add Auto/Custom plot modes for JSON paths, text columns, named values and fixed binary fields.

## Instrument identity refinement

* Restore framed blue instrument panels and satin edges with mint readouts.
* Original hardware test-probe emblem with insulated grip, contact tip and cable.
* Matching application icon and geometric headings on both platforms.

## Visual identity refresh

* Original connected-endpoint mark and lowercase Probe wordmark.
* Flat graphite/teal/violet workbench, matching light palette, unified headings.
* Removed metallic chassis, ornamental rails and faux meter stripes.
* Retained transport workflows, keyboard focus and bundled OFL font notices.

## 1.2.1 (Windows / Linux)

* Consolidate the main workspace into Traffic, Live plot and Terminal. Move decoded text, hex/ASCII and every-byte paging into Analyze; remove the extra Analyze button and lower inspector panel.
* A single traffic-cell click (or Enter) opens/reuses Analyze, preserving the chosen analysis tab. Filtering, following and programmatic selection do not open windows. Keep copying/saving all snapshot bytes and explicitly loading the composer.
* Replace positional tab indices and automatic split-pane sizing with stable widget identities and full-page views. Keep target/injection-side/composer controls available on Terminal.
* Make Send keyboard focus the terminal screen, improve connected/view-only/listening hints, add vertical scrolling and fit all terminal/history controls in two rows. Fix serial bridge RX filtering when a specific TCP client is selected; allow typing to the sole TCP client before its first reply and retain text after peer disconnect.
* Give Live plot explicit RX numeric-format guidance, peer selection, independent partial lines, bounded samples and a visible single-sample point. Reject binary/non-finite/oversized lines, batch rendering with the UI poll, and preserve main traffic when clearing a plot.
* Add native mouse-click, serial-loop plot/keyboard, selected-client bridge and first-key TCP regressions; expand frozen GUI diagnostics. No runtime dependencies added.

## 1.2.0 (Windows / Linux)

* Add a single Analyze entry beside traffic and context-menu shortcuts. Protocol Inspector decodes JSON (including ASCII body-length prefixes), explicit one-byte TLV or definite BER-TLV, with exact byte highlighting and copied field paths.
* Add editable custom binary fields with integer/float/text interpretations, length and checksum validation, saved profiles and clear mismatch/truncation status.
* Capture Diff compares selected messages or concatenated single-peer/direction streams from history/capture/binary files. Show added/removed/changed ranges, ignore JSON values or byte ranges, and export original bytes plus comparison rules/results.
* Add optional response rules to sequences: JSON/TLV/byte extraction, named variables, literal/JSON/hex substitution, conditions and stable next/goto/finish/fail routes, including timeout routing. Recompute optional frame length/checksum after substitution.
* Keep the simple sequence page. Response rules use separate Save reply values / Choose next step tabs, an explicit captured-field picker, Save/Cancel and always-visible editor actions. Initial and last received variables have their own dialog.
* Version 3 sequence files retain variables/routing/templates while legacy/version 1/2 files still load. Missing variables/fields and dangling branch targets fail explicitly; loops, reply sizes and offline analysis are bounded. No new runtime dependencies.
* Exercise new modules in source and frozen self-test/GUI diagnostics, including actual TCP extraction and templated sends. Add runnable read-only SESSION/STATUS simulator/sequence examples and a custom protocol profile.

## 1.1.2 (Windows / Linux)

* Add a clear After interval / After a reply sequence control. Reply mode sends immediately after incoming data, with no interval delay, a shared timeout and visible waiting status. Stop cancels pending waits.
* Preserve optional expected-byte matching across receive chunks, repeats, cycles and legacy timing/checks. Export/import reply mode and restore prior timing when switching modes.
* Route reply checks to the selected client and injection side; ignore outgoing sends, other clients, empty data and traffic preceding the send.
* Fix disabled button text contrast, including Stop and hovered disabled buttons. Remove Clam's dotted button focus element while preserving keyboard traversal and a solid focus border.
* Add real TCP/serial gating, timeout/Stop, immediate/split reply, mode-switch, JSON round-trip and button-contrast regressions. No new runtime dependencies.

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
