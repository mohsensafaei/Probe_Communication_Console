'Retained display history, independent of widgets and transport acquisition.'
import time
from collections import OrderedDict, deque
from dataclasses import dataclass

from .evidence.identity import Origins, namespace


@dataclass(frozen=True)
class HistoryChange:
    added: tuple
    removed: tuple


def retained_size(event):
    return len(event['data']) + len(event.get('original_hex',''))//2 + sum(320+len(ref['event_id']) for ref in event.get('source_refs',()))


class TrafficHistory:
    def __init__(self, max_rows=2000, max_bytes=8 * 1024 * 1024):
        self.max_rows = max_rows
        self.max_bytes = max_bytes
        self.events = OrderedDict()
        self.sequence = 0
        self.identity = namespace()
        self.retained_bytes = 0
        self.evicted = 0

    def extend(self, events):
        'Apply retention before rendering; only report surviving new rows.'
        if self.max_rows < 1 or self.max_bytes < 1:
            raise ValueError("History limits must be positive.")
        boundary = self.sequence
        removed = []
        added = deque()
        for event in events:
            self.sequence += 1
            key = str(self.sequence)
            if not event.get('event_id'):event = dict(event, event_version=1, event_id=f'{self.identity}:{key}')
            self.events[key] = event
            added.append(key)
            self.retained_bytes += retained_size(event)
            while len(self.events) > self.max_rows or self.retained_bytes > self.max_bytes:
                old, discarded = self.events.popitem(last=False)
                self.retained_bytes -= retained_size(discarded)
                self.evicted += 1
                if int(old) <= boundary:
                    removed.append(old)
                else:
                    added.popleft()
        return HistoryChange(tuple(added), tuple(removed))

    def clear(self):
        self.events.clear()
        self.retained_bytes = self.evicted = 0


class DisplayFraming:
    """Group display bytes with bounded peer state and acquisition timestamps."""
    def __init__(self, factory, max_streams=64):
        if max_streams < 1:
            raise ValueError("Stream limit must be positive.")
        self.factory = factory
        self.max_streams = max_streams
        self.streams = OrderedDict()
        self._chunks = False
        self.identity = namespace();self.sequence = 0

    def _row(self, metadata, data):
        row = {**metadata, 'data': data}
        origins = row.pop('_origins', None)
        if origins is not None:
            self.sequence += 1
            refs, complete = origins.take(len(data))
            row.update(event_version=1, event_id=f'{self.identity}:{self.sequence}', source_refs=refs, source_refs_complete=complete)
        pending = row.pop('_original', None)
        if pending is not None:
            original = bytes(pending[:len(data)])
            del pending[:len(data)]
            if original != data:row['original_hex'] = original.hex()
            else:row.pop('modified_by', None)
        return row

    def _flush(self, state, reason):
        framer, metadata, _ = state
        return [{**self._row(metadata, data), "display_partial": True, "display_reason": reason}
                for data in framer.flush()]

    def feed(self, event):
        if "hid" in event:
            yield event
            return
        if self._chunks:
            yield event
            return
        key = tuple(event.get(k, '') for k in ('direction', 'peer', 'client_peer', 'session'))
        if key not in self.streams:
            framer = self.factory()
            if framer.mode == "Chunks":
                self._chunks = True
                yield event
                return
            if len(self.streams) >= self.max_streams:
                _, state = self.streams.popitem(last=False)
                yield from self._flush(state, "stream limit")
            self.streams[key] = (framer, {}, "monotonic_ns" in event)
        framer, metadata, monotonic = self.streams[key]
        self.streams.move_to_end(key)
        use_monotonic = "monotonic_ns" in event
        if monotonic != use_monotonic:
            yield from self._flush(self.streams[key], "clock changed")
        now = event["monotonic_ns"] / 1e9 if use_monotonic else event["time"]
        yield from (self._row(metadata, data) for data in framer.tick(now))
        original = bytes.fromhex(event['original_hex']) if 'original_hex' in event else None
        if original is not None and len(original) != len(event['data']):
            yield from self._flush(self.streams.pop(key), 'plugin changed length')
            yield {**event, 'display_partial': True, 'display_reason': 'plugin changed length; showing transport chunk'}
            return
        origins = metadata.get('_origins') or Origins()
        origins.add(event)
        previous = metadata.get('_original')
        changed = bool(previous) or original is not None
        modifiers = metadata.get('modified_by', []) if framer.buffer else []
        if changed:
            if previous is None:previous = bytearray(framer.buffer)
            previous.extend(original if original is not None else event['data'])
        metadata = {k: v for k, v in event.items() if k not in ('data', 'original_hex')}
        metadata['_origins'] = origins
        if changed:
            metadata['_original'] = previous
            metadata['modified_by'] = list(dict.fromkeys(modifiers + event.get('modified_by', [])))
        for data in framer.iter_feed(event["data"], now):
            partial = (framer.mode == "Idle gap" or
                       framer.mode == "Fixed length" and len(data) != framer.size or
                       framer.mode == "Delimiter" and not data.endswith(framer.delimiter))
            row = self._row(metadata, data)
            if partial:
                row.update(display_partial=True, display_reason="frame buffer limit")
            yield row
        self.streams[key] = (framer, metadata, use_monotonic)

    def tick(self, wall_time=None, monotonic_time=None):
        wall_time = time.time() if wall_time is None else wall_time
        monotonic_time = time.perf_counter() if monotonic_time is None else monotonic_time
        result = []
        for framer, metadata, monotonic in self.streams.values():
            result.extend(self._row(metadata, data)
                          for data in framer.tick(monotonic_time if monotonic else wall_time))
        return result

    def flush(self, reason="session ended"):
        result = []
        for state in self.streams.values():
            result.extend(self._flush(state, reason))
        self.clear()
        return result

    def clear(self):
        self.streams.clear()
        self._chunks = False
