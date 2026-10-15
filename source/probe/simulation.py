"""Compile recorded byte conversations into bounded, deterministic device models."""
from dataclasses import dataclass
from collections.abc import Iterable
from typing import Any
import math

MAX_REQUEST = 65536
MAX_MODEL_BYTES = 8 * 1024 * 1024
MAX_DELAY_MS = 3600000


@dataclass(frozen=True)
class Reply:
    data: bytes
    delay_ms: float = 0


@dataclass(frozen=True)
class Exchange:
    request: bytes
    replies: tuple[Reply, ...]


@dataclass(frozen=True)
class DeviceModel:
    exchanges: tuple[Exchange, ...]
    ignored_startup_bytes: int = 0


def capture_peers(events: Iterable[dict[str, Any]]) -> list[str]:
    # Older serial proxy captures label app TX differently from physical RX.
    peers = {str(e.get("peer", "")) for e in events if e.get("kind", "data") == "data"}
    aliases = {"App → device", "Injected to app"}
    ordinary = peers - aliases
    return sorted(ordinary if len(ordinary) == 1 else peers)


def compile_capture(events: Iterable[dict[str, Any]], peer: str | None = None,
                    request_direction: str = "TX") -> DeviceModel:
    rows = [e for e in events if e.get("kind", "data") == "data"]
    peers = capture_peers(rows)
    if peer is None:
        if len(peers) > 1:
            raise ValueError("Choose one recorded peer before building a device model.")
        peer = peers[0] if peers else ""
    if request_direction not in ("TX", "RX"):
        raise ValueError("Choose TX or RX as the recorded request direction.")
    aliases = {"App → device", "Injected to app"} if len(peers) == 1 else set()
    rows = [e for e in rows if str(e.get("peer", "")) == peer or e.get("peer") in aliases]
    exchanges: list[Exchange] = []
    request = bytearray()
    replies: list[Reply] = []
    last_time = 0.0
    ignored = total = 0
    for row in rows:
        data = bytes(row["data"])
        total += len(data)
        if total > MAX_MODEL_BYTES:
            raise ValueError("Device model exceeds 8 MiB. Select a smaller capture.")
        timestamp = float(row["time"])
        if not math.isfinite(timestamp) or row["direction"] not in ("TX", "RX"):
            raise ValueError("Capture needs finite timestamps and TX/RX directions.")
        if row["direction"] == request_direction:
            if replies:
                exchanges.append(Exchange(bytes(request), tuple(replies)))
                request.clear()
                replies.clear()
            request.extend(data)
            if len(request) > MAX_REQUEST:
                raise ValueError("A recorded request exceeds 64 KiB. Split the conversation.")
            last_time = timestamp
        elif request:
            delay = max(0.0, (timestamp - last_time) * 1000)
            if delay > MAX_DELAY_MS:
                raise ValueError("A recorded reply delay exceeds one hour. Trim the capture first.")
            replies.append(Reply(data, delay))
            last_time = timestamp
        else:
            ignored += len(data)
    if request:
        exchanges.append(Exchange(bytes(request), tuple(replies)))
    if not exchanges or not any(e.replies for e in exchanges):
        raise ValueError("Capture needs a request followed by a device reply. Record both directions first.")
    return DeviceModel(tuple(exchanges), ignored)


class RequestMatcher:
    """Match stream bytes regardless of how reads split/coalesce requests."""
    def __init__(self, model: DeviceModel, ordered: bool = True, repeat: bool = True):
        if not model.exchanges:
            raise ValueError("The device model is empty.")
        if not ordered:
            seen: dict[bytes, tuple[Reply, ...]] = {}
            for item in model.exchanges:
                if item.request in seen and tuple(r.data for r in seen[item.request]) != tuple(r.data for r in item.replies):
                    raise ValueError("The same request has different replies. Use Conversation order.")
                seen[item.request] = item.replies
            requests = list(seen)
            if any(a != b and b.startswith(a) for a in requests for b in requests):
                raise ValueError("One request is a prefix of another. Use Conversation order.")
        self.model = model
        self.ordered = ordered
        self.repeat = repeat
        self.index = 0
        self.buffer = bytearray()
        self.discarded = 0

    def feed(self, data: bytes) -> list[Exchange]:
        matches: list[Exchange] = []
        # Process in small slices to keep the pending buffer bounded even on junk.
        for byte in data:
            self.buffer.append(byte)
            while self.buffer:
                if self.ordered and self.index >= len(self.model.exchanges):
                    self.discarded += len(self.buffer)
                    self.buffer.clear()
                    break
                candidates = (self.model.exchanges[self.index],) if self.ordered else self.model.exchanges
                full = next((e for e in candidates if self.buffer == e.request), None)
                if full:
                    matches.append(full)
                    self.buffer.clear()
                    if self.ordered:
                        self.index += 1
                        if self.repeat and self.index == len(self.model.exchanges):
                            self.index = 0
                    break
                if any(e.request.startswith(self.buffer) for e in candidates):
                    break
                del self.buffer[0]
                self.discarded += 1
        return matches


def model_to_dict(model: DeviceModel) -> dict[str, Any]:
    return {"format": "probe-device", "version": 1, "exchanges": [
        {"request": item.request.hex().upper(), "replies": [
            {"hex": reply.data.hex().upper(), "delay_ms": reply.delay_ms} for reply in item.replies]}
        for item in model.exchanges]}


def model_from_dict(value: Any) -> DeviceModel:
    if not isinstance(value, dict) or value.get("format") != "probe-device" or value.get("version") != 1:
        raise ValueError("Choose a Probe device model (version 1).")
    rows = value.get("exchanges")
    if not isinstance(rows, list) or not 1 <= len(rows) <= 2000:
        raise ValueError("Device model must contain 1–2000 exchanges.")
    exchanges = []
    used = chunks = 0
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("request"), str) or not isinstance(row.get("replies"), list):
            raise ValueError("Each exchange needs request hex and a list of replies.")
        request = bytes.fromhex(row["request"])
        if not request or len(request) > MAX_REQUEST:
            raise ValueError("Each request must contain 1–65536 bytes.")
        replies = []
        for reply in row["replies"]:
            chunks += 1
            if chunks > 2000:
                raise ValueError("A model is limited to 2000 reply chunks.")
            if not isinstance(reply, dict) or not isinstance(reply.get("hex"), str):
                raise ValueError("Each reply needs a hex string and delay_ms.")
            data = bytes.fromhex(reply["hex"])
            delay = float(reply.get("delay_ms", 0))
            if not math.isfinite(delay) or not 0 <= delay <= MAX_DELAY_MS:
                raise ValueError("Reply delay must be 0–3600000 ms.")
            replies.append(Reply(data, delay))
            used += len(data)
        used += len(request)
        if used > MAX_MODEL_BYTES:
            raise ValueError("Device model exceeds 8 MiB.")
        exchanges.append(Exchange(request, tuple(replies)))
    if not any(e.replies for e in exchanges):
        raise ValueError("Add at least one device reply.")
    return DeviceModel(tuple(exchanges))
