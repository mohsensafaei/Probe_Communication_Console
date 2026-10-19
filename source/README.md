# Probe

A compact English-language Python desktop workbench for TCP, UDP and USB serial communications. Version **1.2.0** (Windows release).

### Analyze traffic without sending anything

Select a traffic row and click **Analyze…**, or right-click it. The separate
analysis window has two tabs; the main connection/send workflow stays unchanged.

* **Protocol Inspector:** Auto recognizes UTF-8 JSON objects/arrays, optionally
  preceded by 1–12 ASCII body-length digits. Select a field to highlight its exact
  source bytes; **Copy field path** supplies its JSON pointer/TLV tag. Explicitly
  choose **TLV (1-byte)** for one-byte tag/length fields, or **BER-TLV** for
  definite-length BER (nested constructed tags included). Raw bytes are never
  labeled as a guessed protocol. Incomplete data remains visible in the hex view.
* **Custom fields…:** Add named fields with 0-based offsets and lengths (0 reads
  the rest), text, signed/unsigned LE/BE integers or 4/8-byte floats. Length fields
  validate a byte-range size; checksum fields validate SUM/XOR/LRC/CRC bytes over
  an explicit range. End offsets are excluded. Blank ranges default to bytes after
  a length field, or bytes preceding a checksum field. Profiles save/load JSON.
  Try `examples/lab-protocol.json` with hex `30 30 30 30 30 33 41 42 43 06 13`.
* **Capture Diff:** A defaults to the previous retained message from the same
  direction/peer; B is the selected message. **Choose A/B…** can load history,
  JSONL/CSV captures or binary files. Filter one peer/direction and select chunks
  to combine in recorded order. This compares byte streams, not TCP read chunk
  boundaries or capture timestamps. Alignment is heuristic; additions/removals
  and replacements are explicit with original offsets.
* **Ignore fields…:** Select JSON value fields (paths must exist on both sides),
  or enter byte ranges such as `0:6 12:16`. Different JSON value lengths remain
  aligned. Ranges must not overlap; changing length prefixes/checksums may need
  separate ignores. Originals are unchanged. **Save comparison…** includes both
  complete inputs, ignore rules and every difference range, including ignored
  bytes. Protocol analysis supports 1 MiB; comparison 256 KiB per input.

### Use reply values in a sequence

The usual Choose messages → Set timing → Run workflow remains available.
For a dynamic conversation, edit the request and click **Response & next step…**:

1. In **Save reply values**, choose JSON, TLV, BER-TLV or fixed reply bytes.
   **Pick field from captured reply…** lets you select captured chunks and then
   the field. Name the variable, click **Add / update field**, then **Save rules**
   and **Save message**. Manual JSON paths accept `data.sessionId` or the exact
   JSON pointer `/data/sessionId`. Binary fields can stay Hex bytes or decode as
   UTF-8 text / unsigned LE/BE integers. BER nested tags use `6F/84` notation.
2. Edit the next request and use **Insert variable…**. `${sid}` inserts literal
   text (raw bytes as hex in Hex mode). `${sid:json}` inserts a safely escaped
   JSON value; use it without surrounding quotes: `{"sessionId":${sid:json}}`.
   `${blob:hex}` inserts byte hex. Undefined variables stop before sending; no
   placeholder text is sent. **Outgoing frame…** in the rules dialog can add an
   ASCII length prefix and prefix/checksum/suffix after variable substitution.
3. In **Choose next step**, optionally compare a variable using equals, not
   equals, contains, greater than or less than. Choose Next message, Go to
   message, Finish successfully or Fail test for true/false/timeout outcomes.
   Goto targets retain stable IDs when reordered/renamed. Referenced messages
   cannot be removed until their branch rules are changed. Stop cancels waits.
4. **Variables…** on the sequence page defines initial Text/Hex/JSON values and
   displays the latest received values. Initial values reset each cycle; each
   extraction clears its previous value before waiting, preventing stale reuse
   after a timeout. Saved fields publish atomically after all requested fields
   arrive. Checks wait across receive chunks and use the sequence/message timeout.

Reply rules do not execute Python or expressions. A missing field in complete
JSON is an error; incomplete fields wait until timeout. Specific expected hex
bytes still apply. Routes run after each repeated send; a timeout route skips
remaining repeats. Go-to loops allow at most 10000 message visits per cycle.
Replies/dynamically rendered messages are bounded to 1 MiB (legacy static
sequences retain their 8 MiB total), extraction rules to 16 per message,
initial variables to 64 and runtime variables to 256 / 8 MiB. Export uses version 3 when
templates/rules/initial values are present, so older releases reject such files.
Legacy shelves and version 1/2 sequences still load.

For a complete hardware-free example, load `examples/variable-device.json` in
one Probe simulator, connect another Probe as TCP Client, then load
`examples/variable-sequence.json`. SESSION returns a session ID and response
code; the condition selects a STATUS request containing that ID. These are
synthetic read-only lab messages, not a vendor POS protocol.

The instrument-panel UI takes visual inspiration from ASUS PC Probe II: an angular silver chassis, blue panels, recessed green readouts and geometric headings. Michroma, Rajdhani and Share Tech Mono are bundled under the SIL Open Font License and loaded privately on Windows/Linux, without installing system fonts. They are open fonts, not ASUS's proprietary typography. The Appearance button has been replaced by Test lab; data fonts can be resized with Ctrl +/-. The layout compresses on short displays; drag the divider to give the traffic table or byte inspector more room. Selecting Terminal opens up the work area and uses the terminal's direct keyboard controls; returning to another inspector tab restores the composer.

Probe uses Tkinter, pySerial and the small pure-Python pyte/wcwidth terminal libraries. There is no browser, Electron or Qt runtime. All I/O runs off the UI thread. Windows and Linux share the same source. Hardware drivers remain the operating system's responsibility. STM32 programming is intentionally excluded.

## Start from source

Python **3.10–3.13** with Tkinter is recommended.

```sh
python -m pip install -r requirements.txt
python run_probe.py
```

Windows: run `start_windows.bat`. It creates `.windows-venv`, installs pinned
dependencies on first use and accepts `--self-test`. Set `PROBE_PYTHON` to an
installed Python executable path when needed.

Linux: run `./start_linux.sh`. It chooses an installed Python with Tkinter, creates `.venv` and installs the pinned runtime dependencies on first launch. Set `PROBE_PYTHON` to select an interpreter. If Tkinter is missing on Debian/Ubuntu, install `python3-tk`; creating an environment may also need `python3-venv`.

Network modes still work without pySerial. If pyte is missing, the terminal tab displays an installation hint; raw communications modes remain usable. The source launcher requires Python; a frozen portable build includes Python and the runtime dependencies.

## Portable builds

**Build separately on each target OS.** PyInstaller does not cross-compile Windows EXEs on Linux.

* Windows: run `build_windows.bat`. Extract `dist/Probe-windows-x64.zip` and open `Probe/Probe.exe`. No Python install is needed on the target PC. Use `build_windows.bat --onefile` for the optional single executable.
* Linux: `chmod +x build_linux.sh && ./build_linux.sh`. Result: `dist/Probe-linux-x86_64.zip` on x86_64. Extract and run `./start-probe.sh`. No Python install is needed on the target PC.
* Add `--onefile` to either build script for a single executable. The default directory bundle starts faster and avoids extracting the runtime on every launch.

The spec includes fonts, font licenses, Tkinter and serial URL handlers. All paths
are relative to the spec. The builder runs `--self-test` against the actual frozen
executable from outside the source tree before creating the ZIP. The Windows branch includes `start_windows.bat` and `build_windows.bat`;
see the repository README for native Windows commands and COM-pair setup.

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
| Device Simulator | Replay recorded device replies on TCP or a virtual serial endpoint without the original device. |

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
2. Set Application-side partner port to `COM21`; your other app opens that port.
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
* Build up to 1000 named test steps in Test lab with independent millisecond delays, repeats, optional expected reply bytes and timeouts. Export/import complete sequences or legacy command shelves. Cycles 0 repeats until stopped. Samples are in `examples/test-sequence.json`.
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

Search text normally; use `hex:02 A4` for a hexadecimal substring. Profiles save endpoints and composer settings. Test lab opens device modeling and timed sequence editing. Ctrl +/- changes data font size. Existing Midnight preferences migrate to Probe II. Settings may contain endpoint addresses and saved commands.

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

Choose **Hercules** input mode to use `$FF`, `#000`–`#255`, `<STX>`, `<CR>`, `<LF>` and other named controls. `##`, `$$` and `<<` produce literal characters. The parser validates tokens and never evaluates code. **LRC8** appends the two's-complement negative sum of prefix + payload. Test lab **Cycles = 0** repeats the sequence until stopped.

## Device simulator and test sequences (1.1)

**Device Simulator** is a separate transport mode. It does not open the original
physical device; Windows COM simulation opens only its virtual-pair endpoint.
Use **Test lab → Device simulator** to load a two-direction capture or a saved
model. Choose a peer (and RX request direction for recordings where the application
was the receiving server). Consecutive request chunks are joined until the first
reply; reply chunks retain their timing relative to the last request and each
other. The preview shows expected requests, response bytes and chunk delays.

Expose a **TCP socket**, **Virtual COM pair** on Windows, or **Virtual serial
(PTY)** on Linux, then Start simulator. For Windows, install a virtual pair first,
enter Probe-side COM20 and its application-side partner COM21; the other
application opens COM21. For TCP use the displayed address, or on Linux the
generated `/dev/pts/N` path. Requests are
matched across split/coalesced stream reads. Each TCP client gets its own model
state. Conversation order preserves repeated requests with stateful replies;
Repeat conversation wraps after the final exchange. Match requests accepts
independent commands in any order and rejects conflicting replies/prefixes.
Unmatched bytes are ignored and reported. Reset matching cancels pending delayed
replies and resets conversations. Stop closes endpoints and pending tasks.

Models use exact bytes. A capture alone does not infer variable transaction IDs,
checksums over changed fields, encrypted sessions or a complete hardware state
machine. Startup RX chatter is excluded and reported. Linux PTYs represent serial
bytes, not a USB device identity or modem-line emulation. Model size is bounded to
8 MiB and requests to 64 KiB. Save model / Load model makes emulation reusable.

**Sequences** opens a three-part page: **Choose messages → Set timing → Send
messages**. Connect in the main window first. **Choose captured messages…**
opens a selectable RX/TX list, with RX initially selected. Pick traffic history,
an imported capture or **Load capture…**, optionally filter one peer, and add
the selected records. Their bytes and order are preserved. Loading a capture
here does not replace the main traffic view or disconnect an active session.
RX means received by Probe and TX means sent by Probe in the original recording;
both can be sent again. Selecting a direction never changes the destination.
The visible **Send to** line identifies the physical port, TCP endpoint or
downstream application selected in the main window. For proxying, choose the
correct target/injection side there before running.

For a quick test, set **Interval between messages** to **100 ms** and choose
**Run once**. The shared interval immediately applies to every table row, the
next Run and Save, without Update selected. **Repeat a set number** shows a run
count; **Repeat until stopped** provides continuous operation without a magic
number. **Add composer** preserves its complete encoded bytes including prefix,
checksum and line ending. **New message…** and **Edit message…** use a separate
Save/Cancel editor; the payload editor is absent from the main sequence page.

To advance only when the destination replies, choose **Set timing → Send next
message → After a reply**. Set **Reply timeout** (default 2000 ms), then Run.
The first message sends immediately. Each following message waits for incoming
data after the previous send, without an interval delay. The last message also
waits for its reply before the run completes. A timeout stops the sequence;
**Stop** cancels the wait immediately. Switching back to **After interval**
restores shared/individual timing. Run and Save use the mode shown here.

By default, the first nonempty receive chunk from the selected destination
counts as a reply. TCP/serial chunks can be partial protocol messages, and
unsolicited data from that same destination also counts. To require a particular
response, open **Edit message… → Advanced → Expected reply** and enter its hex
bytes; matching spans receive chunks. Display framing does not control reply
matching. In proxy mode the selected injection side determines which direction
contains the destination's reply. Example: `examples/reply-sequence.json`.
Reply-gated exports use sequence format version 2 so older Probe versions reject
them instead of ignoring the wait. Legacy shelves and version 1 files still load.

Advanced message options include format/encoding, line ending, repeats,
expected reply substring (hex, optional) and reply timeout. **Advanced: use
individual message delays** enables per-message timing (0–3600000 ms). Delays
start after sending, or after the expected reply when a reply check is enabled;
they are not start-to-start periods when waiting for replies. A missing reply
stops the test and names the step. In interval mode, blank expected reply means
no reply wait unless **Wait for any reply for this message** is enabled. Reply
mode always waits, using the shared timeout; expected bytes narrow that check.
Progress reports cycle, step, sends and checked replies. Expected replies use the
selected client; select one client when several are connected. Run/Repeat/Replay
stop one another. Disconnect cancels the sequence. Already written bytes cannot
be recalled. Small millisecond delays are best effort and do not promise hard
real-time scheduling or prove that a device cannot fail under other workloads.

Load/Save stores steps and cycles in the existing JSON format. Files with mixed
individual delays automatically keep individual timing, along with reply checks
and repetitions. The capture picker uses the shared interval by default;
**Keep recorded intervals (advanced)** explicitly preserves gaps between the
selected records and enables individual timing. Original command-shelf JSON files
can still be loaded; files without delays use the 100 ms quick-test default.
Settings retain timing/repeat choices separately from the composer's Repeat
interval. Editing is locked during a run; Stop cancels future sends and waits.
Synthetic runnable examples are `examples/device-model.json`
and `examples/test-sequence.json`; they do not claim a vendor-specific POS protocol.
