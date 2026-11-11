'Thread-contained asyncio transport engine; the UI never performs network I/O.'
import asyncio
import contextlib
import os
import threading
import time

from .recording import CaptureWriter
from .evidence.identity import CLOCK_ID, namespace
from .timing import SCHEDULED_NS
from .transports import MODES as MODES, MONITOR_MODES
from .transports import network, serial


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
        self.plugins = None
        self.workspace = 0
        self.session = namespace();self.event_sequence = 0

    def event(self, kind, **fields):
        event = {"kind": kind, "time": time.time(), **fields}
        if kind=='data':
            self.event_sequence += 1
            event.update(event_version=1, event_id=f'{self.session}:{self.workspace}:{self.event_sequence}')
            if not fields.get('tcp_capture'):
                event.update(clock_id=CLOCK_ID, monotonic_ns=time.perf_counter_ns())
            event['session']=self.session
            scheduled=SCHEDULED_NS.get()
            if scheduled is not None and 'monotonic_ns' in event:
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
        self.session = namespace();self.event_sequence = 0
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
                await self._plugin_end()
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
        if self.cfg.get("mode") in MONITOR_MODES:raise RuntimeError("This mode is capture-only. Sending and replay are disabled.")
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
            if mode in MONITOR_MODES:raise RuntimeError("This mode is capture-only.")
            if mode == "Device Simulator":
                await self._transfer(data,"RX",target,lambda out:self.simulator_send(out,target))
            elif mode == "UDP":
                await self._transfer(data,"TX",str(self.udp_target),lambda out:network.udp_send(self,out,self.udp_target))
            elif mode in ("USB / Serial", "Serial Proxy", "Serial ↔ TCP") and side == "Device / upstream":
                await self._transfer(data,"TX",self.cfg['serial_port'],lambda out:serial.write(self,self.serials[0],out))
            elif mode == "Serial Proxy":
                await self._transfer(data,"RX","Injected to app",lambda data:serial.app_write(self,data))
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
        extra={}
        if direction and self.plugins and self.plugins.changes:data,extra=await self._transform(data,direction,peer)
        writer.write(data)
        if direction: self.event("data", direction=direction, peer=peer, data=data,**extra)
        await asyncio.wait_for(writer.drain(), 10)

    async def _transform(self,data,direction,peer,**context):
        if not self.plugins or not self.plugins.changes:return data,{}
        started=time.perf_counter_ns();source_time=time.time()
        context.update(direction=direction,peer=peer,workspace=self.workspace,mode=self.cfg['mode'],session=self.session,time=source_time,monotonic_ns=started)
        try:
            reply=await asyncio.wrap_future(self.plugins.submit('transform',data,context))
        except Exception as exc:
            self.event('data',direction=direction,peer=peer,data=b'',original_hex=data.hex(),plugin_error=str(exc))
            raise RuntimeError(f'Plugin blocked sending / forwarding: {exc}') from exc
        extra={}
        if reply['data']!=data:
            extra=dict(original_hex=data.hex(),modified_by=reply['changed'],source_time=source_time,
                       source_monotonic_ns=started,plugin_elapsed_ns=time.perf_counter_ns()-started)
        return reply['data'],extra

    async def _transfer(self,data,direction,peer,write,**fields):
        extra={}
        if self.plugins and self.plugins.changes:data,extra=await self._transform(data,direction,peer,**fields)
        await write(data)
        self.event('data',direction=direction,peer=peer,data=data,**fields,**extra)

    async def _plugin_end(self,peer=''):
        if self.plugins:
            try:await asyncio.wait_for(asyncio.wrap_future(self.plugins.submit('end',b'',dict(session=self.session,peer=peer))),3)
            except Exception as exc:self.event('error',message='Plugins: '+str(exc))


    def _connected(self, message, **extra):
        self.ready = True
        self.event("state", state="Connected", message=message, **extra)


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
        if self.cfg.get("mode") in MONITOR_MODES:raise ValueError("This mode is capture-only. Sequences cannot transmit here.")
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

    async def _run(self):
        mode=self.cfg["mode"]
        if mode in MONITOR_MODES:
            if mode == 'TCP Monitor':
                from .tcp_monitor import run_monitor
            else:
                from .hid_monitor import run_monitor
            worker=asyncio.create_task(asyncio.to_thread(run_monitor,self))
            try:await asyncio.shield(worker)
            except asyncio.CancelledError:
                self.stopping.set()
                with contextlib.suppress(asyncio.TimeoutError,OSError):
                    await asyncio.wait_for(asyncio.shield(worker),10)
                raise

        elif mode == "Device Simulator":
            from .simulator import serve_simulator
            await serve_simulator(self)

        elif mode == "TCP Client":await network.run_client(self)
        elif mode in ("TCP Server","TCP Proxy","Serial ↔ TCP"):await network.run_server(self)
        elif mode == "UDP":await network.run_udp(self)
        else:await serial.run(self)
