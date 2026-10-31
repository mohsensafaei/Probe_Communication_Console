"""Thread-contained asyncio transport engine; the UI never performs network I/O."""
import asyncio
import contextlib
import datetime
import errno
import json
import os
import socket
import threading
import time
from pathlib import Path

from .timing import sleep_at_least, SCHEDULED_NS
from .recording import CaptureWriter

MODES = ("TCP Client", "TCP Server", "TCP Proxy", "UDP", "USB / Serial",
         "Serial Proxy", "Serial ↔ TCP", "Device Simulator", "HID Monitor")

class Engine:
    def __init__(self, emit):
        self.emit = emit
        self.loop = None
        self.thread = None
        self.root_task = None
        self.ready = False
        self.stopping = threading.Event()
        self.clients = {}
        self.writers = set()
        self.tasks = set()
        self.serials = []
        self.serial_locks = {}
        self.serial_pending_rx = {}
        self.udp = None
        self.server = None
        self.pty_fds = []
        self.counter = 0
        self.tx = self.rx = 0
        self.auto_reply = None
        self.echo = False
        self.capture = None
        self.raw_rx = None
        self.record_control_lock=threading.Lock()
        self.capture_writer=None
        self.recording_error_message=""
        self.compute_pool=None
        self.cfg = {}
        self.pending_sends = threading.BoundedSemaphore(64)
        self.accepting = 0
        self.pending_bytes=0
        self.pending_lock=threading.Lock()
        self.observers = set()
        self.scenario_task = None
        self.scenario_generation = 0
        self.simulator_reset = None

    def event(self, kind, **fields):
        event = {"kind": kind, "time": time.time(), **fields}
        if kind=='data':
            event['monotonic_ns']=time.perf_counter_ns()
            scheduled=SCHEDULED_NS.get()
            if scheduled is not None:
                event['scheduled_ns']=scheduled;event['dispatch_lateness_ns']=max(0,event['monotonic_ns']-scheduled)
        if kind == "data":
            data = fields["data"]
            if fields["direction"] == "TX": self.tx += len(data)
            else: self.rx += len(data)
            for observer in tuple(self.observers): observer(event)
        writer=self.capture_writer
        if writer and (self.capture or self.raw_rx):writer.enqueue(event)
        self.emit(event)

    def _recording_error(self,message):
        self.capture=self.raw_rx=None;self.recording_error_message='Recording incomplete: '+message
        self.emit(dict(kind='recording_error',time=time.time(),message=self.recording_error_message))

    def record(self,path=None,raw=False):
        with self.record_control_lock:
            # Control waits only in the caller, outside the transport capture enqueue lock.
            if self.capture_writer is not None and self.capture_writer.failed:
                self.capture_writer.close();self.capture_writer=None;self.capture=self.raw_rx=None
            if self.capture_writer is None:
                if path is None:return
                self.capture_writer=CaptureWriter(self._recording_error)
            self.capture_writer.control('raw' if raw else 'capture',path)
            if path:self.recording_error_message=''
            if raw:self.raw_rx=str(path) if path else None
            else:self.capture=str(path) if path else None

    async def compute(self,function,*args):
        if self.compute_pool is None:
            import multiprocessing
            from concurrent.futures import ProcessPoolExecutor
            self.compute_pool=ProcessPoolExecutor(max_workers=1,mp_context=multiprocessing.get_context('spawn'))
        return await self.loop.run_in_executor(self.compute_pool,function,*args)

    def start(self, cfg):
        if self.thread and self.thread.is_alive(): raise RuntimeError("Session is already running.")
        self.cfg = dict(cfg)
        self.stopping.clear()
        self.thread = threading.Thread(target=self._thread_main, name="Probe transport", daemon=True)
        self.thread.start()

    def _thread_main(self):
        async def main():
            self.loop = asyncio.get_running_loop()
            self.root_task = asyncio.current_task()
            try:
                if self.stopping.is_set(): return
                await self._run()
            except asyncio.CancelledError: pass
            except Exception as exc:
                if not self.stopping.is_set(): self.event("error", message=str(exc))
            finally:
                self.ready = False
                self.stopping.set()
                if self.server:
                    self.server.close()
                for task in list(self.tasks): task.cancel()
                if self.tasks: await asyncio.gather(*list(self.tasks), return_exceptions=True)
                for writer in list(self.writers): writer.close()
                for writer in list(self.writers):
                    with contextlib.suppress(Exception, asyncio.CancelledError):
                        await asyncio.wait_for(writer.wait_closed(), 1)
                if self.server:
                    with contextlib.suppress(Exception, asyncio.CancelledError):
                        await asyncio.wait_for(self.server.wait_closed(), 1)
                for port in self.serials:
                    pending = self.serial_pending_rx.pop(id(port), b"")
                    if pending:
                        self.event("data", direction="RX", peer=port.port, data=bytes(pending))
                    with contextlib.suppress(Exception): port.close()
                for fd in self.pty_fds:
                    with contextlib.suppress(OSError): os.close(fd)
                if self.udp: self.udp.close()
                self.clients.clear()
                self._close_workers()
                self.event("state", state="Disconnected")
        asyncio.run(main())
        self.loop = None

    def stop(self):
        if self.stopping.is_set(): return
        self.stopping.set()
        loop = self.loop
        if loop and not loop.is_closed():
            def cancel_session():
                # Server.serve_forever waits for accepted transports when cancelled.
                # Close them first so a connected application cannot hold Stop open.
                for task in list(self.tasks): task.cancel()
                for writer in list(self.writers): writer.close()
                if self.root_task: self.root_task.cancel()
            with contextlib.suppress(RuntimeError): loop.call_soon_threadsafe(cancel_session)

    def _close_workers(self):
        with self.record_control_lock:
            if self.capture_writer:
                self.capture_writer.close();self.capture_writer=None
                self.capture=self.raw_rx=None
        if self.compute_pool:
            self.compute_pool.shutdown(wait=False,cancel_futures=True);self.compute_pool=None

    def join(self, timeout=5):
        if self.thread:self.thread.join(timeout)
        else:self._close_workers()

    def schedule(self, coro):
        loop = self.loop
        if not loop or loop.is_closed() or self.stopping.is_set():
            coro.close(); return False
        def spawn():
            task = asyncio.create_task(coro)
            self.tasks.add(task); task.add_done_callback(self.tasks.discard)
        try: loop.call_soon_threadsafe(spawn);return True
        except RuntimeError: coro.close();return False

    def send(self, data, target="All clients", side="Device / upstream"):
        if self.cfg.get("mode")=="HID Monitor":raise RuntimeError("HID Monitor is capture-only. Sending and replay are disabled.")
        if not self.ready: raise RuntimeError("Connect before sending.")
        if len(data) > 16 * 1024 * 1024: raise ValueError("A payload is limited to 16 MiB. Use Send file for larger data.")
        if not self.pending_sends.acquire(blocking=False):
            raise RuntimeError("Send queue is full. Increase the repeat interval.")
        with self.pending_lock:
            if self.pending_bytes+len(data)>16*1024*1024:
                self.pending_sends.release()
                raise RuntimeError("Pending sends exceed 16 MiB. Wait or use Send file.")
            self.pending_bytes+=len(data)
        async def queued():
            try: await self._send(bytes(data), target, side)
            finally:
                with self.pending_lock:self.pending_bytes-=len(data)
                self.pending_sends.release()
        if not self.schedule(queued()):
            with self.pending_lock:self.pending_bytes-=len(data)
            self.pending_sends.release()
            raise RuntimeError("Connection closed before the send could be queued.")

    def reset_counters(self):
        async def reset():self.tx=self.rx=0
        if self.ready:self.schedule(reset())
        else:self.tx=self.rx=0

    async def _send(self, data, target, side):
        try:
            mode = self.cfg["mode"]
            if mode == "HID Monitor":raise RuntimeError("HID Monitor is capture-only.")
            if mode == "Device Simulator":
                await self.simulator_send(data, target)
                self.event("data", direction="RX", peer=target, data=data)
            elif mode == "UDP":
                await self._udp_send(data, self.udp_target)
                self.event("data", direction="TX", peer=str(self.udp_target), data=data)
            elif mode in ("USB / Serial", "Serial Proxy", "Serial ↔ TCP") and side == "Device / upstream":
                await self._serial_write(self.serials[0], data)
                self.event("data", direction="TX", peer=self.cfg["serial_port"], data=data)
            elif mode == "Serial Proxy":
                await self._app_write(data)
                self.event("data", direction="RX", peer="Injected to app", data=data)
            else:
                peers = list(self.clients.items())
                if target != "All clients": peers = [(k,v) for k,v in peers if k == target]
                if not peers: raise RuntimeError("No connected client matches the send target.")
                for peer, links in peers:
                    writer = links[1] if mode == "TCP Proxy" and side == "Device / upstream" else links[0]
                    await self._write(writer, data, direction="TX" if side == "Device / upstream" else "RX", peer=peer)
            return True
        except Exception as exc:
            if not self.stopping.is_set(): self.event("error", message=f"Send failed: {exc}")
            return False

    async def _write(self, writer, data, *, direction=None, peer=None):
        writer.write(data)
        if direction: self.event("data", direction=direction, peer=peer, data=data)
        await asyncio.wait_for(writer.drain(), 10)

    async def _serial_write(self, port, data):
        # Serial writes are bounded by write_timeout and serialized per port.
        async with self.serial_locks[id(port)]:
            n = await asyncio.to_thread(port.write, data)
            if n != len(data): raise IOError(f"Partial serial write: {n}/{len(data)} bytes")

    def _serial_read(self, port):
        data = port.read(min(max(port.in_waiting, 1), 65536))
        pending = self.serial_pending_rx.setdefault(id(port), bytearray())
        # Keep draining the driver during a write (full duplex), but publish a
        # fast reply after the corresponding TX has been recorded on this loop.
        if self.serial_locks[id(port)].locked() or pending:
            pending.extend(data)
            if len(pending) > 8 * 1024 * 1024:
                raise RuntimeError("Pending serial reply exceeds 8 MiB while a write is in progress.")
            if self.serial_locks[id(port)].locked(): return b""
            data = bytes(pending)
            pending.clear()
        return data

    def _port(self, name):
        try: import serial
        except ImportError: raise RuntimeError("USB / Serial requires pyserial. Run: python -m pip install pyserial") from None
        cfg = self.cfg
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
        self.serials.append(port); self.serial_locks[id(port)] = asyncio.Lock()
        return port

    def _connected(self, message, **extra):
        self.ready = True
        self.event("state", state="Connected", message=message, **extra)

    async def _run(self):
        cfg = self.cfg; mode = cfg["mode"]
        if mode == "HID Monitor":
            from .hid_monitor import run_monitor
            worker=asyncio.create_task(asyncio.to_thread(run_monitor,self))
            try:await asyncio.shield(worker)
            except asyncio.CancelledError:
                self.stopping.set()
                # Drain the helper before recorder/session teardown. A pending OS
                # permission dialog can outlive cancellation but emits no reports.
                with contextlib.suppress(asyncio.TimeoutError,OSError):
                    await asyncio.wait_for(asyncio.shield(worker),10)
                raise
        elif mode == "Device Simulator":
            from .simulator import serve_simulator
            await serve_simulator(self)
        elif mode == "TCP Client":
            reader, writer = await asyncio.wait_for(asyncio.open_connection(cfg["host"], int(cfg["port"])), 5)
            self.writers.add(writer)
            peer = f'{cfg["host"]}:{cfg["port"]}'
            self.clients[peer] = (writer,)
            self.event("peers", peers=list(self.clients))
            self._connected(f"Connected to {peer}")
            await self._reader(reader, writer, peer)
        elif mode in ("TCP Server", "TCP Proxy", "Serial ↔ TCP"):
            if mode == "Serial ↔ TCP": self._port(cfg["serial_port"])
            self.server = await asyncio.start_server(self._accept, cfg["bind"], int(cfg["listen_port"]))
            addr = self.server.sockets[0].getsockname()
            self._connected(f"Listening on {addr[0]}:{addr[1]}", address=addr)
            if mode == "Serial ↔ TCP":
                task = asyncio.create_task(self._serial_bridge_rx())
                self.tasks.add(task); task.add_done_callback(self.tasks.discard)
            await self.server.serve_forever()
        elif mode == "UDP":
            # Resolve IPv4 names off the GUI thread; UDP broadcast is explicit.
            infos = await self.loop.getaddrinfo(cfg["host"], int(cfg["port"]), family=socket.AF_INET, type=socket.SOCK_DGRAM)
            self.udp_target = infos[0][4]
            self.udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.udp.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            self.udp.bind((cfg["bind"], int(cfg["listen_port"])))
            self.udp.setblocking(False)
            self._connected(f"UDP bound to {self.udp.getsockname()}", address=self.udp.getsockname())
            while True:
                data, address = await self._udp_receive()
                peer = f"{address[0]}:{address[1]}"
                self.event("data", direction="RX", peer=peer, data=data)
                response = data if self.echo else self.auto_reply
                if response is not None:
                    await self._udp_send(response, address)
                    self.event("data", direction="TX", peer=peer, data=response)
        else:
            physical = self._port(cfg["serial_port"])
            if mode == "Serial Proxy":
                app_port = cfg.get("app_port", "Auto PTY")
                if app_port == "Auto PTY":
                    if os.name == "nt": raise ValueError("On Windows, enter Probe's end of an installed virtual COM pair.")
                    import tty
                    master, slave = os.openpty()
                    self.pty_fds = [master, slave]
                    tty.setraw(slave); os.set_blocking(master, False)
                    self.app_path = os.ttyname(slave)
                else:
                    from .serial_endpoints import VirtualPair
                    pair = VirtualPair(app_port, cfg.get("app_peer_port", ""))
                    pair.validate(cfg["serial_port"])
                    self._port(pair.probe); self.app_path = pair.application
                self._connected(f"Serial proxy ready. App connects to {self.app_path}", app_path=self.app_path)
            else: self._connected(f'Opened {cfg["serial_port"]}')
            next_lines = 0
            while True:
                data = self._serial_read(physical)
                if data:
                    self.event("data", direction="RX", peer=cfg["serial_port"], data=data)
                    if mode == "Serial Proxy": await self._app_write(data)
                    if mode != "Serial Proxy":
                        response = data if self.echo else self.auto_reply
                        if response is not None:
                            await self._serial_write(physical, response)
                            self.event("data", direction="TX", peer=cfg["serial_port"], data=response)
                if mode == "Serial Proxy":
                    if self.pty_fds:
                        try: sent = os.read(self.pty_fds[0], 65536)
                        except BlockingIOError: sent = b""
                    else:
                        port = self.serials[1]
                        sent = self._serial_read(port)
                    if sent:
                        await self._serial_write(physical, sent)
                        self.event("data", direction="TX", peer=cfg["serial_port"], data=sent)
                if time.monotonic() > next_lines:
                    self._lines(physical); next_lines = time.monotonic() + .5
                await sleep_at_least(.01)

    async def _udp_receive(self):
        if hasattr(self.loop,"sock_recvfrom"):
            return await self.loop.sock_recvfrom(self.udp,65535)
        # Python 3.10 lacks the datagram socket coroutine helpers.
        while True:
            try:return self.udp.recvfrom(65535)
            except (BlockingIOError,InterruptedError):await sleep_at_least(.001)

    async def _udp_send(self,data,address):
        if hasattr(self.loop,"sock_sendto"):
            return await self.loop.sock_sendto(self.udp,data,address)
        while True:
            try:return self.udp.sendto(data,address)
            except (BlockingIOError,InterruptedError):await sleep_at_least(.001)

    async def _app_write(self, data):
        if self.pty_fds:
            view = memoryview(data)
            deadline = time.monotonic() + 5
            while view:
                try: view = view[os.write(self.pty_fds[0], view):]
                except BlockingIOError:
                    if time.monotonic() > deadline: raise TimeoutError("App is not reading its PTY.")
                    await sleep_at_least(.01)
        else: await self._serial_write(self.serials[1], data)

    def _lines(self, port):
        with contextlib.suppress(Exception):
            self.event("lines", CTS=port.cts, DSR=port.dsr, DCD=port.cd, RI=port.ri)

    def control(self, name, value=True):
        async def change():
            try:
                if not self.serials: raise RuntimeError("Open a serial session first.")
                if name == "break": await asyncio.to_thread(self.serials[0].send_break, .25)
                else: setattr(self.serials[0], name, value)
                self.event("info", message=f"{name.upper()} = {value}")
            except Exception as exc: self.event("error", message=f"Control line: {exc}")
        self.schedule(change())

    def start_scenario(self, steps, cycles=1, target="All clients", side="Device / upstream", variables=None):
        from .scenario import integer, run_scenario
        from .sequence_flow import needs_reply
        if self.cfg.get("mode")=="HID Monitor":raise ValueError("HID Monitor is capture-only. Sequences cannot transmit here.")
        if not self.ready: raise RuntimeError("Connect before running a test sequence.")
        if self.cfg["mode"] == "Device Simulator":
            raise ValueError("Run sequences from an application transport; the simulator replies to its clients.")
        cycles = integer(cycles, "Cycles", 0, 1000000)
        if not steps: raise ValueError("Add a sequence step first.")
        if target == "All clients" and len(self.clients) > 1 and any(needs_reply(step) for step in steps):
            raise ValueError("Select one client when checking expected replies.")
        if (target == "All clients" and len(self.clients) == 1 and any(needs_reply(step) for step in steps)
                and (self.cfg["mode"] in ("TCP Client", "TCP Server", "TCP Proxy") or side == "App / downstream")):
            target = next(iter(self.clients))
        self.scenario_generation += 1
        generation = self.scenario_generation
        async def start():
            if generation != self.scenario_generation: return
            if self.scenario_task and not self.scenario_task.done():
                self.scenario_task.cancel()
                await asyncio.gather(self.scenario_task, return_exceptions=True)
            if generation != self.scenario_generation: return
            task = asyncio.create_task(run_scenario(self, steps, cycles, target, side, variables))
            self.scenario_task = task
            self.tasks.add(task)
            task.add_done_callback(self.tasks.discard)
        if not self.schedule(start()): raise RuntimeError("Connection closed before the sequence started.")

    def stop_scenario(self):
        self.scenario_generation += 1
        generation = self.scenario_generation
        if self.loop and not self.loop.is_closed():
            def cancel():
                if generation == self.scenario_generation and self.scenario_task: self.scenario_task.cancel()
            with contextlib.suppress(RuntimeError): self.loop.call_soon_threadsafe(cancel)

    def reset_simulator(self):
        async def reset():
            if self.simulator_reset: self.simulator_reset()
        self.schedule(reset())

    async def _reader(self, reader, writer, peer):
        while True:
            data = await reader.read(65536)
            if not data: return
            self.event("data", direction="RX", peer=peer, data=data)
            response = data if self.echo else self.auto_reply
            if response is not None:
                await self._write(writer, response, direction="TX", peer=peer)

    async def _accept(self, reader, writer):
        current = asyncio.current_task()
        self.tasks.add(current)
        peer = None; remote_writer = None
        admitted = False
        self.writers.add(writer)
        try:
            mode = self.cfg["mode"]
            if self.accepting >= (1 if mode == "Serial ↔ TCP" else 16):
                self.event("info", message="Rejected connection: session client limit reached."); return
            self.accepting += 1; admitted = True
            self.counter += 1
            addr = writer.get_extra_info("peername")
            peer = f"#{self.counter} {addr[0]}:{addr[1]}"
            if mode == "TCP Proxy":
                remote_reader, remote_writer = await asyncio.wait_for(
                    asyncio.open_connection(self.cfg["host"], int(self.cfg["port"])), 5)
                self.writers.add(remote_writer)
                self.clients[peer] = (writer, remote_writer)
            else: self.clients[peer] = (writer,)
            self.event("peers", peers=list(self.clients))
            self.event("info", message=f"Client connected: {peer}")
            if mode == "TCP Proxy":
                async def pump(src, dst, direction):
                    while True:
                        data = await src.read(65536)
                        if not data:
                            if dst.can_write_eof(): dst.write_eof(); await dst.drain()
                            return
                        self.event("data", direction=direction, peer=peer, data=data)
                        await self._write(dst, data)
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
                    await self._serial_write(self.serials[0], data)
                    self.event("data", direction="TX", peer=self.cfg["serial_port"], client_peer=peer, data=data)
            else: await self._reader(reader, writer, peer)
        except asyncio.CancelledError: raise
        except Exception as exc:
            if not self.stopping.is_set(): self.event("error", message=f"Client session: {exc}")
        finally:
            for w in (writer, remote_writer):
                if w:
                    w.close()
                    with contextlib.suppress(Exception, asyncio.CancelledError): await asyncio.wait_for(w.wait_closed(), 1)
                    self.writers.discard(w)
            if peer:
                self.clients.pop(peer, None)
                self.event("peers", peers=list(self.clients))
                self.event("info", message=f"Client disconnected: {peer}")
            self.tasks.discard(current)
            if admitted: self.accepting -= 1

    async def _serial_bridge_rx(self):
        try:
            while True:
                port = self.serials[0]
                data = self._serial_read(port)
                if data:
                    self.event("data", direction="RX", peer=self.cfg["serial_port"], data=data)
                    for peer, links in list(self.clients.items()): await self._write(links[0], data)
                await sleep_at_least(.01)
        except asyncio.CancelledError: raise
        except Exception as exc:
            self.event("error", message=f"Serial bridge stopped: {exc}")
            self.stop()
