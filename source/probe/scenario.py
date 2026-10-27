"""Validated test steps and a cancellable runner on the transport event loop."""
import asyncio
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import time
from typing import Any, TYPE_CHECKING

from .codec import parse_hex
from .protocol import MAX_DATA, IncompleteMessage
from .sequence_flow import Action, Flow, SendSpec, compile_flow, display_value, initial_variables, needs_reply, send_spec
from .timing import sleep_at_least, wait_for, SequenceClock, SCHEDULED_NS
from . import processing

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
    template: SendSpec | None = None
    flow: Flow | None = None
    step_id: str = ""


def compile_steps(rows: Sequence[Mapping[str, Any]], default_delay: int = 1000, *, check_targets=True) -> tuple[Step, ...]:
    if not rows or len(rows) > MAX_STEPS:
        raise ValueError(f"Add 1–{MAX_STEPS} steps before running.")
    result: list[Step] = []
    used = 0
    for index, row in enumerate(rows, 1):
        payload, template = send_spec(row)
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
                           integer(row.get("timeout_ms", 2000), "Reply timeout (ms)", 1, MAX_DELAY), wait_for_reply,
                           template, compile_flow(row), str(row.get("step_id", ""))))
    ids = [step.step_id for step in result if step.step_id]
    if len(ids) != len(set(ids)):raise ValueError("Sequence message IDs must be unique.")
    for step in result:
        if step.flow:
            for action in (step.flow.on_true, step.flow.on_false, step.flow.on_timeout):
                if check_targets and action.action == "goto" and action.target not in ids:raise ValueError(f"{step.name}: branch destination no longer exists. Edit Response & next step.")
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


async def compute(engine,function,*args):
    worker=getattr(engine,'compute',None)
    return await worker(function,*args) if worker else function(*args)


async def run_scenario(engine: "Engine", steps: tuple[Step, ...], cycles: int,
                       target: str, side: str, variables=None) -> None:
    queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=16)
    overflow = False
    expecting = False
    sent = checked = cycle = 0
    started = time.perf_counter()
    clock=SequenceClock()
    direction = "TX" if side == "App / downstream" else "RX"
    initial = dict(variables or {})
    values = dict(initial)
    destinations = {step.step_id: index for index, step in enumerate(steps) if step.step_id}
    finished = False
    next_progress=0

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
            values = dict(initial)
            position = visits = 0
            while position < len(steps) and not finished:
                visits += 1
                if visits > 10000:raise RuntimeError("Sequence branch limit reached (10000 message visits per cycle). Check Go to rules.")
                index = position+1;step = steps[position];route = Action()
                for repetition in range(step.repeat):
                    timed_out = False
                    while not queue.empty():
                        queue.get_nowait()
                    overflow = False
                    gated=needs_reply(step)
                    payload = await compute(engine,processing.render,step.template,values) if step.template else step.payload
                    scheduled_ns=await clock.before_send()
                    while not queue.empty():queue.get_nowait()
                    overflow=False;expecting=gated
                    if step.flow:
                        for item in step.flow.extract:values.pop(item.name, None)
                    now=time.perf_counter()
                    if gated or now>=next_progress:
                        next_progress=now+.05
                        engine.event("scenario", state="running", cycle=cycle, step=index, sent=sent, checked=checked,
                                     message=f"Cycle {cycle} · step {index}/{len(steps)} · {step.name} · repeat {repetition+1}/{step.repeat}")
                    token=SCHEDULED_NS.set(scheduled_ns)
                    try:
                        clock.dispatched(time.perf_counter_ns())
                        if not await engine._send(payload, target, side):
                            raise RuntimeError(f"Step {index}: transport rejected the payload.")
                    finally:SCHEDULED_NS.reset(token)
                    sent += 1
                    if expecting:
                        engine.event("scenario", state="running", cycle=cycle, step=index, sent=sent, checked=checked,
                                     message=f"Step {index}/{len(steps)} · {step.name} · waiting for {'matching reply' if step.expect else 'reply'} (timeout {step.timeout_ms} ms)…")
                        deadline = time.perf_counter() + step.timeout_ms / 1000
                        response = bytearray()
                        timed_out = False
                        while True:
                            if overflow:
                                raise RuntimeError(f"Step {index}: reply capture overflow. Reduce incoming traffic.")
                            if response and (not step.expect or step.expect in response):
                                try:
                                    extracted = await compute(engine,processing.extract,step.flow.extract,bytes(response)) if step.flow and step.flow.extract else {}
                                except IncompleteMessage:pass
                                else:
                                    proposed={**values,**extracted}
                                    if len(proposed) > 256:raise ValueError("A run supports at most 256 variables.")
                                    if sum(len(value) if isinstance(value,bytes) else len(display_value(value).encode('utf-8')) for value in proposed.values())>8*1024*1024:
                                        raise ValueError("Run variables exceed 8 MiB.")
                                    values=proposed
                                    break
                            remaining = deadline - time.perf_counter()
                            if remaining <= 0:
                                timed_out = True;break
                            try:
                                response.extend(await wait_for(queue.get(), remaining))
                            except TimeoutError:
                                timed_out = True;break
                            if len(response) > MAX_DATA:raise RuntimeError(f"Step {index}: reply exceeds 1 MiB.")
                        if timed_out:
                            route = step.flow.on_timeout if step.flow else Action("fail")
                            if route.action == "fail":raise RuntimeError(f"Step {index}: expected reply/fields not received within {step.timeout_ms} ms.")
                        else:checked += 1
                    expecting = False
                    if step.flow and not timed_out:
                        route = step.flow.on_true if step.flow.matches(values) else step.flow.on_false
                    if step.flow:
                        engine.event("scenario", state="running", cycle=cycle, step=index, sent=sent, checked=checked,
                                     variables={key: display_value(value)[:1024] for key,value in values.items()},
                                     message=f"Step {index}/{len(steps)} · {step.name} · {route.action} · {len(values)} variables")
                    if route.action == "fail":raise RuntimeError(f"Step {index} · {step.name}: reply condition failed.")
                    await clock.after_send(step.delay_ms,reply_gated=gated)
                    if route.action != "next" or timed_out:break
                if route.action == "stop":finished = True
                elif route.action == "goto":position = destinations[route.target]
                else:position += 1
            if finished:break
        engine.last_sequence_timing=clock.summary()
        engine.event("scenario", state="complete", cycle=cycle, sent=sent, checked=checked,timing=clock.summary(),variables={key:display_value(value)[:1024] for key,value in values.items()},
                     message=f"Sequence complete · {sent} sends · max dispatch lateness {clock.max_late_ns/1e6:.3f} ms · {clock.skipped} missed slots (all messages kept).")
    except asyncio.CancelledError:
        engine.event("scenario", state="stopped", cycle=cycle, sent=sent, checked=checked,timing=clock.summary(),
                     message=f"Sequence stopped · {sent} sends · {checked} replies checked.")
        raise
    except Exception as exc:
        engine.event("scenario", state="failed", cycle=cycle, sent=sent, checked=checked,timing=clock.summary(), message=str(exc))
    finally:
        engine.observers.discard(observe)
        engine.scenario_task = None


def sequence_from_dict(value: Any) -> tuple[list[dict[str, Any]], int]:
    if isinstance(value, list):  # Original command shelf files remain usable.
        rows, cycles = value, 1
    elif isinstance(value, dict) and value.get("format") == "probe-sequence" and value.get("version") in (1, 2, 3):
        rows = value.get("steps")
        cycles = integer(value.get("cycles", 1), "Cycles", 0, 1000000)
        initial_variables(value.get("variables", {}))
    else:
        raise ValueError("Choose a Probe sequence or legacy command shelf JSON file.")
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise ValueError("Sequence steps must be a list of objects.")
    compile_steps(rows)
    return rows, cycles
