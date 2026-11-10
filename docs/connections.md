# Connections and probes

The **+** next to the last probe tab creates an independent workspace, up to eight.
Each workspace has its own connection settings, traffic, terminal, plot, recording,
plugins and sequence. Rename tabs for their location in your system. Hover a tab
to reveal its close button. Background probes keep acquiring data; closing an
active probe asks before disconnecting it.

## Choose a mode

| Mode | Purpose |
| --- | --- |
| TCP Client | Connect directly to a device or application |
| TCP Server | Accept connections from an application |
| TCP Proxy | Forward between clients and a target; inspect both directions |
| UDP | Bind a local endpoint and send datagrams to a remote endpoint |
| USB / Serial | Open a serial port or a pySerial URL |
| Serial Proxy | Bridge a physical port to a virtual serial endpoint |
| Serial ↔ TCP | Expose a serial port to a TCP client |
| Device Simulator | Run a recorded or edited device model |
| HID Monitor | Read-only USB HID capture |

A USB connector does not imply a serial interface. USB / Serial is for CDC ACM,
USB UART and other devices exposed by the OS as serial ports. HID uses its own
monitoring workflow. Probe is not a general USB protocol analyzer.

## A local TCP example

1. In Probe 1 select **TCP Server**, bind `127.0.0.1`, port `9001`, and **Listen**.
2. Create Probe 2. Choose **TCP Proxy**, listen on `127.0.0.1:9000`, and target
   `127.0.0.1:9001`. Start the proxy.
3. Create Probe 3 as a **TCP Client** connecting to `127.0.0.1:9000`.
4. Send text from Probe 3. See it arrive at Probe 1 and pass through Probe 2.
5. Reply from Probe 1. Inspect both directions in the proxy and use **Trace path…**
   to compare the same payload at different points.

For an external application, point that application to the proxy's listen address
instead of the original target. The proxy target remains the original server.
An already-open connection must reconnect through the proxy. This is explicit
forwarding, not passive interception of arbitrary TCP connections. Probe does not
decrypt TLS; use endpoints that expose the plaintext you intend to test.

## Serial setup

Select the physical port, baud rate, data bits, parity, stop bits and flow control
to match the device. For example: `COM34` or `/dev/ttyUSB0`, `115200`, 8 data bits,
no parity, 1 stop bit. Refresh ports after connecting hardware. Stable Linux names
under `/dev/serial/by-id/` avoid renumbering after reconnects.

Use `loop://` for a hardware-free echo check. It validates the software path, not
your USB adapter or actual UART timing. Only one application can normally own a
physical serial port at a time.

### Proxy on Linux

Choose **Serial Proxy**, set the physical port and select automatic PTY.
Probe creates a virtual endpoint and displays its path. Configure the other
application to open that path; Probe owns the real port. The application's line
settings must match the intended device behavior. A PTY does not emulate every
USB adapter control signal or electrical property.

### Proxy on Windows

Provide a virtual COM pair using a separately installed driver, for example
`COM20 ↔ COM21`. Creating/installing the driver generally requires an administrator;
Probe cannot bypass that requirement. Once the pair is available:

- Other application: open `COM20` with the device's serial settings.
- Probe: **Serial Proxy**, physical port `COM34`, virtual endpoint `COM21`.
- Both: use matching baud and line settings, then start the proxy and application.

Do not open `COM34` from the other application. The virtual partner name is a label
for the application's port; Probe opens the configured virtual endpoint. If no
virtual driver is available, direct serial use and Serial ↔ TCP remain alternatives
for applications that support them.

## Direction, clients and sending

For a proxy, TX is application/client → device/target and RX is the reverse.
For a direct connection, TX is Probe → peer and RX is peer → Probe. The client
selector and injection controls choose the intended proxy flow/side; check them
before sending. The simulator calls its device replies RX.

Start with loopback listen addresses unless another machine must connect. TCP is
reliable ordered bytes, UDP can lose/reorder datagrams, and serial has finite
baud-dependent capacity. UI history is bounded; use [Record](traffic.md) for a
long capture and inspect reported overflow or error events.
