# Files and interoperability

JSON files use UTF-8. Hex payloads preserve bytes; displayed text is an interpretation
using the chosen encoding. Keep sanitized example files small and deterministic.
Loaders validate inputs and do not execute capture/model contents. Python plugins
are different: they are trusted executable code.

## Raw capture / JSONL export

One JSON object per line. A minimal byte-exact capture is:

```json
{"kind":"data","time":1700000000.0,"direction":"TX","peer":"device","hex":"50494E470D0A"}
{"kind":"data","time":1700000000.1,"direction":"RX","peer":"device","hex":"504F4E470D0A"}
```

`time` is a Unix timestamp in seconds, `direction` is TX or RX and `hex` is the wire
payload. Raw recordings can also include session/status events and fields such as
`monotonic_ns`, `client_peer`, `session`, source timing, HID metadata, `original_hex`,
`modified_by`, `plugin_error` and `plugin_elapsed_ns`. Consumers should ignore
unknown keys and non-data events. Do not derive physical timing from numeric precision.

When present, `original_hex` is the pre-transform input; `hex` is the resulting
wire payload. A blocked message may have empty wire data and an error. Framed
display exports describe displayed messages; raw recordings describe transport events.

JSONL import accepts data rows with finite times and valid hex. It skips non-data
events and rejects malformed rows. Current import limits: a 24 MiB file, 2,000 data
events and 8 MiB combined payload/original bytes. Split larger recordings externally.
Raw recording itself is not constrained to these import limits.

## CSV and readable text

CSV columns are `timestamp`, `direction`, `peer`, `byte_count`, plus selected `hex`
and/or `text`. Timestamps are local ISO 8601 strings. Import supports ISO timestamps
or numeric Unix timestamps and requires `hex`. CSV is payload-oriented and omits
some raw JSONL provenance metadata. Text export is for reading, not lossless import.
A decoded-text-only export cannot be replayed or used to rebuild exact device bytes.

## Sequence JSON

Root fields: `format: "probe-sequence"`, `version`, `cycles` and `steps`.
[Basic example](../examples/test-sequence.json) uses payload text/hex, input mode,
delay, repeat and optional reply expectations. Version 3 adds variables, stable
step IDs and response extraction/routing. Older supported versions are migrated
by the loader. See [dynamic example](../examples/variable-sequence.json).
Use the editor/exporter rather than inventing unvalidated field combinations.

## Simulator JSON

Root fields: `format: "probe-device"`, `version`, `exchanges`. Each exchange has a
hex `request` and a list of replies with `hex` and `delay_ms`. Later schema versions
add framing, field match conditions and fault configuration. The
[basic model](../examples/device-model.json) and [JSON fault model](../examples/simulator-json-faults.json)
show both forms. Validate by loading in the simulator before sharing.

## Protocol fields

Root fields: `format: "probe-protocol"`, `version: 1`, `fields`. Field descriptors
include `name`, zero-based `offset`, `length`, `kind` and kind-specific options.
The [lab profile](../examples/lab-protocol.json) describes a six-byte ASCII length,
text body and CRC16 Modbus checksum. A profile validates/inspects bytes; it does
not automatically change traffic.

## Local settings and plugins

`settings.json` stores profiles, macros and last-used values. Other probe workspaces
have separate slot settings. This is local application state, not a stable public
integration API. Do not commit it. See [installation](installation.md) for paths.

Plugin API 1 exchanges bytes and ordinary dictionaries with a worker process;
see the complete [plugin contract](plugins.md). Private implementation module paths
may change; external plugins should use only that contract.
