import asyncio
import contextlib
import socket

from ..sequences.timing import sleep_at_least
from . import serial


async def read_client(engine, reader, writer, peer):
    while True:
        data = await reader.read(65536)
        if not data: return
        engine.event("data", direction="RX", peer=peer, data=data)
        response = data if engine.echo else engine.auto_reply
        if response is not None:
            await engine._write(writer, response, direction="TX", peer=peer)


async def accept_client(engine, reader, writer):
    current = asyncio.current_task()
    engine.tasks.add(current)
    peer = None; remote_writer = None
    admitted = False
    engine.writers.add(writer)
    try:
        mode = engine.cfg["mode"]
        if engine.accepting >= (1 if mode == "Serial ↔ TCP" else 16):
            engine.event("info", message="Rejected connection: session client limit reached."); return
        engine.accepting += 1; admitted = True
        engine.counter += 1
        addr = writer.get_extra_info("peername")
        peer = f"#{engine.counter} {addr[0]}:{addr[1]}"
        if mode == "TCP Proxy":
            remote_reader, remote_writer = await asyncio.wait_for(
                asyncio.open_connection(engine.cfg["host"], int(engine.cfg["port"])), 5)
            engine.writers.add(remote_writer)
            engine.clients[peer] = (writer, remote_writer)
        else: engine.clients[peer] = (writer,)
        engine.event("peers", peers=list(engine.clients))
        engine.event("info", message=f"Client connected: {peer}")
        if mode == "TCP Proxy":
            async def pump(src, dst, direction):
                while True:
                    data = await src.read(65536)
                    if not data:
                        if dst.can_write_eof(): dst.write_eof(); await dst.drain()
                        return
                    await engine._write(dst, data, direction=direction, peer=peer)
            # Preserve half-close: a client may finish writing, then wait for its reply.
            pumps = [asyncio.create_task(pump(reader, remote_writer, "TX")),
                     asyncio.create_task(pump(remote_reader, writer, "RX"))]
            try: await asyncio.gather(*pumps)
            finally:
                for task in pumps: task.cancel()
                await asyncio.gather(*pumps, return_exceptions=True)
        elif mode == "Serial ↔ TCP":
            while True:
                data = await reader.read(65536)
                if not data: break
                await engine._transfer(data,'TX',engine.cfg['serial_port'],lambda out:serial.write(engine,engine.serials[0],out),client_peer=peer)
        else: await read_client(engine,reader, writer, peer)
    except asyncio.CancelledError: raise
    except Exception as exc:
        if not engine.stopping.is_set(): engine.event("error", message=f"Client session: {exc}")
    finally:
        for w in (writer, remote_writer):
            if w:
                w.close()
                with contextlib.suppress(Exception, asyncio.CancelledError): await asyncio.wait_for(w.wait_closed(), 1)
                engine.writers.discard(w)
        if peer:
            await engine._plugin_end(peer)
            engine.clients.pop(peer, None)
            engine.event("peers", peers=list(engine.clients))
            engine.event("info", message=f"Client disconnected: {peer}")
        engine.tasks.discard(current)
        if admitted: engine.accepting -= 1


async def udp_receive(engine):
    if hasattr(engine.loop,"sock_recvfrom"):
        return await engine.loop.sock_recvfrom(engine.udp,65535)
    # Python 3.10 lacks the datagram socket coroutine helpers.
    while True:
        try:return engine.udp.recvfrom(65535)
        except (BlockingIOError,InterruptedError):await sleep_at_least(.001)


async def udp_send(engine,data,address):
    if hasattr(engine.loop,"sock_sendto"):
        return await engine.loop.sock_sendto(engine.udp,data,address)
    while True:
        try:return engine.udp.sendto(data,address)
        except (BlockingIOError,InterruptedError):await sleep_at_least(.001)


async def run_client(engine):
    cfg=engine.cfg
    reader, writer = await asyncio.wait_for(asyncio.open_connection(cfg["host"], int(cfg["port"])), 5)
    engine.writers.add(writer)
    peer = f'{cfg["host"]}:{cfg["port"]}'
    engine.clients[peer] = (writer,)
    engine.event("peers", peers=list(engine.clients))
    engine._connected(f"Connected to {peer}")
    await read_client(engine,reader, writer, peer)


async def run_server(engine):
    cfg=engine.cfg;mode=cfg["mode"]
    if mode == "Serial ↔ TCP": serial.open_port(engine,cfg["serial_port"])
    engine.server = await asyncio.start_server(lambda reader,writer:accept_client(engine,reader,writer), cfg["bind"], int(cfg["listen_port"]))
    addr = engine.server.sockets[0].getsockname()
    engine._connected(f"Listening on {addr[0]}:{addr[1]}", address=addr)
    if mode == "Serial ↔ TCP":
        task = asyncio.create_task(serial.bridge_rx(engine))
        engine.tasks.add(task); task.add_done_callback(engine.tasks.discard)
    await engine.server.serve_forever()


async def run_udp(engine):
    cfg=engine.cfg
    infos = await engine.loop.getaddrinfo(cfg["host"], int(cfg["port"]), family=socket.AF_INET, type=socket.SOCK_DGRAM)
    engine.udp_target = infos[0][4]
    engine.udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    engine.udp.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    engine.udp.bind((cfg["bind"], int(cfg["listen_port"])))
    engine.udp.setblocking(False)
    engine._connected(f"UDP bound to {engine.udp.getsockname()}", address=engine.udp.getsockname())
    while True:
        data, address = await udp_receive(engine)
        peer = f"{address[0]}:{address[1]}"
        engine.event("data", direction="RX", peer=peer, data=data)
        response = data if engine.echo else engine.auto_reply
        if response is not None:
            await engine._transfer(response,'TX',peer,lambda out:udp_send(engine,out,address))
