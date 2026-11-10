# Terminal and live plots

## Terminal

Open the **Terminal** tab in a probe workspace. Incoming bytes appear immediately;
ANSI cursor movement, colors and screen-clearing sequences are interpreted by pyte.
This is useful for boot logs, command shells and firmware diagnostics. It is a
terminal view of the same connection, not an SSH client or separate transport.

Enable **Send keyboard** only when you want keystrokes sent to the current peer.
Set the line-ending behavior to match your firmware. The composer remains useful
for binary commands or exact payloads. In proxy modes, check the selected target
and injection side first. HID Monitor is read-only.

Use the pop-out button to move the terminal into its own window. It is the same
terminal session; closing the window returns it to the workspace. **Reset** clears
the screen, not the device or a recording. Binary protocols may display unreadable
characters or control sequences; use Traffic/Analyze for byte-accurate inspection.

## Live plot

Open **Live plot**. Controls are below the chart to preserve plotting space.
Choose the **Value source** and **Peer**. Auto and Custom read incoming RX bytes;
plugin sources use their configured directions. Changing the display does not
send traffic or change the original bytes.

### Auto

Send LF-terminated numeric lines, for example:

```text
21.4,3.30,120

21.6,3.29,122

```

Here `\n` means an actual LF byte. Each column becomes a channel. Numeric parsing
waits for complete lines and keeps separate buffers for each peer. If there is no
line ending, the plot may have no complete sample to display.

### Custom

Select **Custom → Configure custom…**, then choose a message boundary and value:

| Format | Configuration example |
| --- | --- |
| JSON field | `data.temperature` or `/data/temperature` in a JSON message |
| Delimited column | Column 2, separator `,`, for `21.4,3.30,120` |
| Named value | Name `temp` for `temp=21.4 voltage=3.30` |
| Bytes | Fixed 8-byte frame, byte offset 2, Unsigned 16, Little endian |

Boundaries are LF lines, complete JSON messages, or fixed-size byte frames as
appropriate. Byte offsets start at zero; column numbers start at one. JSON paths
can be selected from the latest complete received JSON. Values must be finite
numbers; a Boolean, object or missing field is not a numeric sample.

Settings are saved with the probe/profile. **Clear plot** removes retained samples.
Plot history is bounded; it is a live diagnostic display, not a long-term time-series
recorder. Host receipt time is not a sample clock on the hardware. Record raw
traffic separately when you need later analysis.

### Plugin metrics

A plugin can return named numeric `values`, optionally with units. Choose
**Plugin: name / value** as the source. See [plugin authoring](plugins.md) for the
API and limits. A plugin can extract proprietary formats without changing the
built-in Auto/Custom parser.
