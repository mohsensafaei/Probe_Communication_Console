"""Validated test steps and a cancellable runner on the transport event loop."""
import asyncio
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import time
from typing import Any, TYPE_CHECKING

from .codec import encode, parse_hex
from .timing import sleep_at_least, wait_for

if TYPE_CHECKING:
    from .engine import Engine

MAX_STEPS = 1000
MAX_DELAY = 3600000


def integer(value: Any, label: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{label} must be a whole number.")
    try: number = int(value)
    except (ValueError, TypeError, OverflowError):
        raise ValueError(f"{label} must be a whole number.") from None
    if str(number) != str(value).strip() or not minimum <= number <= maximum:
        raise ValueError(f"{label} must be {minimum}–{maximum}.")
    return number


@dataclass(frozen=True)
class Step:
    name: str
    payload: bytes
    delay_ms: int = 0
    repeat: int = 1
    expect: bytes = b""
    timeout_ms: int = 2000
    wait_for_reply: bool = False


def compile_steps(rows: Sequence[Mapping[str, Any]], default_delay: int = 1000) -> tuple[Step, ...]:
    if not rows or len(rows) > MAX_STEPS:
        raise ValueError(f"Add 1–{MAX_STEPS} steps before running.")
    result: list[Step] = []
    used = 0
    for index, row in enumerate(rows, 1):
        payload = encode(str(row.get("text", "")), row.get("send_mode", "Text"),
                         row.get("encoding", "utf-8"), row.get("ending", "None"),
                         row.get("checksum", "None"), row.get("prefix", ""), row.get("suffix", ""))
        if not payload:
            raise ValueError(f"Step {index} has no bytes to send.")
        used += len(payload)
        if used > 8 * 1024 * 1024:
            raise ValueError("Sequence payloads exceed 8 MiB.")
        expected = parse_hex(str(row.get("expect", "")))
        if len(expected) > 65536:
            raise ValueError("Expected reply is limited to 64 KiB.")
        wait_for_reply = row.get("wait_for_reply", False)
        if not isinstance(wait_for_reply, bool):
            raise ValueError("Wait for reply must be true or false.")
        result.append(Step(str(row.get("name", f"Step {index}")), payload,
                           integer(row.get("delay_ms", default_delay), "Delay (ms)", 0, MAX_DELAY),
                           integer(row.get("repeat", 1), "Step repeat", 1, 1000000), expected,
                           integer(row.get("timeout_ms", 2000), "Reply timeout (ms)", 1, MAX_DELAY), wait_for_reply))
    return tuple(result)


def steps_from_capture(rows: Sequence[Mapping[str, Any]], delay_ms: int = 100,
                       recorded_timing: bool = False) -> list[dict[str, Any]]:
    """Copy explicitly selected RX or TX records into outgoing, byte-exact steps.

    Direction is provenance, not a routing instruction. The caller chooses the
    destination independently. Uniform timing is the default for quick tests.
    """
    delay_ms = integer(delay_ms, "Interval (ms)", 0, MAX_DELAY)
    if not rows or len(rows) > MAX_STEPS:
        raise ValueError(f"Select 1–{MAX_STEPS} captured messages.")
    result = []
    for index, row in enumerate(rows):
        direction = row.get("direction")
        data = row.get("data")
        if direction not in ("RX", "TX") or not isinstance(data, bytes):
            raise ValueError("Select RX or TX data records from a Probe capture.")
        delay = delay_ms
        if recorded_timing and index + 1 < len(rows):
            try:
                gap = (float(rows[index+1]["time"]) - float(row["time"])) * 1000
                if not math.isfinite(gap):raise ValueError
                delay = integer(round(max(0, gap)), "Recorded delay (ms)", 0, MAX_DELAY)
            except (KeyError, TypeError, ValueError, OverflowError):
                raise ValueError("Recorded intervals must be finite and at most one hour.") from None
        result.append(dict(name=f"Captured {direction} {index+1}", text=data.hex(" ").upper(),
                           send_mode="Hex", delay_ms=delay,
                           source_direction=direction, source_peer=str(row.get("peer", ""))))
    compile_steps(result)
    return result


async def run_scenario(engine: "Engine", steps: tuple[Step, ...], cycles: int,
                       target: str, side: str) -> None:
    queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=16)
    overflow = False
    expecting = False
    sent = checked = cycle = 0
    started = time.perf_counter()
    direction = "TX" if side == "App / downstream" else "RX"

    def observe(event: dict[str, Any]) -> None:
        nonlocal overflow
        physical_reply = side == "Device / upstream" and engine.cfg["mode"] in ("USB / Serial", "Serial Proxy", "Serial ↔ TCP")
        if expecting and event.get("data") and event["direction"] == direction and (physical_reply or target == "All clients" or event["peer"] == target or event.get("client_peer") == target):
            try:
                queue.put_nowait(event["data"])
            except asyncio.QueueFull:
                overflow = True

    engine.observers.add(observe)
    engine.event("scenario", state="running", message="Test sequence running.", sent=0, checked=0, cycle=0)
    try:
        while cycles == 0 or cycle < cycles:
            cycle += 1
            for index, step in enumerate(steps, 1):
                for repetition in range(step.repeat):
                    while not queue.empty():
                        queue.get_nowait()
                    overflow = False
                    expecting = step.wait_for_reply or bool(step.expect)
                    engine.event("scenario", state="running", cycle=cycle, step=index, sent=sent, checked=checked,
                                 message=f"Cycle {cycle} · step {index}/{len(steps)} · {step.name} · repeat {repetition+1}/{step.repeat}")
                    if not await engine._send(step.payload, target, side):
                        raise RuntimeError(f"Step {index}: transport rejected the payload.")
                    sent += 1
                    if expecting:
                        engine.event("scenario", state="running", cycle=cycle, step=index, sent=sent, checked=checked,
                                     message=f"Step {index}/{len(steps)} · {step.name} · waiting for {'matching reply' if step.expect else 'reply'} (timeout {step.timeout_ms} ms)…")
                        deadline = time.perf_counter() + step.timeout_ms / 1000
                        response = bytearray()
                        while not response or (step.expect and step.expect not in response):
                            if overflow:
                                raise RuntimeError(f"Step {index}: reply capture overflow. Reduce incoming traffic.")
                            remaining = deadline - time.perf_counter()
                            if remaining <= 0:
                                raise RuntimeError(f"Step {index}: expected reply not received within {step.timeout_ms} ms.")
                            try:
                                response.extend(await wait_for(queue.get(), remaining))
                            except TimeoutError:
                                raise RuntimeError(f"Step {index}: expected reply not received within {step.timeout_ms} ms.") from None
                            if response and (not step.expect or step.expect in response):
                                break
                            if len(response) > 131072:
                                del response[:-65536]
                        checked += 1
                    expecting = False
                    await sleep_at_least(step.delay_ms / 1000)
        engine.event("scenario", state="complete", cycle=cycle, sent=sent, checked=checked,
                     message=f"Sequence complete · {cycle} cycles · {sent} sends · {checked} replies checked · {time.perf_counter()-started:.2f} s")
    except asyncio.CancelledError:
        engine.event("scenario", state="stopped", cycle=cycle, sent=sent, checked=checked,
                     message=f"Sequence stopped · {sent} sends · {checked} replies checked.")
        raise
    except Exception as exc:
        engine.event("scenario", state="failed", cycle=cycle, sent=sent, checked=checked, message=str(exc))
    finally:
        engine.observers.discard(observe)
        engine.scenario_task = None


def sequence_from_dict(value: Any) -> tuple[list[dict[str, Any]], int]:
    if isinstance(value, list):  # Original command shelf files remain usable.
        rows, cycles = value, 1
    elif isinstance(value, dict) and value.get("format") == "probe-sequence" and value.get("version") in (1, 2):
        rows = value.get("steps")
        cycles = integer(value.get("cycles", 1), "Cycles", 0, 1000000)
    else:
        raise ValueError("Choose a Probe sequence or legacy command shelf JSON file.")
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise ValueError("Sequence steps must be a list of objects.")
    compile_steps(rows)
    return rows, cycles
