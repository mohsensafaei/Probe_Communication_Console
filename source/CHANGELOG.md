# Changes

## Unreleased

- Preserve CSV capture timestamps across time zones and avoid Windows conversion errors for early timestamps.

- Add read-only live TCP Monitor with a port filter, loopback capture and raw PCAP export through system libpcap/Npcap.

- Open PCAP/PCAPNG files in Traffic, reassemble TCP streams and keep capture gaps separate from reusable messages.

- Let Python `respond()` plugins generate and automatically send Device Simulator replies from complete matched requests.

- Fix Save analysis to honor the inspector’s selected Auto/Raw Bytes mode instead of applying a saved custom profile implicitly.

- Fix Sequence import preview to show the editor’s 100 ms default and actual reply-gating rules.

- Isolate diagnostic preview CPU work in an on-demand process; transfer only chosen rows and enforce case bounds before spawning.

- Publish configuration/evidence JSON Schemas and review validated Sequence, Simulator and Protocol imports before applying them.

- Share bounded diagnostic cases from selected multi-probe evidence, with local preview/copy/ZIP, literal masking and explicit capture-health limits.

- Export structured inspector findings with exact values/ranges and explicit clock-scoped observation intervals.

- Preserve stable message IDs, bounded framed source byte ranges and acquisition timing through JSONL export/import; copy and locate IDs in Traffic.

## 1.7.0

- Add per-probe Python plugins with a one-function process API and optional rebuild, action and opt-in transform hooks.
- Reuse Analyze fields, Capture Diff previews and named Live plot sources; keep original bytes and explicit sending.
- Isolate user code in one lazy reusable worker per probe with bounded queues/results, timeouts and connection state; report analysis loss and block failed transforms.
- Support direction filters, portable plugin folders, complete-frame transforms, original RX recording and offline examples / authoring guide.
- Exercise real TCP proxy/serial behavior, native UI workflows, worker performance and frozen plugin execution.

## 1.6.2

- Restore retained Traffic rows when a probe becomes visible, including first display and restoring a hidden window; preserve active filters and Pause without rendering background probes.
- Cover initial visibility, real TCP reception while hidden and filter/pause restoration in native GUI tests.

## 1.6.1

- Replace the separate Close probe button with a stable-width tab close icon shown on hover; close the clicked probe without selecting it, and cancel on drag-off.

- Simplify Traffic search to Text and Hex bytes; remove the JSON-field selector and backend mode, migrate old preferences, and keep explicit Search/Enter behavior.

## 1.6.0

- Add an on-demand two-probe Trace path: reference selection, exact byte spans across split/coalesced reads, optional scalar JSON identifier and explicit manual matching.
- Keep repeated matches ambiguous, label recorded intervals and reuse Capture Diff with the correct A/B probe pickers. Trace snapshots do not add work to acquisition.
- Apply Traffic search only with Search or Enter; changing type resets the applied search, blank inputs keep traffic visible and invalid input preserves previous results.
- Exercise native trace/diff/cleanup/search workflows and benchmark an approximately 8 MiB retained stream scan.

## 1.5.0

- Add up to eight independent, named Probe workspaces with a + button; each owns its endpoints, traffic, analysis, sequences, recording, plot and terminal.
- Keep acquisition running in background tabs while deferring hidden traffic widget creation and drawing.
- Share one Tk interpreter, font load and global shortcut/wheel dispatch; isolate callbacks and shutdown per probe.
- Save endpoint/profile/sequence preferences separately by probe slot and restore them when that slot is reopened.
- Exercise simultaneous TCP and serial loopback, hidden recording, close isolation, timer cleanup and frozen multi-probe connections.
- Add a native 1/2/4-probe CPU/Python-allocation benchmark.

## 1.4.2

- Extract bounded display handoff, retained history and per-stream framing into headless models.
- Keep connection/recording status separate from data pressure; budget queued payloads and HID metadata and expose loss counts.
- Reset incomplete display parsers across dropped data; mark partial frames instead of joining bytes across a known gap.
- Stream frame generation and apply retention before creating table rows; format only retained rows and the selected view.
- Bound framing state to 64 streams, use acquisition monotonic timestamps for idle gaps, and avoid idle flushing while the UI is behind.
- Cooperatively yield between input events and schedule earlier follow-up polls while backlogged.
- Keep the JSON search value field usable at the minimum window width.
- Add headless regression tests, native Tk overflow/burst tests and a reproducible display benchmark; run native workflows on pull requests.

## 1.4.1

- Separate Tk workbench construction and Traffic callbacks from application coordination.
- Extract headless export serialization and numeric acquisition models; retain public callbacks and NumericSamples import compatibility.
- Avoid per-byte span allocation for ordinary Capture Diff and coalesce masked equal runs before allocating results.
- Translate control characters with a precomputed table; consume display-frame buffers once per feed.
- Read search/view settings once per Traffic rebuild rather than per row.
- Add reproducible core microbenchmarks and regression checks for data integrity, offsets, export metadata and headless imports.

## 1.4.0

- Add semantic request rules for JSON paths, TLV/BER-TLV tags, UTF-8 text and byte ranges; AND conditions, required fields and numeric comparisons.
- Assemble complete requests independently of socket/serial read chunks, with explicit JSON/delimiter/fixed/length-prefix framing and optional trailing checksum validation.
- Add deterministic per-rule/per-client fault triggers: delay, no reply, error payload, disconnect, truncation, byte corruption, duplicate and split writes.
- Replace inline simulator editing with a focused Request & reply editor and optional Fault injection tab; retain recorded chunk timing unless edited.
- Save advanced models as v2 while preserving v1 compatibility; include JSON and binary CRC examples.
- Exercise real TCP/PTY, per-client counters, ambiguity, malformed requests, Reset/Stop cancellation, native editors and frozen semantic/fault diagnostics.

## 1.3.1

- Add native Ctrl/Shift multi-selection in Traffic while preserving single-click selection and double-click Analyze.
- Keep selected rows across refresh/view changes and preserve multi-selection on right-click.
- Add Capture Diff for exact selected pairs, with a selected-only A/B picker for larger selections.
- Add snapshot Export selected for JSONL/CSV/text with existing Hex / Decoded text choices; toolbar Export keeps its full-history scope.
- Exercise native selection, context actions, export scope during live retention and frozen selected-pair comparison.

## 1.3.0

- Add USB HID Monitor with device selection, RX/TX report capture and descriptor-based Analyze fields.
- Keep normal startup unelevated; request permission only for HID capture/discovery or explicitly invoked offline driver setup.
- Bundle original USBPcap 1.5.4.0 installer, corresponding source and licenses; use the running kernel usbmon on Linux without downloads.
- Preserve report bytes and metadata in JSONL; support HID field search, descriptor import/export and read-only engine guards.
- Add capture-format, decoder, helper, UI cancellation and portable resource checks. Live physical HID capture still requires validation on the target workstation.

## 1.2.2 — deadline scheduling and capture isolation

* Use absolute interval deadlines across sequence messages/repeats/cycles; count missed slots without dropping messages or replaying an overdue burst.
* Preserve reply-gated behavior and explicit post-reply delays; complete interval mode after the final send (no trailing interval).
* Report dispatch lateness and missed slots; add monotonic/scheduled metadata to sequence captures.
* Move capture encoding/writes to a bounded worker process, with drain-on-stop and explicit incomplete-recording errors.
* Offload dynamic template and reply-field processing to another process; throttle routine progress notifications.
* Support multiprocessing in source/module entry points and PyInstaller bundles.

## Traffic search

* Add visible Text, Hex bytes and JSON field filters with matching/retained counts.
* Match full retained payloads and decoded JSON values; validate byte-aligned hex.
* Apply search to live and paused history without changing captures.

## Plot workspace layout

* Move Value source, custom configuration, RX peer and Clear into one compact footer.
* Give the chart all remaining height; show setup guidance only when no samples exist.

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
