# Reference feature coverage

This is a workflow comparison, not a claim of byte-for-byte compatibility with all releases of either application. The requested SSCOM version was not specified. Hercules describes Serial, TCP Client/Server, UDP and HW-group configuration; SSCOM releases vary and some include terminal emulation, waveform display or STM32 ISP tools.

| Feature | Probe 1.1.0 Linux | Notes |
| --- | --- | --- |
| Recorded device simulator | Implemented | TCP / Linux PTY; exact request matching, stateful ordered replies, response timing, reset and model import/export. |
| TCP client | Implemented | Binary/text, DNS and encoding options. |
| TCP server | Implemented | Up to 16 clients, per-peer send or broadcast. |
| UDP send/receive | Implemented | IPv4 bind, broadcast and sender identity. |
| USB serial / COM terminal | Implemented | pySerial; USB CDC/UART devices, not arbitrary USB protocols. |
| Custom baud / data / stop / parity | Implemented | Actual capabilities depend on driver/device. |
| RTS/CTS, XON/XOFF, DSR/DTR flow | Implemented | Platform/device support varies. |
| Manual DTR/RTS, break | Implemented | Applied to physical serial port. |
| CTS/DSR/DCD/RI status | Implemented | Polled in direct serial and serial proxy modes. |
| Text/hex transmit and display | Implemented | Additional escaped text and decimal input. |
| Timestamps, byte counters, clear | Implemented | Counters are per transport session. |
| Save received data / readable logs | Implemented | Raw RX, streaming JSONL, CSV/text export. |
| File transmit | Implemented | Binary, chunked, cancellable. |
| Timed transmit | Implemented | Minimum interval 50 ms. |
| Multiple predefined sends | Implemented | 1000 steps; independent millisecond timing, repeats, reply checks, JSON import/export. |
| Header + data + checksum + trailer | Implemented | Explicit checksum coverage; seven checksum choices including None. |
| Escape sequences | Implemented | Escaped text and Hercules-style #decimal/$hex/named controls. |
| Reconnect on disconnect/unplug | Implemented | Optional TCP Client / direct Serial reconnect. Device must return at same configured path. |
| Data font sizing | Implemented | Ctrl +/- shortcuts; Appearance button removed in favor of Test lab. |
| Numeric waveform display | Implemented | Up to four ASCII numeric/CSV channels. No analog acquisition. |
| Serial-over-network RFC2217 client | Implemented | Enter `rfc2217://host:port` in USB / Serial port field. Via pySerial. |
| TCP proxy | Implemented | Separate upstream per client, exact bytes, TCP half-close, injection. |
| Linux serial proxy | Implemented | Automatic raw PTY; typed paths supported by the other app. |
| Windows serial proxy | Implemented with external prerequisite | Requires an installed virtual COM pair. Driver install itself is not portable. |
| Raw Serial ↔ TCP bridge | Implemented | One TCP client, physical serial settings managed in Probe. |
| Every-byte inspector | Implemented | Offset, hex, decimal, binary, ASCII/control. |
| Display framing | Implemented | Chunks, delimiter, fixed length, idle gap. Does not alter the wire. |
| TCP Test Mode / repeated traffic | General workflow covered | Echo, automatic replies and repeat; not a dedicated recreation of Hercules's test tab. |
| HW-group proprietary UDP Setup / IP-MASK-GW programming | Not implemented | Vendor-specific discovery/configuration protocol is not duplicated. Generic UDP is available. |
| ANSI/VT-style screen terminal | Implemented | Live colors, cursor, erase, alternate screen, history and direct keyboard; not every xterm extension. |
| STM32 ISP bootloader flashing | Excluded by request | Not part of Probe's scope. |
| Windows device manager / calculator shortcuts | Not implemented | OS-specific convenience launchers are not included. |
| Arbitrary USB HID/bulk interception | Not implemented | Requires per-device protocol/backend, often driver changes. |
| Passive capture of another app's already-owned COM port | Not implemented | Route the app through the explicit serial proxy instead. |
| TLS plaintext interception | Not implemented | Encrypted TCP bytes are forwarded and shown as ciphertext. |

## Reference sources

* HW group, Hercules SETUP utility: https://www.hw-group.com/software/hercules-setup-utility
* HW group, UDP Config in your applications: https://www.hw-group.com/support/udp-config-in-your-applications
* SSCOM publisher's historical download site: https://www.daxia.com/sscom/ (not retrievable during this build; exact-version comparison needs the installed version/help).
* pySerial API: https://pyserial.readthedocs.io/en/latest/pyserial_api.html
* pySerial URL handlers / RFC2217: https://pyserial.readthedocs.io/en/latest/url_handlers.html
* Python PTY availability: https://docs.python.org/3/library/pty.html

Known gaps are listed explicitly because "all features" cannot honestly be claimed for this release. Core send/receive/debugging workflows have working implementations and integration tests.

Version 0.2 adds capture import/replay, exact-payload reuse, LRC8, looping command sequences, a bounded live screen and a terminal pop-out window. HW-group UDP Setup and TEA/I/O extensions still need verified protocol/SDK information and actual-device validation. Their implementation is not inferred from generic UDP support.
