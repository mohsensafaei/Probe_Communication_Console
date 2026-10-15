"""Expose a recorded device model on TCP or an unbacked Linux virtual serial port."""
import asyncio
import contextlib
import os
from typing import TYPE_CHECKING

from .simulation import DeviceModel, RequestMatcher, MAX_DELAY_MS

if TYPE_CHECKING:
    from .engine import Engine


async def serve_simulator(engine: "Engine") -> None:
    model = engine.cfg.get("simulator_model")
    if not isinstance(model, DeviceModel):
        raise ValueError("Build a device model from a capture in Test lab first.")
    ordered = engine.cfg.get("simulator_matching", "Conversation order") == "Conversation order"
    repeat = bool(engine.cfg.get("simulator_repeat", True))
    scale = float(engine.cfg.get("simulator_timing", 1))
    if not 0 <= scale <= 10 or any(r.delay_ms * scale > MAX_DELAY_MS for e in model.exchanges for r in e.replies):
        raise ValueError("Reply timing multiplier must be 0–10 and each delay at most one hour.")
    RequestMatcher(model, ordered, repeat)  # Validate policies before opening an endpoint.
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
            matcher.index = 0
            matcher.buffer.clear()
            matcher.discarded = 0
        engine.event("simulator", state="ready", message="Device conversations reset to the first request.")

    engine.simulator_reset = reset

    async def process(data: bytes, peer: str, write) -> None:
        nonlocal matches
        matcher = matchers[peer]
        signal = reset_signal
        previous = matcher.discarded
        engine.event("data", direction="TX", peer=peer, data=data)
        exchanges = matcher.feed(data)
        if matcher.discarded > previous:
            engine.event("simulator", state="unmatched", message=f"Unmatched request bytes from {peer}: {matcher.discarded-previous} ignored.")
        for exchange in exchanges:
            for reply in exchange.replies:
                delay = reply.delay_ms * scale / 1000
                if delay:
                    try: await asyncio.wait_for(signal.wait(), delay)
                    except TimeoutError: pass
                else: await asyncio.sleep(0)
                if signal.is_set(): return
                await write(reply.data)
                engine.event("data", direction="RX", peer=peer, data=reply.data)
            matches += 1
            engine.event("simulator", state="matched", matches=matches,
                         message=f"Device simulator · {matches} requests matched · {peer}")

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
        engine.simulator_send = lambda data, target: engine._app_write(data)
        engine._connected(f"Simulated device ready at {peer}", app_path=peer)
        while True:
            try:
                data = os.read(master, 65536)
            except BlockingIOError:
                data = b""
            if data:
                await process(data, peer, engine._app_write)
            await asyncio.sleep(.001)
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
                    await process(data, peer, lambda payload: engine._write(writer, payload))
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
        raise ValueError("Choose TCP socket or Virtual serial (PTY).")
