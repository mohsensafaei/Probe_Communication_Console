'Expose a recorded device on TCP, a POSIX PTY or an installed COM pair.'
import asyncio
import contextlib
import os
from dataclasses import replace
from typing import TYPE_CHECKING

from .plugins import MAX_DATA
from .serial_endpoints import VirtualPair
from .simulation import MAX_DELAY_MS, DeviceModel, Reply, RequestMatcher
from .simulator_rules import reply_plan
from .timing import sleep_at_least, wait_for
from .transports import serial

if TYPE_CHECKING:
    from .engine import Engine


async def serve_simulator(engine: "Engine") -> None:
    model = engine.cfg.get("simulator_model")
    if not isinstance(model, DeviceModel):
        raise ValueError("Build a device model from a capture in Test lab first.")
    responder = engine.plugins if engine.plugins and engine.plugins.responds else None
    if not responder and not any(e.fault or any(r.data for r in e.replies) for e in model.exchanges):
        raise ValueError('Add a reply or enable an RX/Both respond() plugin with Allow message changes.')
    ordered = engine.cfg.get("simulator_matching", "Conversation order") == "Conversation order"
    repeat = bool(engine.cfg.get("simulator_repeat", True))
    scale = float(engine.cfg.get("simulator_timing", 1))
    if not 0 <= scale <= 10 or any(r.delay_ms * scale > MAX_DELAY_MS for e in model.exchanges for r in e.replies):
        raise ValueError("Reply timing multiplier must be 0–10 and each delay at most one hour.")
    RequestMatcher(model, ordered, repeat)  # Validate policies before opening an endpoint.
    for item in model.exchanges:
        plan = reply_plan(item, item.fault.nth if item.fault else 1)
        if any(delay * scale > MAX_DELAY_MS for _, delay in plan.chunks):
            raise ValueError("Scaled fault delay exceeds one hour.")
    matchers: dict[str, RequestMatcher] = {}
    writers: dict[str, asyncio.StreamWriter] = {}
    matches = 0
    reset_signal = asyncio.Event()

    def reset() -> None:
        nonlocal matches, reset_signal
        reset_signal.set()
        reset_signal = asyncio.Event()
        matches = 0
        for matcher in matchers.values():
            matcher.reset()
        engine.event("simulator", state="ready", message="Device conversations reset to the first request.")

    engine.simulator_reset = reset

    async def process(data: bytes, peer: str, write) -> bool:
        nonlocal matches
        matcher = matchers[peer]
        signal = reset_signal
        previous = matcher.discarded
        engine.event("data", direction="TX", peer=peer, data=data)
        exchanges = matcher.feed(data)
        if matcher.discarded > previous:
            engine.event("simulator", state="unmatched", message=f"Unmatched request bytes from {peer}: {matcher.discarded-previous} ignored.")
        for reason in matcher.errors:
            engine.event("simulator", state="unmatched", message=f"{peer}: {reason}")
        if not exchanges and matcher.buffer and not matcher.errors:
            engine.event("simulator", state="waiting", message=f"Waiting for a complete request from {peer} · {len(matcher.buffer)} bytes buffered.")
        for exchange, (rule, hit, request) in zip(exchanges, matcher.details):
            label = exchange.name or f'Rule {rule+1}'
            try:
                if responder:
                    context = dict(direction='RX', peer=peer, session=engine.session, workspace=engine.workspace,
                                   mode='Device Simulator', rule_name=exchange.name, rule_index=rule, match_number=hit)
                    if len(request) + sum(len(r.data) for r in exchange.replies) > MAX_DATA:
                        raise ValueError('Plugin request and default reply together exceed 1 MiB.')
                    default = b''.join(r.data for r in exchange.replies)
                    reply = await asyncio.wrap_future(responder.submit('respond', request, context, reply=default))
                    if signal.is_set():return False
                    if reply is not None:
                        delay = exchange.replies[0].delay_ms if exchange.replies else 0
                        exchange = replace(exchange, replies=(Reply(reply, delay),) if reply else ())
                plan = reply_plan(exchange, hit)
            except (RuntimeError, ValueError) as exc:
                engine.event('simulator', state='error', message=f'{label} · {peer} · Reply blocked: {exc}')
                continue
            if plan.description:
                engine.event("simulator", state="fault", message=f"{label} · {plan.description} · {peer}")
            for payload, delay_ms in plan.chunks:
                delay = delay_ms * scale / 1000
                if delay:
                    try: await wait_for(signal.wait(), delay)
                    except TimeoutError: pass
                else: await asyncio.sleep(0)
                if signal.is_set(): return False
                if payload:
                    await engine._transfer(payload,'RX',peer,write)
            if signal.is_set(): return False
            matches += 1
            engine.event("simulator", state="matched", matches=matches,
                         message=f"Device simulator · {matches} requests matched · {label} / hit {hit} · {plan.description or 'Normal reply'} · {peer}")
            if plan.disconnect: return True
        return False

    transport = engine.cfg.get("simulator_transport", "TCP socket")
    if transport == "Virtual serial (PTY)":
        if os.name != "posix":
            raise ValueError("Automatic virtual serial ports require Linux/POSIX.")
        import tty
        master, slave = os.openpty()
        engine.pty_fds = [master, slave]
        tty.setraw(slave)
        os.set_blocking(master, False)
        engine.app_path = os.ttyname(slave)
        peer = engine.app_path
        matchers[peer] = RequestMatcher(model, ordered, repeat)
        engine.simulator_send = lambda data, target: serial.app_write(engine,data)
        engine._connected(f"Simulated device ready at {peer}", app_path=peer)
        while True:
            try:
                data = os.read(master, 65536)
            except BlockingIOError:
                data = b""
            if data:
                if await process(data, peer, lambda data: serial.app_write(engine,data)): return
            await sleep_at_least(.001)
    elif transport == "Virtual COM pair":
        pair = VirtualPair(engine.cfg.get("simulator_port", ""), engine.cfg.get("simulator_peer_port", ""))
        pair.validate()
        port = serial.open_port(engine,pair.probe)
        engine.app_path = pair.application
        peer = pair.application
        matchers[peer] = RequestMatcher(model, ordered, repeat)

        async def write(payload: bytes) -> None:
            await serial.write(engine,port, payload)

        engine.simulator_send = lambda data, target: write(data)
        engine._connected(f"Simulated device: app opens {peer}; Probe owns {pair.probe}", app_path=peer)
        while True:
            data = serial.read(engine,port)
            if data:
                if await process(data, peer, write): return
            await sleep_at_least(.001)
    elif transport == "TCP socket":
        async def connection(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            task = asyncio.current_task()
            engine.tasks.add(task)
            engine.writers.add(writer)
            peer = ""
            try:
                if len(writers) >= 16:
                    engine.event("info", message="Simulator client limit reached (16).")
                    return
                engine.counter += 1
                address = writer.get_extra_info("peername")
                peer = f"#{engine.counter} {address[0]}:{address[1]}"
                matchers[peer] = RequestMatcher(model, ordered, repeat)
                writers[peer] = writer
                engine.clients[peer] = (writer,)
                engine.event("peers", peers=list(writers))
                while data := await reader.read(65536):
                    if await process(data, peer, lambda payload: engine._write(writer, payload)): break
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                engine.event("info", message=f"Simulator client disconnected: {exc}")
            finally:
                writer.close()
                with contextlib.suppress(Exception, asyncio.CancelledError):
                    await asyncio.wait_for(writer.wait_closed(), 1)
                engine.writers.discard(writer)
                writers.pop(peer, None)
                await engine._plugin_end(peer)
                matchers.pop(peer, None)
                engine.clients.pop(peer, None)
                engine.event("peers", peers=list(writers))
                engine.tasks.discard(task)

        async def inject(data: bytes, target: str) -> None:
            selected = list(writers) if target == "All clients" else [target] if target in writers else []
            if not selected:
                raise RuntimeError("No connected application. Connect it to the simulator first.")
            for peer in selected:
                await engine._write(writers[peer], data)

        engine.simulator_send = inject
        engine.server = await asyncio.start_server(connection, engine.cfg.get("bind", "127.0.0.1"),
                                                   int(engine.cfg.get("listen_port", 9001)))
        address = engine.server.sockets[0].getsockname()
        engine._connected(f"Simulated device listening on {address[0]}:{address[1]}", address=address)
        await engine.server.serve_forever()
    else:
        raise ValueError("Choose TCP socket, Virtual serial (PTY) or Virtual COM pair.")
