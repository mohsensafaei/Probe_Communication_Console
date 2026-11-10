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

## Share a diagnostic case

Select Traffic messages, right-click → **Share diagnostic case…**. Describe the
problem and expected behavior. Add 0–20 surrounding rows or explicitly include
selected messages from other probes. The dialog snapshots retained history once;
new traffic does not silently change the evidence while reviewing it.

**Preview** builds the case off the UI/acquisition path. **Copy summary** gives a
bounded Markdown summary; **Save case…** writes a ZIP with README.md, case.json
(metadata, findings, observation intervals) and traffic.jsonl (chosen bytes once).
Limits are 200 messages / 8 MiB, including original payloads. No upload, connection,
send, plugin execution or AI service is involved. Existing exports remain unchanged.

Settings are snapshots at export. `settings_session` identifies the session they
belong to, when known; other sessions may have different settings. Health counters
cover the current display since Clear, not the lifetime recording. Completeness
is always unknown for selected evidence. Referenced raw chunks may not be included.
Plugin activation/direction/transform flags are included; executable code, settings,
private file paths and credentials are not automatically bundled.

Masking accepts literal text, one value per line, encoded with each probe's selected
encoding. It masks wire bytes and original bytes before producing hex and derived
output, and literal metadata text. It is not automatic secret discovery or arbitrary
binary-field redaction. Masking omits opaque HID/plugin-error metadata and disables
protocol findings for the sanitized copy: masking can invalidate lengths/checksums.
Turning off payloads exports metadata only. Review the preview and chosen scope;
other secrets must be removed explicitly. Sanitized rows cannot be imported for
replay. Original traffic is never modified. All copy/save actions require a fresh
preview after editing options.

Each message's analysis is limited to 64 KiB input and 32 fields/checks in a case;
larger or truncated results are labeled. Use Save analysis for a fuller individual
report. Observation gaps do not infer missing replies or the component at fault.

## Generate and review configuration files

The `schemas` folder publishes self-contained JSON Schema 2020-12 contracts for
Sequence (versions 1–3), Simulator (1–2), Protocol profile (1), diagnostic case
metadata and structured analysis. Give the relevant schema and an example to your
external assistant. No AI service is built into Probe.

Use **Load…** in Sequences, **Load model** in the simulator, or **Load profile** in
the protocol editor. Probe validates with its existing execution/analysis services
and shows an Apply / Cancel preview before replacing anything. A sequence preview
includes messages, repetitions, delays/reply checks and the current destination.
Dynamic variables/routing are still resolved at execution time. Import never
starts a connection, simulator or sequence. Cancel leaves the current setup intact.

Schemas describe authoring structure; Probe remains authoritative for hex parsing,
combined byte limits, numeric-string bounds, checksum ranges and branch targets.
No second runtime validator or runtime dependency is added. Legacy input formats
remain supported. Automated schema/example checks use the development dependency
in `requirements-dev.txt`; install it before running the complete test suite.
