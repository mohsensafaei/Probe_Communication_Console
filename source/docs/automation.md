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
