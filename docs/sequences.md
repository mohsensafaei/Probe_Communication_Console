# Test sequences

Use **Sequences** beside the composer, or open it from **Test lab**. Sequences send
repeatable messages through the current probe connection. They do not create a
second connection. Check destination, client and proxy injection side before running.

## Send messages every 100 ms

1. Connect to your device using TCP Client or USB / Serial.
2. Open **Sequences**. Add messages from the composer, create a message, load a
   sequence file, or choose captured messages.
3. Under **Send next message**, select **After interval**.
4. Set **Interval between messages** to `100` ms. Leave individual intervals off
   unless each message needs a different interval.
5. Choose a run count or continuous repeat, then **Run sequence**. **Stop** cancels it.

The interval is a requested start-to-start period. The runner uses monotonic,
absolute deadlines so processing time does not accumulate into drift. If it misses
a slot, it preserves messages and reports missed timing rather than pretending
the send was on time. OS scheduling, socket/serial buffering and plugins add jitter.
This is not a nanosecond or hard real-time generator.

## Send the next message after a reply

Select **After a reply** and set **Reply timeout**. Each message waits for a received
reply before the next send. No reply stops the sequence. A simple reply gate
accepts incoming bytes, not necessarily a complete application-level response.
For an exact check, edit the message and set expected reply bytes; for structured
responses use **Response & next step…**. Choose a timeout suitable for the device.

Advanced per-message options include line endings, repeat counts, individual delay,
expected reply and response routing. In interval mode a configured reply check
runs before the delay; reply-driven mode uses the sequence timeout and no interval.

## Build from a capture

Choose captured messages and select **Original direction**: RX is the default,
TX is also available. The choice means where the saved bytes originally came from;
all chosen payloads become outgoing sends to the current destination. It does not
reverse the connection or select a different device.

Choose one recorded peer and select the rows. The optional **Keep recorded intervals**
uses their original gaps. A capture row may only be a stream chunk; inspect framing
before replaying it as a protocol request. For a proxy capture, TX usually contains
application requests and RX device replies. Choose whichever side you are reproducing.

## Dynamic data and response routing

**Variables…** defines initial values. Payload templates support `${name}` for text,
`${name:json}` for a JSON value, and `${name:hex}` for binary bytes. The message editor
can also rebuild configured length prefixes and checksums after substitution.

**Response & next step…** extracts a named value from JSON, TLV, text or byte ranges.
Use a condition to continue, go to another step, succeed, fail or handle a timeout.
Variables are reset to their initial values for each cycle. Branches are bounded;
an accidental infinite route fails with a clear error. Do not use arbitrary Python
expressions in sequence files; user Python code belongs in [plugins](plugins.md).

## Try it locally

Run `examples/device-model.json` in the [simulator](simulator.md), connect another
probe to its TCP endpoint, and load `examples/test-sequence.json`. Also see
`reply-sequence.json`, `variable-device.json` and `variable-sequence.json` in
[examples](../examples). Export sequences as JSON for version control. File formats
are described in [formats](formats.md); use the UI to validate edited files.

For physical serial at 115200 baud, 8N1, each byte needs ten bit times. A 32-byte
frame alone takes about 2.78 ms on the wire. A 1 ms request period cannot make the
UART transmit that frame in 1 ms; buffering is not faster physical transmission.
