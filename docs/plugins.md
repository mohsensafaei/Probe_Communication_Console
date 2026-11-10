# Python plugins (API 1)

Plugins work with bytes, regardless of device or protocol. No Python installation
is needed when using a portable Probe build. No packages are downloaded at runtime.

## Use a plugin

1. Open **Traffic → Plugins… → Add…**. Select a `.py` file, or a folder containing
   `main.py` and optional helper files. Probe copies it into the local data directory’s `plugins` folder (see [installation](installation.md)).
2. Enable it, choose **RX / TX / Both**, then **Apply** while disconnected.
   Settings and activation are independent for each probe tab and are saved.
3. Double-click traffic and open **Plugins** in Analyze. Live analysis results
   appear automatically; **Run analysis** also works with retained/imported traffic.
4. If supported, double-click a field, **Rebuild**, then **Preview changes**.
   The preview uses the existing Capture Diff. **Load output into composer** never
   sends by itself. **Run action** invokes a plugin-provided manual operation.
5. For numeric output, choose **Plugin: name / value** in Live plot's Value source.
   Each direction/peer has its own series. Auto and Custom keep their existing RX behavior.

Analysis alone never changes transport bytes. **Allow message changes** additionally
enables the optional `transform` hook before sending/forwarding, including Composer,
Terminal, files, Sequence, Replay, auto replies, TCP/serial proxies and simulator replies.
Selected directions follow Traffic's RX/TX convention; simulator replies are RX.
Transforms run in list order. With several plugins, add them in the desired order.
Replay also passes enabled transforms; disable changes for exact-byte replay.

Modified rows are marked **[Modified]**. Analyze → Plugins → Preview changes compares
the original input chunk and resulting wire bytes. Raw JSONL recording preserves
`original_hex`, the actual `hex`, plugin names and processing timing. A blocked send
is marked **[Blocked]** and records zero transmitted bytes plus the original input.
Text/CSV exports contain the displayed wire data; use JSONL to preserve metadata.

Python plugins are trusted executable code, with your normal user file/network
permissions. A separate process contains crashes/hangs; it is not a security sandbox.
Plugins never execute in the elevated HID helper. HID monitoring remains read-only.

## The smallest plugin

Save this as a `.py` file; metadata and every hook except the one you need are optional.

```python
def process(data, context):
    return {"fields": {"bytes": len(data)}, "values": {"Packet size": len(data)}}
```

Optional metadata is a literal dictionary, inspected without executing the file:

```python
PLUGIN = {
    "api": 1,
    "name": "My protocol",
    "description": "Decode my device's messages.",
    "settings": {"gain": 1.0, "strict": True},
    "actions": ["Generate sample"],
}
```

`context` contains `direction`, `peer`, optional `client_peer`, timestamps when
available, `workspace`, `mode`, `session`, `operation`, `settings` and `state`.
`manual` is true for explicit Analyze / Rebuild / Action invocations; these ignore
the live direction filter and do not add historical samples to the live plot.
`state` is a mutable dictionary shared between RX/TX for the same connection/peer,
isolated from other probes and sessions. State is bounded to 64 flows per plugin;
inactive flows may be evicted. Use it for counters, correlations or protocol state.
No GUI or transport object is exposed.

`process(data: bytes, context)` returns a dictionary (or None). Optional keys:

| Key | Value |
| --- | --- |
| `fields` | Name/value dictionary, or list of `{name, value, offset?, size?, editable?}` |
| `values` | Named finite numbers, or `{value: number, unit: string}` entries |
| `label`, `message` | Human-readable result |
| `valid` | Boolean validation result |
| `data` | Bytes to preview/load manually; this never implicitly changes traffic |

Field values can be JSON values. Offsets are zero-based; select a field to see its
byte range. Optional hooks use the same context and run in the same worker:

```python
def rebuild(data, fields, context):  # fields is the edited name/value dictionary
    return new_bytes

def action(name, data, context):     # name comes from PLUGIN["actions"]
    return new_bytes                # or the same result dictionary as process()

def transform(data, context):       # only runs with Allow message changes
    return new_bytes
```

`rebuild` may also return a result dictionary. Missing optional hooks are not
required. Do not rely on process() being called before transform(): analysis runs
later on a bounded display snapshot, while transforms must finish before writing.
Repeated manual Run analysis calls are additional invocations of process().

## Message boundaries

TCP/serial chunks are not messages. **Analysis follows the existing Traffic framing**:
use Chunks for byte-stream inspection or choose Fixed length / Delimiter / Idle gap
when process() needs complete messages. Partial frames are marked in Traffic.

Transforms normally receive write/forward chunks. An optional literal metadata entry
enables complete-message buffering independently for each direction and peer:

```python
"framing": {"delimiter": "0A"}  # delimiter included in each transform() call
# OR
"framing": {"size": 4}          # fixed-size complete messages
```

Split frames wait; coalesced frames are transformed separately. Empty bytes suppress
output. Incomplete transformed frames at disconnect are reported, never silently
forwarded unmodified. For a length-prefixed or other custom protocol, implement its
buffer in `context["state"]`; keep it bounded and account for incomplete data yourself.
Built-in framing applies to transform(), not to rebuild()/action() input.

The JSON example uses LF framing and a demo SHA-256 definition over sorted compact
UTF-8 JSON excluding its checksum field. Real protocols must define their own
serialization/hash/MAC rules and keys. It is not a universal checksum algorithm.

## Runtime and limits

The worker starts only when plugins are enabled. There is one reusable worker per
active plugin workspace, not one process per message. Applying changes restarts it.
Analysis never blocks acquisition or raw recording. Overload/errors are reported;
use Run analysis to retry a retained row. Result retention is 128 rows / 2 MiB.
Inputs/transform outputs are limited to 1 MiB, analysis to 256 fields / 16 metrics /
64 KiB including preview, queues to 32 requests / 8 MiB. Live plot retains at most
16 plugin sources and 300 samples per peer. A call has a two-second limit (15 seconds
for initial imports). A timed-out/crashed worker requires Apply to restart.
Transform failure blocks that send or closes the affected proxy flow; the original
message is never sent as a fallback. Transforms add latency and are unsuitable for
strict send-deadline tests. Keep them disabled when measuring base transport timing.

Portable builds include these common standard-library modules: json, struct, hashlib,
hmac, base64, binascii, re, math, statistics, decimal, datetime, collections, itertools,
functools, zlib, csv and string. Other runtime modules may also be present, but arbitrary
pip dependencies/native extensions are not automatically available. No pip installer
or package manager is included. A source installation can use its installed packages.
Folder plugins use relative helper imports, e.g. `from .helpers import decode`.
After editing copied files, disconnect and Apply again. Keep `probe-data` alongside
the portable application to carry your plugins/settings between machines.

Try `examples/plugins/binary_sensor.py` for binary fields/edit/rebuild/units, or
`examples/plugins/json_tools.py` for JSON editing, generation and checksum repair.
