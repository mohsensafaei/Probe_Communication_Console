"""Bounded transport-to-display handoff; never touches Tk or recording.

Data and control events share FIFO ordering but independent capacities. Traffic
pressure may evict display data, never a connection/recording status. This is a
rolling display, not the lossless recorder. Control-only floods retain the latest
128 controls; both kinds of loss are counted explicitly.
"""
from collections import deque
from queue import Empty
from threading import Lock


def event_cost(event):
    """Conservative queue budget including decoded HID metadata, not just bytes."""
    cost = 512
    stack = list(event.values())
    while stack:
        value = stack.pop()
        if isinstance(value, bytes):
            cost += len(value)
        elif isinstance(value, str):
            cost += len(value) * 4
        elif isinstance(value, dict):
            cost += 128 * len(value)
            stack.extend(value.values())
        elif isinstance(value, (list, tuple)):
            cost += 64 + 8 * len(value)
            stack.extend(value)
        else:
            cost += 32
    return cost


class DisplayEventBuffer:
    def __init__(self, max_events=1024, max_bytes=8 * 1024 * 1024, max_controls=128):
        if min(max_events, max_bytes, max_controls) < 1:
            raise ValueError("Display buffer limits must be positive.")
        self.max_events = max_events
        self.max_bytes = max_bytes
        self.max_controls = max_controls
        self._data = deque()
        self._controls = deque()
        self._lock = Lock()
        self._serial = self._data_serial = self._delivered = 0
        self._pending_bytes = 0
        self._dropped = self._dropped_controls = 0

    def put_nowait(self, event):
        cost = event_cost(event) if event["kind"] == "data" else 0
        with self._lock:
            self._serial += 1
            if event["kind"] != "data":
                if len(self._controls) == self.max_controls:
                    self._controls.popleft()
                    self._dropped_controls += 1
                self._controls.append((self._serial, event))
                return
            self._data_serial += 1
            if cost > self.max_bytes:
                self._dropped += 1
                return
            while self._data and (len(self._data) >= self.max_events or
                                  self._pending_bytes + cost > self.max_bytes):
                self._pending_bytes -= self._data.popleft()[3]
                self._dropped += 1
            self._data.append((self._serial, self._data_serial, event, cost))
            self._pending_bytes += cost

    def get_nowait(self):
        with self._lock:
            if self._controls and (not self._data or self._controls[0][0] < self._data[0][0]):
                return self._controls.popleft()[1]
            if not self._data:
                raise Empty
            _, serial, event, cost = self._data.popleft()
            self._pending_bytes -= cost
            gap = serial != self._delivered + 1
            self._delivered = serial
            # Never mutate the shared Engine/recorder event.
            return {**event, "_display_gap": True} if gap else event

    def empty(self):
        with self._lock:
            return not self._data and not self._controls

    def stats(self):
        with self._lock:
            return dict(events=len(self._data), controls=len(self._controls),
                        pending_bytes=self._pending_bytes, dropped=self._dropped,
                        dropped_controls=self._dropped_controls)

    def reset_stats(self):
        with self._lock:
            self._dropped = self._dropped_controls = 0
