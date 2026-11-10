# Automation and diagnostic workflows

## Stable message references

Raw data events receive an ID before recording and display. IDs contain a unique
session namespace, probe slot and event counter; they do not depend on tab names,
filters or the row number. JSONL export/import preserves them and monotonic timing
metadata. Legacy captures receive deterministic IDs based on file contents.

Right-click Traffic → **Copy message IDs**, or **Find message by ID…**. Finding
an ID clears display filters and selects the retained row; it never sends bytes.
An evicted message must be recovered from its capture, not guessed from a row number.

Framed rows have separate IDs and `source_refs` containing immediate source event
IDs and zero-based, end-exclusive wire-byte ranges. `source_refs_complete` indicates
whether all ranges are known. References are capped at 128 per buffered frame;
exceeding this limit preserves the payload but reports unavailable provenance.
Imported framed events can themselves be sources when reframed. Referenced raw
chunks are not necessarily retained alongside the displayed message.

These identifiers and host timestamps do not establish physical causality or
wire timing. Hex bytes remain authoritative. No AI provider or network upload is
involved in any of these operations.

## Structured analysis

Analyze → **Save analysis…** exports `probe-analysis` version 1 JSON. It reuses the
same inspector and configured protocol fields as the UI. Checks include actual /
expected length or checksum, the field byte range and the bytes used to validate it.
Truncated fields and unavailable parsing are distinct from validated mismatches.
Offsets are zero-based and end-exclusive. No device failure is inferred.

Raw events also carry `clock_id`: a process-specific clock scope. Observation
intervals use monotonic timestamps only within the same scope; otherwise they are
explicitly wall-time differences. Neither establishes wire latency or causality.
