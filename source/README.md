# Probe

A compact English-language Python desktop workbench for TCP, UDP and USB serial communications. Version **1.0.0** (Linux release).

The instrument-panel UI takes visual inspiration from ASUS PC Probe II: an angular silver chassis, blue panels, recessed green readouts and geometric headings. Michroma, Rajdhani and Share Tech Mono are bundled under the SIL Open Font License and loaded privately on Windows/Linux, without installing system fonts. They are open fonts, not ASUS's proprietary typography. Both dark and light appearances are available. The layout compresses on short displays; drag the divider to give the traffic table or byte inspector more room. Selecting Terminal opens up the work area and uses the terminal's direct keyboard controls; returning to another inspector tab restores the composer.

Probe uses Tkinter, pySerial and the small pure-Python pyte/wcwidth terminal libraries. There is no browser, Electron or Qt runtime. All I/O runs off the UI thread. Windows and Linux share the same source. Hardware drivers remain the operating system's responsibility. STM32 programming is intentionally excluded.

## Start from source

Python **3.10–3.13** with Tkinter is recommended.

```sh
python -m pip install -r requirements.txt
python run_probe.py
```

Linux: run `./start_linux.sh`. It chooses an installed Python with Tkinter, creates `.venv` and installs the pinned runtime dependencies on first launch. Set `PROBE_PYTHON` to select an interpreter. If Tkinter is missing on Debian/Ubuntu, install `python3-tk`; creating an environment may also need `python3-venv`.

Network modes still work without pySerial. If pyte is missing, the terminal tab displays an installation hint; raw communications modes remain usable. The source launcher requires Python; a frozen portable build includes Python and the runtime dependencies.

## Portable builds

**Build separately on each target OS.** PyInstaller does not cross-compile Windows EXEs on Linux.

* Linux: `chmod +x build_linux.sh && ./build_linux.sh`. Result: `dist/Probe-linux-x86_64.zip` on x86_64. Extract and run `./start-probe.sh`. No Python install is needed on the target PC.
* Add `--onefile` to either build script for a single executable. The default directory bundle starts faster and avoids extracting the runtime on every launch.

The spec includes fonts, font licenses, Tkinter and serial URL handlers. All paths
are relative to the spec. The builder runs `--self-test` against the actual frozen
executable from outside the source tree before creating the ZIP. The Linux branch
does not distribute Windows launchers or binaries.

Keep the whole portable folder together. Settings, profiles and commands are stored beside the app in `probe-data`; if the folder is read-only, Probe falls back to a per-user directory. No registry settings or background service are installed.

Linux binaries depend on compatible system libraries. Build on the oldest Linux distribution you intend to support. This Linux release was validated on Debian 13 with glibc 2.41; use the source launcher or rebuild for older systems. Build architecture follows your Python interpreter.

## Modes

| Mode | What it does |
| --- | --- |
| TCP Client | Connect to a device/server and exchange binary or text data. DNS names and IPv4/IPv6 stream endpoints are supported by Python networking. |
| TCP Server | Listen and accept up to 16 clients. Send to one client or broadcast. |
| TCP Proxy | Listen locally, connect each client to its own upstream, forward and capture both directions. Supports TCP half-close. |
| UDP | Bind a receive endpoint and send datagrams to a remote endpoint, including IPv4 broadcast. Replies are displayed with their actual sender. |
| USB / Serial | Open COM/tty devices with baud, parity, stop/data bits, flow control, DTR/RTS and break. |
| Serial Proxy | Bridge an app's virtual serial port to a physical COM/tty port and capture both directions. |
| Serial ↔ TCP | Let one TCP application communicate with a serial device through a raw byte bridge. |

Only one transport session is active per window. Run multiple Probe instances for multiple simultaneous device workspaces. The local listen address defaults to `127.0.0.1`; enter `0.0.0.0` if other computers should connect. Windows may show its normal firewall prompt for a listening application.

## TCP proxy example

Your real server is `192.168.1.50:9000`.

1. Select **TCP Proxy**.
2. Set Upstream host/port to `192.168.1.50` / `9000`.
3. Set Listen address/port to `127.0.0.1` / `9001`.
4. Start proxy; configure the other application to connect to `127.0.0.1:9001`.
5. TX means app → upstream. RX means upstream → app.

Choose **Device / upstream** or **App / downstream** to inject a test payload into the appropriate side. Forwarded bytes are unchanged. Probe does not decrypt TLS, so encrypted traffic appears as ciphertext. It is an explicit proxy, not a packet sniffer: the app must connect through it.

For a local check, start `python examples/echo_server.py`, point upstream at `127.0.0.1:9000`, then connect another Probe TCP Client window to `127.0.0.1:9001`.

## USB serial proxy example

USB support means devices exposed as **COM ports**, **USB CDC**, or USB-to-UART adapters. This is the serial workflow commonly used with SSCOM. Arbitrary USB HID/bulk devices require a device-specific protocol and are outside this release.

### Linux

1. Select **Serial Proxy**, physical port `/dev/ttyUSB0` or `/dev/ttyACM0`.
2. Set the device's actual serial parameters.
3. Leave the virtual port as **Auto PTY** and start the proxy.
4. Probe creates an app-side path such as `/dev/pts/4`, displays it and copies it to the clipboard.
5. Enter that path in the other application's serial settings.

The path lives only while the session runs and may change on reconnect. Your user needs access to the physical device; on Debian, that often means membership in `dialout`. A program that insists on enumerated USB devices rather than accepting a typed port path may not accept a PTY.

### Windows

Windows needs an **already installed virtual COM-pair driver**. Probe cannot create kernel COM ports with portable Python alone. Install a signed virtual serial pair driver compatible with your Windows version, and create, for example, `COM20 ↔ COM21`.

1. Probe opens physical `COM3` and its side of the pair, `COM20`.
2. Your other app opens the partner, `COM21`.
3. Probe forwards the bytes in both directions.

This part is not completely installation-free: creating the virtual COM pair may need administrator rights. Probe itself remains portable. A physical port already owned by another app cannot normally be opened simultaneously; the app must be routed to the virtual port instead.

The serial proxy forwards **data bytes**. Baud changes, break and modem line changes made by the app to the virtual port are not transparently mapped to the physical device. Configure those at Probe's physical side. DTR/RTS are OFF initially; some drivers can briefly assert lines while opening a port.

## Inspect and send

* View text and hex together, or text, hex or decimal separately.
* Select a row for decoded text, an offset/hex/ASCII dump, and a table of every byte with hexadecimal, decimal, binary and ASCII/control name.
* Send text, hex (`02 A4 00 FF 03`), escaped text (`HELLO\r\n\x03`) or decimal bytes (`2 164 0 255 3`).
* Encoding options include UTF-8, ASCII, Latin-1, Windows-1256, GBK and UTF-16 LE. Display decoding never changes the underlying bytes.
* Append CR, LF or CRLF. Tools adds prefix/suffix bytes and SUM8, XOR8, CRC16 Modbus, CRC16 CCITT or CRC32.
* Checksum covers **prefix + payload**. The final wire layout is prefix + payload + checksum + suffix + line ending. Modbus CRC16 is little-endian; CCITT is big-endian with initial FFFF; CRC32 is little-endian.
* Send files as original binary data in 4096-byte chunks, with cancellation. Composer transformations are not applied to files.
* Repeat at a configurable interval (minimum 50 ms).
* Keep up to 99 named commands; export/import them and run a sequence once in order or repeatedly with **Loop** enabled. Sample commands are in `examples/commands.json`.
* Automatic echo or a fixed composer reply is available in direct modes, once per receive chunk/datagram. These replies are not protocol-aware. Echo at both ends creates a loop.
* TCP Client and USB / Serial can reconnect automatically when disconnected. This is optional and off by default; manual Disconnect stops reconnection.
* Live plot accepts newline-separated ASCII numbers or comma/space-separated numeric channels (up to four). It is a numeric display, not a hardware oscilloscope.

## Framing and captures

TCP and serial provide **byte streams**, not message boundaries. A socket read may contain part of one message or several messages. Probe can group displayed rows by read chunks, a hex delimiter (included), a fixed byte count or an idle gap. Grouping changes the display only. Incomplete display frames are flushed on disconnect; buffering is capped at 64 KiB.

* **Record**: append lossless JSON Lines records containing timestamp, direction, peer and hex, directly at the transport before UI filtering or grouping. Record can be armed before connecting and stays armed for later connections.
* **Raw RX file**: append received bytes to a binary file. With multiple clients these are interleaved by arrival order; use JSONL to retain peer identity.
* **Export**: save the current retained history as JSONL, CSV or readable text. Includes rows hidden by filters. It is not a complete lifetime capture.
* **Save bytes**: save one selected row exactly as binary. **Copy hex** puts its exact hex on the clipboard.
* **Pause** pauses the display; forwarding, capture and the rolling history continue.

The display retains up to **2000 events / 8 MiB**. Old entries are evicted. The GUI queue is bounded to 1024 transport events; overload drops are counted visibly. Full recording happens before this queue. The inspector pages through the complete payload in 4 KiB pages using the arrow buttons; saving/copying uses its complete bytes. If storage fails, recording stops and an error is shown. Captures are flushed but not fsynced on every event, so power-loss durability is not guaranteed.

File/recording disk work runs on the transport thread. Very slow storage can reduce throughput. This first release is intended for terminal/debugging traffic; it does not promise line-rate packet capture or unbounded stress testing.

Search text normally; use `hex:02 A4` for a hexadecimal substring. Profiles save endpoints and composer settings. Appearance includes Probe II and Light themes and font scaling. Existing Midnight preferences migrate to Probe II. Settings may contain endpoint addresses and saved commands.

## Shortcuts

| Shortcut | Action |
| --- | --- |
| Ctrl + Enter | Send |
| Ctrl + L | Clear display |
| Ctrl + S | Export history |
| Ctrl + Plus / Minus | Resize data fonts |
| F1 | Quick guide |

## Test

```sh
python -m unittest discover -s tests -v
python run_probe.py --demo
```

`--demo` shows **synthetic sample traffic**, opens no endpoints and is suitable for previewing the UI. Transport tests use real loopback TCP/UDP and pySerial loopback. POSIX tests also bridge real PTY pairs. Windows USB hardware and Windows virtual-COM-driver integration still require testing on a Windows machine with the actual device/driver.

See `FEATURE_MATRIX.md` for implemented workflows and explicit reference-app gaps. No claim is made that this release duplicates every device-specific feature of every Hercules/SSCOM version.

## New in 0.2.0

### Live ANSI terminal

Select **Terminal** to see a live ANSI/VT-style screen rather than literal escape bytes. Colors (including truecolor), bold/underline, cursor movement, erase commands, carriage returns, scrollback and alternate-screen switching are supported. Text decoding is incremental across reads. **Pop out** opens a larger screen; use the arrow history buttons for scrollback. The screen is 100×24 cells, with horizontal scrolling in smaller panes.

Keyboard input is **off by default**. Enable **Keyboard**, click the screen and type directly to the device. Choose CR/LF/CRLF for Enter and DEL/BS for Backspace. Arrow/function keys and Ctrl-letter control bytes are supported. Ctrl+Shift+C/V copies/pastes; Local echo is optional. Keyboard sends original key bytes without composer prefixes, checksums or line endings. Device-status replies are sent only when Keyboard is enabled. The terminal tracks one peer at a time to avoid combining independent escape streams; select a client in the target selector to switch peers.

The raw traffic table and recordings still contain the original ANSI bytes. Pause freezes the display while capture continues. Unsupported terminal protocols are not claimed as implemented; this is not SSH, a local shell, sixel graphics or a complete implementation of every xterm extension. Oversized/incomplete CSI and control strings are bounded in the terminal view and never alter the raw capture.

### Capture import and replay

Open **Tools → Import capture**, or right-click a traffic row. While disconnected, load Probe JSONL or CSV into the history for inspection; importing sends no traffic. Import limits are 2000 events, 8 MiB decoded bytes and 24 MiB file size. Streaming full recordings can exceed these limits and may need splitting before import.

Connect and choose a target/side, then **Replay TX** (the replay dialog also offers RX). Replay sends exact recorded bytes, without composer transformations, at the original relative timing scaled by 0.1–10×. Negative/backward timing is clamped to preserve order. Stop replay cancels future sends; bytes already queued cannot be recalled. Disconnecting cancels replay. Repeat, sequence and replay runners stop one another when a new runner starts. Replay duration is bounded to 24 hours.

Double-click a traffic row to load its exact hex into the composer, with all transformations reset. Tools also resets byte counters without deleting history or recordings. Pending send data is bounded to 16 MiB to prevent repeat/replay from consuming unlimited memory.

### Hercules-style payload tokens

Choose **Hercules** input mode to use `$FF`, `#000`–`#255`, `<STX>`, `<CR>`, `<LF>` and other named controls. `##`, `$$` and `<<` produce literal characters. The parser validates tokens and never evaluates code. **LRC8** appends the two's-complement negative sum of prefix + payload. Sequence **Loop** repeats the entire saved command shelf in order until stopped.
