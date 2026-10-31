# HID Monitor — Probe 1.3.0

HID Monitor observes **USB HID reports** while the normal OS driver and application
continue to use the device. It is not HID Terminal and never sends Output/Feature
reports. Bluetooth, I²C and SPI HID are outside this capture mode.

## Start a capture

1. Choose **HID Monitor** in Connections.
2. On Windows, if USBPcap is not installed, click **Install USBPcap (offline)…**.
   The original signed installer is already included in the package. Complete its
   interactive setup and restart Windows if required. Probe never downloads it,
   silently accepts licenses, replaces a HID driver or restarts the computer.
3. Click **Refresh devices**, then choose your device. Linux lists USB devices
   with HID interfaces. USBPcap discovery on Windows may list composite and other
   USB devices too; only HID interfaces/reports are displayed during capture.
4. Click **Start capture**. Approve the OS permission prompt when needed.
5. Use the device normally. RX means device → computer; TX means computer → device.
6. Double-click a Traffic row. **HID Report** shows decoded fields; the existing
   Hex + ASCII / Every Byte pages retain the exact report bytes.
7. Click **Stop capture**. The helper closes capture and the OS driver keeps working.

No elevation is requested when Probe starts, when ordinary TCP/serial transports
are used, or simply when the HID mode is selected. In Windows a discovery retry
may itself request UAC, but only after the user clicks Refresh in HID Monitor.
Cancelling permission stops that operation and leaves the normal app usable.

## Windows: offline prerequisite and permissions

`drivers/windows/USBPcapSetup-1.5.4.0.exe` is the unmodified official x86/x64
installer. Its SHA-256 is checked before launch and during packaging. The
corresponding upstream source ZIP, GPLv2/BSD license texts, version and download
provenance are included alongside it. Portable folder and single-file builds
contain these resources; the ZIP also exposes them in `drivers/windows`.

USBPcap needs administrator permission for live capture. **Only the capture
helper** (or the explicitly selected driver installer) is elevated; Probe's main
GUI retains its original permissions. Capture is restricted to one selected USB
root/address and does not auto-include newly attached devices. The driver normally
needs a Windows restart after installation. Do not uninstall/reinstall it merely
because a device was unplugged; refresh the device selection instead.

HIDAPI 0.15.0 is bundled on Windows for descriptor metadata queries. Windows
reconstructs report descriptors from its preparsed HID data; these are not claimed
to be verbatim descriptors fetched from the wire. Queries never send HID reports.
If multiple identical physical devices or conflicting top-level collections cannot
be distinguished reliably, Probe keeps the raw report without guessing a layout.
A failed metadata query also falls back to raw bytes.

## Linux: offline system facility

Linux uses the running kernel's **usbmon binary API** and sysfs device/report
descriptors. No libpcap, Wireshark, lsusb, downloaded installer, or new Python USB
package is needed. A usbmon kernel module cannot be shared as a portable binary
across different kernel versions. It must already exist in the host's kernel or
installed module tree; Probe does not download kernel packages.

If your user already has read access to `/dev/usbmonN`, capture runs without
privilege elevation. Otherwise Probe starts only its capture helper through
`pkexec`. On desktops without pkexec, an existing x-terminal-emulator/xterm plus
sudo is used for the password prompt. No persistent root service, udev rule or
permission change is installed. The helper loads `usbmon` with the host's existing
modprobe if necessary. If the kernel lacks usbmon or the desktop has no supported
authentication mechanism, Probe explains the missing prerequisite instead of
trying to download it. An administrator can also grant usbmon access externally.

## What is captured and decoded

- Interrupt Input and Output reports, plus class GET_REPORT/SET_REPORT Input,
  Output and Feature transfers on HID interfaces.
- USB submit/complete pairs are reconstructed into a single report. IN payloads
  come from completion; OUT payloads come from submission after a successful
  completion. This avoids duplicating TX/RX rows for the same report.
- Report IDs, little-endian bit fields, signed logical values, padding, variable
  fields and arrays are supported. Common mouse/keyboard/button/LED usages have
  names; unknown/vendor usages keep numeric page/usage IDs.
- Linux reads descriptors from sysfs. On Windows, injected configuration/device
  descriptors identify HID interfaces and HIDAPI provides report metadata where
  available. Successfully captured GET_DESCRIPTOR(report) responses can also
  supply the layout.
- If a descriptor is unavailable, **raw capture still works**. Use Analyze →
  HID Report → **Load report descriptor…** with a `.bin` or whitespace-separated
  `.hex` file. This changes only the current inspection, not the capture or device.
  Example layouts are in `examples/hid-mouse-report.hex` and
  `examples/hid-keyboard-report.hex`; use your actual device's descriptor.
- Text search includes decoded HID field names/values. Hex search uses original
  report bytes. Record and JSONL Export retain HID metadata, and JSONL import
  restores/revalidates it. CSV/readable exports remain payload-oriented views.
- The composer is hidden in HID Monitor. Engine-level Send, replay transmissions
  and Sequence are rejected even if invoked from another window.

This is OS-level transfer capture, not an electrical USB analyzer. Captured report
bytes are the payload, not USB tokens/handshakes. Device unplug/replug can change
its USB address; stop, refresh and select again. Failed USB transactions do not
become successful report rows. Alternate HID settings/configuration changes,
boot-protocol switches, unusual long HID items and complex collection layouts may
require an externally supplied descriptor or raw-byte analysis. Descriptor limits
and unsupported/truncated layouts are explicit; vendor protocol meanings still
require device documentation.

## Limits and validation

The helper uses a random authenticated loopback channel with bounded framed
messages. It accepts only heartbeat/stop on the control channel; arbitrary
commands, file paths and output-file writes are not accepted. Closing Probe or
losing its heartbeat revokes capture. The GUI never opens a privileged capture
handle. Normal permission cancellation is recoverable.

USBPcap uses an 8 MiB kernel buffer; usbmon kernel drop reports are surfaced when
available. Probe's rolling UI/history and asynchronous recording keep their normal
limits. No loss-free or physical timing guarantee is implied; capture truncation
is marked, and unsupported descriptors retain their raw reports.

Automated coverage includes USBPcap and usbmon binary fixtures, fragmented pcap,
mouse/keyboard/report-ID/signed/array/Feature decoding, OUT reconstruction,
composite endpoint filtering, metadata import, permission cancellation, and an
actual unelevated helper handshake. Frozen self-tests verify the helper entry
point without starting privileged capture. Native Windows/Linux GUI and package
checks do not substitute for a physical USB device test. No physical USB/HID
hardware was attached in the development/CI environment; validate live capture on
the target workstation before relying on it in the lab.
