'Compile recorded byte conversations into bounded, deterministic device models.'
import math
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from typing import Any

from .rules import Condition, Fault, FrameSpec, RequestContext, RequestFrames, conditions_from_dict, fault_from_dict, fault_to_dict, frame_from_dict, frame_to_dict, reply_plan

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
    match: tuple[Condition, ...] | None = None
    fault: Fault | None = None
    name: str = ""


@dataclass(frozen=True)
class DeviceModel:
    exchanges: tuple[Exchange, ...]
    ignored_startup_bytes: int = 0
    framing: FrameSpec | None = None


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
    def __new__(cls, model, ordered=True, repeat=True):
        if cls is RequestMatcher and model.framing is not None:
            return FramedMatcher(model, ordered, repeat)
        return super().__new__(cls)

    def __init__(self, model: DeviceModel, ordered: bool = True, repeat: bool = True):
        if not model.exchanges:
            raise ValueError("The device model is empty.")
        if any(e.match for e in model.exchanges):
            raise ValueError("Field rules need Request framing. Choose JSON, delimiter, fixed length or length prefix.")
        if not ordered:
            seen: dict[bytes, Exchange] = {}
            for item in model.exchanges:
                if item.request in seen and (seen[item.request].replies, seen[item.request].fault) != (item.replies, item.fault):
                    raise ValueError("The same request has different replies. Use Conversation order.")
                seen[item.request] = item
            requests = list(seen)
            if any(a != b and b.startswith(a) for a in requests for b in requests):
                raise ValueError("One request is a prefix of another. Use Conversation order.")
        self.model = model
        self.ordered = ordered
        self.repeat = repeat
        self.index = 0
        self.buffer = bytearray()
        self.discarded = 0
        self.hits = [0] * len(model.exchanges)
        self.details = []
        self.errors = []

    def reset(self):
        self.index = self.discarded = 0
        self.buffer.clear()
        self.hits = [0] * len(self.model.exchanges)
        self.details = []
        self.errors = []

    def feed(self, data: bytes) -> list[Exchange]:
        matches: list[Exchange] = []
        self.details = []
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
                    rule = self.index if self.ordered else next(i for i,e in enumerate(self.model.exchanges) if e is full)
                    self.hits[rule] += 1
                    self.details.append((rule, self.hits[rule]))
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


class FramedMatcher:
    """Validate full wire messages before testing semantic AND predicates."""
    def __init__(self, model, ordered=True, repeat=True):
        self.model, self.ordered, self.repeat = model, ordered, repeat
        if not model.exchanges: raise ValueError("The device model is empty.")
        self.frames = RequestFrames(model.framing)
        for item in model.exchanges:
            if item.match is None:
                frames = RequestFrames(model.framing)
                actual = frames.feed(item.request)
                expected = [item.request.strip()] if model.framing.mode == "JSON" else [item.request]
                if actual != expected or frames.buffer:
                    raise ValueError("An exact request does not fit Request framing. Edit the request or framing first.")
                model.framing.payload(item.request)
        self.reset()

    @property
    def buffer(self): return self.frames.buffer

    def reset(self):
        self.frames.reset()
        self.index = self.discarded = 0
        self.hits = [0] * len(self.model.exchanges)
        self.details, self.errors = [], []

    def feed(self, data):
        self.details, self.errors = [], []
        result = []
        raw_frames = self.frames.feed(data)
        self.discarded += self.frames.discarded
        self.frames.discarded = 0
        self.errors.extend(self.frames.errors)
        for raw in raw_frames:
            try: body = self.model.framing.payload(raw)
            except (ValueError, RecursionError) as exc:
                self.discarded += len(raw)
                if len(self.errors)<8: self.errors.append(str(exc))
                continue
            context = RequestContext(body)
            candidates = [self.index] if self.ordered and self.index<len(self.model.exchanges) else [] if self.ordered else range(len(self.model.exchanges))
            found, reasons = [], []
            for index in candidates:
                item = self.model.exchanges[index]
                if item.match is None:
                    same = raw == item.request
                    if self.model.framing.mode == "JSON": same = raw.strip() == item.request.strip()
                    reason = "Exact request bytes differ."
                else:
                    same, reason = True, ""
                    for condition in item.match:
                        same, reason = condition.evaluate(context)
                        if not same: break
                if same: found.append(index)
                elif len(reasons)<3: reasons.append(f"{item.name or 'Rule '+str(index+1)}: {reason}")
            if len(found)!=1:
                self.discarded += len(raw)
                reason = "Ambiguous request: matches multiple rules. Make their conditions distinct." if found else "; ".join(reasons) or "Conversation finished; reset or enable Repeat."
                if len(self.errors)<8: self.errors.append(reason)
                continue
            index = found[0]
            self.hits[index] += 1
            self.details.append((index, self.hits[index]))
            result.append(self.model.exchanges[index])
            if self.ordered:
                self.index += 1
                if self.repeat and self.index == len(self.model.exchanges): self.index = 0
        return result


def model_to_dict(model: DeviceModel) -> dict[str, Any]:
    advanced = model.framing is not None or any(e.match is not None or e.fault or e.name for e in model.exchanges)
    result = {"format": "probe-device", "version": 2 if advanced else 1, "exchanges": []}
    if model.framing: result["framing"] = frame_to_dict(model.framing)
    for item in model.exchanges:
        row = {"request": item.request.hex().upper(), "replies": [
            {"hex": r.data.hex().upper(), "delay_ms": r.delay_ms} for r in item.replies]}
        if item.match is not None: row["match"] = [asdict(c) for c in item.match]
        if item.fault: row["fault"] = fault_to_dict(item.fault)
        if item.name: row["name"] = item.name
        result["exchanges"].append(row)
    return result


def model_from_dict(value: Any) -> DeviceModel:
    if not isinstance(value, dict) or value.get("format") != "probe-device" or value.get("version") not in (1,2):
        raise ValueError("Choose a Probe device model (version 1 or 2).")
    rows = value.get("exchanges")
    if not isinstance(rows, list) or not 1 <= len(rows) <= 2000:
        raise ValueError("Device model must contain 1–2000 rules.")
    framing = frame_from_dict(value.get("framing"))
    exchanges = []
    used = chunks = 0
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("request", ""), str) or not isinstance(row.get("replies"), list):
            raise ValueError("Each rule needs request hex and a list of replies.")
        request = bytes.fromhex(row.get("request", ""))
        conditions = conditions_from_dict(row.get("match"))
        if (not request and conditions is None) or len(request)>MAX_REQUEST:
            raise ValueError("Exact requests must contain 1–65536 bytes.")
        replies = []
        for reply in row["replies"]:
            chunks += 1
            if chunks>2000: raise ValueError("A model is limited to 2000 reply chunks.")
            if not isinstance(reply, dict) or not isinstance(reply.get("hex"), str): raise ValueError("Each reply needs hex and delay_ms.")
            data = bytes.fromhex(reply["hex"])
            delay = float(reply.get("delay_ms",0))
            if not math.isfinite(delay) or not 0<=delay<=MAX_DELAY_MS: raise ValueError("Reply delay must be 0–3600000 ms.")
            replies.append(Reply(data,delay)); used += len(data)
        fault = fault_from_dict(row.get("fault"))
        name = row.get("name", "")
        if not isinstance(name,str) or len(name)>120: raise ValueError("Rule names are limited to 120 characters.")
        item = Exchange(request, tuple(replies), conditions, fault, name)
        if fault: reply_plan(item, fault.nth)
        used += len(request)+len(name.encode())+(len(fault.payload) if fault else 0)
        if conditions: used += sum(len(c.value.encode())+len(c.selector.encode()) for c in conditions)
        if used>MAX_MODEL_BYTES: raise ValueError("Device model exceeds 8 MiB.")
        exchanges.append(item)
    if not any(e.replies or e.fault for e in exchanges): raise ValueError("Add at least one device reply or fault.")
    model = DeviceModel(tuple(exchanges), framing=framing)
    RequestMatcher(model)  # Validate framing without opening a transport.
    return model
