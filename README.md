# Probe for Windows 1.1.0

Portable TCP, UDP and USB/COM workbench with traffic recording/replay, a live
ANSI terminal, serial proxies, recorded device simulation and timed test sequences.

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
The title shows version 1.1.0, and the sidebar has eight modes including
**Device Simulator**.

* **Device simulator:** record TX/RX with the real device, then load the capture
  in Test lab or use retained traffic history. Select one peer and build/save a
  model. Expose it as a TCP socket or an installed virtual COM pair. The other
  application receives recorded replies to exact matching requests, including
  response timing and stateful conversations. The original physical device can
  be disconnected. Edit requests, replies and delays, or reset matching.
* **Test sequences:** create/reorder/duplicate steps with separate payloads,
  millisecond delays, repeats, optional reply bytes and timeouts. Set finite
  cycles or 0 for continuous running. Import/export complete sequences. Connect
  the desired port/socket in the main window, select target/side, then Run.

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
