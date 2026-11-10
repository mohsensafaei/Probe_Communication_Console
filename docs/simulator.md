# Device simulator

The simulator lets another application talk to a stand-in for a controller, sensor,
payment terminal or other device. It can reproduce recorded conversations or use
explicit request/reply rules. It does not emulate a CPU, operating system or electrical bus.

## First local simulation

1. Open **Test lab → Device simulator** (also available as a connection mode).
2. Load [device-model.json](../examples/device-model.json).
3. Choose **TCP socket**, bind to `127.0.0.1`, select an unused port and start.
4. Connect another probe/application to the displayed endpoint.
5. Send `PING` followed by CR LF. The model replies `PONG` followed by CR LF.
6. Use `examples/test-sequence.json` from a connected probe for a complete test.

The real hardware is never opened by a simulation. Windows virtual COM simulation
requires an existing virtual COM pair; Linux can create an automatic PTY. Configure
the application to open the other endpoint. See [connections](connections.md).

## Create a model from a real device

Record a successful TX/RX exchange with the device. Stop the live connection, open
the simulator and load the JSONL/CSV capture or retained traffic. Select one peer
and build the model. Leading RX chatter is excluded because it has no triggering
request. Review the resulting rules before starting.

**Conversation order** preserves the sequence, including different replies for
identical requests at different steps. **Match requests** accepts independent rules
in any order; ambiguous matches are rejected. Unknown requests are reported and
ignored. Reset matching to replay the conversation from its initial state.

Reply timing can be scaled. Repeated conversations can restart after completion.
Save a model to share it; captures/models should contain synthetic or sanitized data.

## Edit requests and replies

Double-click a rule. **Request & reply** can match exact bytes or field conditions.
All conditions must match. Supported field sources include JSON paths, TLV tags,
text and byte ranges. Replies are static bytes with optional delays; editing a
field match does not automatically synthesize a new cryptographic response.

Configure **Message boundary** for the protocol: exact stream, delimiter, fixed
length, length prefix or JSON. Framing can validate lengths and supported checksums.
Field conditions operate on the payload, excluding configured framing/checksum
bytes. Byte offsets start at zero. Exact stream retains the legacy recorded-byte
matching behavior across split reads.

## Test recovery with faults

The rule's **Fault injection** tab provides repeatable disturbances such as missing,
delayed, truncated, corrupted, split or duplicated replies and connection closure
where supported. Configure the trigger count for that rule. Counts are separate
for each connected application; reset matching clears them. Timing multipliers
also scale fault delays and gaps. Read the per-fault hint before applying it.

Try [simulator-json-faults.json](../examples/simulator-json-faults.json) and
[simulator-binary-crc.json](../examples/simulator-binary-crc.json). Verify normal
behavior first, then enable one fault so failures remain easy to interpret.

Dynamic handshakes, changing IDs, signatures and complex device state need an
explicit model or a protocol-specific tool. The simulator's purpose is repeatable
application testing, not automatic inference of undocumented protocol semantics.
