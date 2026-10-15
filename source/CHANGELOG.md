# Changes

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
