"""Retained display history, independent of widgets and transport acquisition."""
from collections import OrderedDict, deque
from dataclasses import dataclass
import time


@dataclass(frozen=True)
class HistoryChange:
    added: tuple
    removed: tuple


class TrafficHistory:
    def __init__(self, max_rows=2000, max_bytes=8 * 1024 * 1024):
        self.max_rows = max_rows
        self.max_bytes = max_bytes
        self.events = OrderedDict()
        self.sequence = 0
        self.retained_bytes = 0
        self.evicted = 0

    def extend(self, events):
        """Apply retention before rendering; only report surviving new rows.

        A single read can produce 65,536 one-byte frames. Rows evicted within
        this batch never need a widget, a search or payload formatting.
        """
        if self.max_rows < 1 or self.max_bytes < 1:
            raise ValueError("History limits must be positive.")
        boundary = self.sequence
        removed = []
        added = deque()
        for event in events:
            self.sequence += 1
            key = str(self.sequence)
            self.events[key] = event
            added.append(key)
            self.retained_bytes += len(event["data"])
            if 'original_hex' in event:self.retained_bytes+=len(event['original_hex'])//2
            while len(self.events) > self.max_rows or self.retained_bytes > self.max_bytes:
                old, discarded = self.events.popitem(last=False)
                self.retained_bytes -= len(discarded["data"])
                if 'original_hex' in discarded:self.retained_bytes-=len(discarded['original_hex'])//2
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

    @staticmethod
    def _flush(state, reason):
        framer, metadata, _ = state
        return [{**metadata, "data": data, "display_partial": True, "display_reason": reason}
                for data in framer.flush()]

    def feed(self, event):
        if "hid" in event:
            yield event
            return
        if self._chunks:
            yield event
            return
        key = (event["direction"], event["peer"])
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
        yield from ({**metadata, "data": data} for data in framer.tick(now))
        # Do not keep the original large read alive just for its metadata.
        metadata = {k: v for k, v in event.items() if k != "data"}
        for data in framer.iter_feed(event["data"], now):
            partial = (framer.mode == "Idle gap" or
                       framer.mode == "Fixed length" and len(data) != framer.size or
                       framer.mode == "Delimiter" and not data.endswith(framer.delimiter))
            row = {**metadata, "data": data}
            if partial:
                row.update(display_partial=True, display_reason="frame buffer limit")
            yield row
        self.streams[key] = (framer, metadata, use_monotonic)

    def tick(self, wall_time=None, monotonic_time=None):
        wall_time = time.time() if wall_time is None else wall_time
        monotonic_time = time.perf_counter() if monotonic_time is None else monotonic_time
        result = []
        for framer, metadata, monotonic in self.streams.values():
            result.extend({**metadata, "data": data}
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
