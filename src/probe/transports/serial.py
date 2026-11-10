import asyncio
import contextlib
import errno
import os
import time

from ..sequences.timing import sleep_at_least


async def write(engine, port, data):
    # Serial writes are bounded by write_timeout and serialized per port.
    async with engine.serial_locks[id(port)]:
        n = await asyncio.to_thread(port.write, data)
        if n != len(data): raise IOError(f"Partial serial write: {n}/{len(data)} bytes")


def read(engine, port):
    data = port.read(min(max(port.in_waiting, 1), 65536))
    pending = engine.serial_pending_rx.setdefault(id(port), bytearray())
    if engine.serial_locks[id(port)].locked() or pending:
        pending.extend(data)
        if len(pending) > 8 * 1024 * 1024:
            raise RuntimeError("Pending serial reply exceeds 8 MiB while a write is in progress.")
        if engine.serial_locks[id(port)].locked(): return b""
        data = bytes(pending)
        pending.clear()
    return data


def open_port(engine, name):
    try:
        import serial
    except ImportError: raise RuntimeError("USB / Serial requires pyserial. Run: python -m pip install pyserial") from None
    cfg = engine.cfg
    kwargs = dict(baudrate=int(cfg.get("baud",115200)), bytesize=int(cfg.get("bits",8)),
                  parity=cfg.get("parity","N"), stopbits=float(cfg.get("stopbits",1)),
                  timeout=0, write_timeout=2, xonxoff=cfg.get("flow") == "XON/XOFF",
                  rtscts=cfg.get("flow") == "RTS/CTS", dsrdtr=cfg.get("flow") == "DSR/DTR")
    if os.name != "nt" and "://" not in name: kwargs["exclusive"] = True
    if not hasattr(serial, "serial_for_url"):
        raise RuntimeError("Wrong 'serial' package installed. Use the source launcher to install pyserial.")
    port = serial.serial_for_url(name, do_not_open=True, **kwargs)
    try:
        port.dtr = bool(cfg.get("dtr",False)); port.rts = bool(cfg.get("rts",False))
        port.open()
    except Exception as exc:
        with contextlib.suppress(Exception): port.close()
        if os.name == "posix" and getattr(exc, "errno", None) in (errno.EACCES, errno.EPERM):
            import getpass
            import grp
            import shlex
            try: group = grp.getgrgid(os.stat(name).st_gid).gr_name
            except (OSError, KeyError): group = "dialout"
            command = f"sudo usermod -aG {shlex.quote(group)} {shlex.quote(getpass.getuser())}"
            raise RuntimeError(f"Permission denied: {name}. Run {command}, then log out and back in.") from exc
        raise
    engine.serials.append(port); engine.serial_locks[id(port)] = asyncio.Lock()
    return port


async def app_write(engine, data):
    if engine.pty_fds:
        view = memoryview(data)
        deadline = time.monotonic() + 5
        while view:
            try: view = view[os.write(engine.pty_fds[0], view):]
            except BlockingIOError:
                if time.monotonic() > deadline: raise TimeoutError("App is not reading its PTY.")
                await sleep_at_least(.01)
    else: await write(engine,engine.serials[1], data)


def lines(engine, port):
    with contextlib.suppress(Exception):
        engine.event("lines", CTS=port.cts, DSR=port.dsr, DCD=port.cd, RI=port.ri)


async def bridge_rx(engine):
    try:
        while True:
            port = engine.serials[0]
            data = read(engine,port)
            if data:
                client_peer=next(iter(engine.clients),'')
                data,extra=await engine._transform(data,'RX',engine.cfg['serial_port'],client_peer=client_peer)
                engine.event("data", direction="RX", peer=engine.cfg["serial_port"], client_peer=client_peer,data=data,**extra)
                for peer, links in list(engine.clients.items()): await engine._write(links[0], data)
            await sleep_at_least(.01)
    except asyncio.CancelledError: raise
    except Exception as exc:
        engine.event("error", message=f"Serial bridge stopped: {exc}")
        engine.stop()


async def run(engine):
    cfg=engine.cfg;mode=cfg["mode"]
    physical = open_port(engine,cfg["serial_port"])
    if mode == "Serial Proxy":
        app_port = cfg.get("app_port", "Auto PTY")
        if app_port == "Auto PTY":
            if os.name == "nt": raise ValueError("On Windows, enter Probe's end of an installed virtual COM pair.")
            import tty
            master, slave = os.openpty()
            engine.pty_fds = [master, slave]
            tty.setraw(slave); os.set_blocking(master, False)
            engine.app_path = os.ttyname(slave)
        else:
            from .endpoints import VirtualPair
            pair = VirtualPair(app_port, cfg.get("app_peer_port", ""))
            pair.validate(cfg["serial_port"])
            open_port(engine,pair.probe); engine.app_path = pair.application
        engine._connected(f"Serial proxy ready. App connects to {engine.app_path}", app_path=engine.app_path)
    else: engine._connected(f'Opened {cfg["serial_port"]}')
    next_lines = 0
    while True:
        data = read(engine,physical)
        if data:
            if mode == "Serial Proxy": await engine._transfer(data,'RX',cfg['serial_port'],lambda data: app_write(engine,data))
            else:engine.event("data", direction="RX", peer=cfg["serial_port"], data=data)
            if mode != "Serial Proxy":
                response = data if engine.echo else engine.auto_reply
                if response is not None:
                    await engine._transfer(response,'TX',cfg['serial_port'],lambda out:write(engine,physical,out))
        if mode == "Serial Proxy":
            if engine.pty_fds:
                try: sent = os.read(engine.pty_fds[0], 65536)
                except BlockingIOError: sent = b""
            else:
                port = engine.serials[1]
                sent = read(engine,port)
            if sent:
                await engine._transfer(sent,'TX',cfg['serial_port'],lambda out:write(engine,physical,out))
        if time.monotonic() > next_lines:
            lines(engine,physical); next_lines = time.monotonic() + .5
        await sleep_at_least(.01)
