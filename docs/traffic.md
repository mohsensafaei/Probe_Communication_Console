# Traffic, analysis and captures

## Select and search

Traffic shows direction, timestamp, peer and the current data view. Single-click
selects a row; double-click opens **Analyze** for that message. Hold Ctrl to select
several rows. Right-click offers **Capture Diff**, **Export selected…** and the
cross-probe trace workflow. Selected export writes only those messages.

Choose **Text** or **Hex bytes**, enter a query, then press **Search** or Enter.
Typing alone does not hide rows. Changing search type clears the applied search;
blank searches leave traffic visible. Hex searches are byte-aligned, for example
`02 10 FF`, not partial nibbles. Invalid input preserves the previous valid filter.
**Reset** clears the search. The RX/TX/All selector still applies independently.

**Pause** pauses the display, not the connection or raw recording. **Clear** clears
the retained view and replay source. It does not erase an existing recording file.
Retention is bounded (normally 2,000 rows / 8 MiB); old messages leave the display.

## Bytes, text and boundaries

Use Analyze for **Decoded text**, **Hex + ASCII**, individual bytes, protocol
inspection, plugin results and Capture Diff. Decoding never changes the original
bytes. Encoding errors may be replaced for display; hex is the authoritative byte view.

TCP and serial reads may split one protocol message or combine several. Traffic
framing controls how those chunks are displayed and analyzed:

| Boundary | Use |
| --- | --- |
| Chunks | Show each captured read/write chunk |
| Fixed length | Collect a known number of bytes |
| Delimiter | Split on configured delimiter bytes |
| Idle gap | End a frame after an inactivity interval |

Choose framing before interpreting message fields. Partial frames are labeled.
Raw recording retains transport events independently of the framed display.
Plugin transform framing is separate; see [plugins](plugins.md).

## Capture Diff and protocol fields

Select a reference message and open Capture Diff, then choose the comparison
message. The initial direction follows the reference; you can change it. Reopening
the same analysis preserves its comparison choices. Differences show byte offsets,
hex and decoded text. **Ignore variable fields** masks the selected
JSON value fields or byte ranges for comparison; it does not remove bytes from traffic or exports.
Use it for timestamps, counters and transaction IDs that change on every message.

The protocol inspector offers **Auto** and **Raw Bytes**. Auto attempts supported
structures such as JSON/TLV and configured protocol fields. A profile can describe
fixed byte fields, lengths and checksums; select a field to inspect its range.
A successful parse is not proof that a device accepted the message.

## Record, export, import and replay

| Operation | Result |
| --- | --- |
| Record | Append raw events to JSONL in the background, including status and provenance |
| Export | Save retained/selected messages as JSONL, CSV or text |
| Import capture | Load supported JSONL/CSV into retained history without sending |
| Replay TX | Send captured TX bytes through the current connection |

Export asks for **Hex**, **Decoded text**, or both. Keep Hex for a byte-exact capture
that you plan to import, replay or use in a simulator; decoded text alone cannot
represent arbitrary bytes reliably. JSONL is preferred for plugin metadata and
original/wire byte provenance. See [file formats](formats.md).

Replay is an explicit sending operation. Check the destination first. Enabled
message-changing plugins also apply to replay; disable them for exact-byte replay.
Capture import itself does not trigger live plugin transforms or send data.

Rows changed by plugins are marked **[Modified]**, and failed sends **[Blocked]**.
Analyze's plugin preview compares input with actual output. Raw recording includes
`original_hex` when present, wire `hex`, processing metadata and plugin names.
Plugins do not rewrite the stored original input. Framed rows retain the original
chunks that contributed to them.

## Follow a message across probes

Open **Trace path…** or right-click a message → **Follow across probes…**. Choose
a target probe and **Find matches**. Exact byte matching handles split and combined
stream chunks. Optionally enter a scalar JSON identifier, such as `sessionId`, to
find related payloads whose content changed. Repeated occurrences require a choice;
Probe does not assume which is causal. **Compare selected…** opens Capture Diff.

Trace uses retained snapshots. **Refresh traffic** takes another snapshot. Recorded
intervals describe host observation times, not wire propagation latency. This
workflow never sends traffic and does not automatically diagnose the faulty component.
