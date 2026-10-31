# Probe for Windows 1.3.0

Portable TCP, UDP and USB/COM workbench with traffic recording/replay, a live
ANSI terminal, serial proxies, recorded device simulation and timed test sequences.

Version 1.2 adds **Protocol Inspector**, **Capture Diff**, and **sequence variables
and conditions**. Click a traffic row to open Analyze, or use its right-click menu. Advanced sequence rules stay inside the message editor.

## Run

Download the verified `Probe-windows-x64` artifact from this branch's
[Windows builds](https://github.com/mohsensafaei/Probe_Communication_Console/actions/workflows/windows.yml).
Extract the outer artifact ZIP, then extract `Probe-windows-x64.zip` and open
`Probe/Probe.exe`. Keep the entire folder together. The optional
`Probe-windows-x64-onefile.zip` contains a single executable and starts more slowly.
The portable packages include Python and Tcl/Tk; Python installation is unnecessary.

To run from source, install Python 3.10+ with Tcl/Tk (the standard python.org
Windows installer), then double-click `source\start_windows.bat`, or run:

```bat
source\start_windows.bat
source\start_windows.bat --self-test
```

The launcher creates `.windows-venv` and installs pinned dependencies on first use.
Initial dependency installation requires Internet access. Set `PROBE_PYTHON` to a
Python executable path to select an interpreter explicitly. Use `loop://` in
**USB / Serial** for a hardware-free check. For a USB device, select its actual
COM port and serial parameters. Close other software that already owns that COM.

## Hardware test lab

**Test lab** is at the bottom of the control panel; **Appearance** is removed.
The title shows version 1.3.0, and the sidebar has eight modes including
**Device Simulator**.

* **Device simulator:** record TX/RX with the real device, then load the capture
  in Test lab or use retained traffic history. Select one peer and build/save a
  model. Expose it as a TCP socket or an installed virtual COM pair. The other
  application receives recorded replies to exact matching requests, including
  response timing and stateful conversations. The original physical device can
  be disconnected. Edit requests, replies and delays, or reset matching.
* **Test sequences:** choose messages, select **After interval** or **After a reply**, then Run.
  **Choose captured messages…** opens an RX/TX picker (RX initially selected)
  with source/peer filters, previews and explicit message selection. Add the
  composer or write a new message instead. The destination is always displayed.
  Select **Run once**, **Repeat a set number** or **Repeat until stopped**.
  Edit a message for advanced repeats/reply checks; enable individual delays
  only when needed. Sequence files with custom timing keep their timing/checks.

For a 100 ms test: connect the port/socket in the main window, open **Sequences**,
choose the captured RX or TX records you want, set **Interval between messages**
to **100**, leave **Run once**, then click **Run sequence**. Changing the shared
interval updates the table and the next Run/Save immediately; no per-row Update
is needed. Loading a capture in the picker does not disconnect or replace the
main traffic view. **Keep recorded intervals** is an explicit advanced option.

For reply-driven sending: **Sequences → Set timing → Send next message → After
a reply**. Set **Reply timeout**, then **Run sequence**. The first message sends
immediately; each next message waits for incoming data from the destination,
with no interval delay. The final reply completes the run. Timeout stops the
run, and **Stop** cancels the wait. Optional **Edit message… → Advanced →
Expected reply** hex bytes require a specific response across receive chunks.
Otherwise any nonempty receive chunk, including unsolicited data, counts.
**After interval** restores the previous timing. Stop and other buttons now have
readable disabled labels and a solid focus border instead of dotted outlines.

RX and TX describe the original recording relative to Probe; either source can
be sent again. For commands to a physical device, the recorded TX is usually
appropriate; recorded RX can reproduce a device's replies toward an application.
Check **Send to** before running: choosing RX does not change the destination.

Try `source/examples/device-model.json` and `source/examples/test-sequence.json`
with two Probe windows: one **Device Simulator / TCP socket**, one **TCP Client**.
These are synthetic PING/BUY examples; use your device's real protocol bytes.
Timings are best effort; captures do not infer dynamic fields or encryption.

## USB proxy and virtual COM simulation

Install a signed virtual serial-pair driver compatible with your Windows version
and create a pair such as **COM20 ↔ COM21**. Probe does not install drivers.

* **Serial Proxy:** physical device = COM3, Probe-side virtual port = COM20,
  application-side partner = COM21. The other software opens COM21. Probe opens
  COM3 and COM20, forwards bytes and records TX/RX. Choose the injection side to
  send toward the hardware or the application.
* **Device Simulator / Virtual COM pair:** Probe-side = COM20, app-side partner
  = COM21. Load a model and start; your other software opens COM21. Only COM20
  is opened by Probe; the original hardware is unnecessary.
* **Serial ↔ TCP:** expose a physical COM port on a local TCP listener. This
  workflow needs no virtual COM driver when the application can use a socket.

The partner is entered explicitly; Probe displays/copies that application-side
port. Both ends and any physical port must be different. Match the pair's line
settings to the application. Proxying forwards bytes; app-side baud/modem-line
changes are not automatically applied to the physical device. USB means CDC/UART
COM devices, including supported phones; arbitrary USB/MTP/HID interception is
outside this backend.

## Build and test on Windows

```bat
source\build_windows.bat
source\build_windows.bat --onefile
cd source
.windows-venv\Scripts\python.exe -m unittest discover -s tests -v
.windows-venv\Scripts\python.exe -m unittest discover -s tests -p ui_smoke.py -v
.windows-venv\Scripts\python.exe verify_bundle.py dist\Probe-windows-x64.zip dist\Probe-windows-x64-onefile.zip
```

The build launcher creates `.windows-build-venv`, installs pinned runtime/build
requirements, builds natively and runs the frozen executable's real I/O self-test.
CI additionally extracts both ZIPs outside the repository and checks the frozen
GUI, all eight modes and both Test lab tabs. Artifacts upload only after checks
pass. Build outputs, local preferences and environments are excluded from Git.

Physical AT-capable USB hardware checks require explicit port selection:

```bat
set PROBE_TEST_SERIAL_PORT=COM3
set PROBE_TEST_APP_PORT=COM20
set PROBE_TEST_PEER_PORT=COM21
set PROBE_TEST_GUI=1
.windows-venv\Scripts\python.exe -m unittest discover -s tests -p test_serial_hardware.py -v
```

These tests send only `AT` attention commands, verify direct USB, COM proxy,
injection, exact captures, Serial-to-TCP, GUI and emulation after the original
session closes. They are skipped by default. Windows kernel-driver/physical USB
verification requires the actual Windows device and COM-pair driver; ordinary CI
uses loopback and real pySerial socket endpoints instead.

See [the full guide](source/README.md), [feature coverage](source/FEATURE_MATRIX.md)
and [validation scope](source/VALIDATION.md).

## Traffic, live plot and terminal

The main workspace has three pages: **Traffic**, **Live plot** and **Terminal**.
Click a traffic row (or select it and press Enter) to open one reusable Analyze
window with **Decoded text**, **Hex + ASCII**, **Every byte**, Protocol Inspector
and Capture Diff. The separate Analyze button and lower byte-inspector panel
are removed. Receiving, filtering or following traffic does not open windows.

Live plot reads RX numbers/CSV terminated by LF, such as `1,2\n3,4\n`. It
shows up to four channels and keeps partial lines separate for each peer. JSON,
binary frames and TX-only traffic are not numeric plot samples. Terminal shows
received ANSI/text automatically; enable **Send keyboard**, then click the screen
to type. Enter and Backspace are configurable. The composer, target and injection
side remain visible on all three pages.

## Probe visual identity

The interface uses an original hardware test-probe emblem, satin-edged blue
instrument panels and mint readouts. Geometric Michroma headings, Rajdhani
controls and Share Tech Mono data fonts are bundled with OFL notices.
The light palette preserves the same controls and message workflows.
No vendor logo or proprietary skin is used.
