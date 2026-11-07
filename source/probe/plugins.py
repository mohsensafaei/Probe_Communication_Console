"""Small Python plugin contract; user code only runs in a disposable worker."""
import ast
from collections import OrderedDict
from concurrent.futures import Future
import importlib.util
import json
import math
import multiprocessing as mp
from pathlib import Path
import queue
import threading
import time

MAX_DATA = 1024 * 1024
MAX_RESULT = 64 * 1024


def metadata(path):
    path = Path(path)
    if path.stat().st_size > MAX_DATA:
        raise ValueError('A plugin entry file is limited to 1 MiB.')
    tree = ast.parse(path.read_text(encoding='utf-8-sig'), filename=str(path))
    info = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'PLUGIN' for t in node.targets):
            info = ast.literal_eval(node.value)
    if not isinstance(info, dict) or type(info.get('api',1)) is not int or info.get('api', 1) != 1:
        raise ValueError('This plugin requires an unsupported Probe plugin API.')
    info = dict(info, name=str(info.get('name', path.stem))[:80])
    if not isinstance(info.get('settings', {}), dict) or not isinstance(info.get('actions', []), list):
        raise ValueError('PLUGIN.settings must be a dictionary and actions a list of names.')
    if len(info.get('settings',{}))>32 or len(info.get('actions',[]))>16 or not all(isinstance(k,str) for k in info.get('settings',{})) or not all(isinstance(k,str) for k in info.get('actions',[])):
        raise ValueError('Use at most 32 named settings and 16 named actions.')
    try:encoded=json.dumps(info,allow_nan=False)
    except (TypeError,ValueError,RecursionError) as exc:raise ValueError('Plugin metadata must contain JSON-compatible values.') from exc
    if len(encoded.encode())>MAX_RESULT:raise ValueError('Plugin metadata exceeds 64 KiB.')
    info['hooks'] = [n.name for n in tree.body if isinstance(n, ast.FunctionDef)]
    info['hooks'] += [a.asname or a.name for n in tree.body if isinstance(n,ast.ImportFrom) for a in n.names]
    framing=info.get('framing',{})
    if framing:
        if not isinstance(framing,dict) or set(framing) not in ({'delimiter'},{'size'}):
            raise ValueError('framing needs either delimiter (hex) or size (bytes).')
        if 'delimiter' in framing and (not isinstance(framing['delimiter'],str) or not 1<=len(bytes.fromhex(framing['delimiter']))<=32):
            raise ValueError('Framing delimiter must contain 1–32 bytes.')
        if 'size' in framing and (type(framing['size']) is not int or not 1<=framing['size']<=MAX_DATA):
            raise ValueError('Framing size must be 1–1048576 bytes.')
    return info


def result(value):
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError('process() must return a dictionary or None.')
    value = dict(value)
    if 'data' in value:
        data = value.pop('data')
        if not isinstance(data, bytes) or len(data) > MAX_DATA:
            raise ValueError('Preview data must be bytes, at most 1 MiB.')
        value['data_hex'] = data.hex()
    fields = value.get('fields', [])
    if isinstance(fields, dict):
        fields = [dict(name=k, value=v) for k, v in fields.items()]
    if not isinstance(fields, list) or len(fields) > 256:
        raise ValueError('Return at most 256 fields.')
    for field in fields:
        if not isinstance(field, dict) or not isinstance(field.get('name'), str) or 'value' not in field:
            raise ValueError('Each field needs a name and value.')
        for key in ('offset', 'size'):
            if key in field and (type(field[key]) is not int or field[key] < 0):
                raise ValueError('Field offsets and sizes must be non-negative integers.')
    value['fields'] = fields
    values = value.get('values', {})
    if not isinstance(values, dict) or len(values) > 16:
        raise ValueError('Return at most 16 named numeric values.')
    for name, sample in values.items():
        number = sample.get('value') if isinstance(sample, dict) else sample
        if not isinstance(name, str) or type(number) not in (int, float) or not math.isfinite(number):
            raise ValueError('Plot values must be finite numbers.')
    encoded = json.dumps(value, allow_nan=False)
    if len(encoded.encode()) > MAX_RESULT:
        raise ValueError('Analysis result exceeds 64 KiB; return a smaller preview.')
    return json.loads(encoded)


def _worker(pipe, entries):
    try:
        plugins = []
        for index, entry in enumerate(entries):
            path = Path(entry['path']); info = metadata(path); info['name']=entry.get('name',info['name'])
            spec = importlib.util.spec_from_file_location(f'probe_user_{index}', path,
                                                        submodule_search_locations=[str(path.parent)])
            module = importlib.util.module_from_spec(spec)
            import sys
            sys.modules[spec.name] = module
            spec.loader.exec_module(module)
            plugins.append((entry, info, module, OrderedDict()))
        pipe.send((True, None))
        while True:
            operation, data, context, options = pipe.recv()
            try:
                if operation == 'ready': pipe.send((True, [])); continue
                if operation == 'end':
                    pending=0
                    for _,_,_,states in plugins:
                        for flow in list(states):
                            if flow[0]==str(context.get('session','')) and (not context.get('peer') or context['peer'] in flow[1:]):
                                pending+=sum(len(b) for b in states[flow]['buffers'].values())
                                states[flow]['buffers'].clear()
                    if pending:raise ValueError(f'{pending} incomplete plugin frame bytes were not forwarded; original chunks remain in Traffic / capture.')
                    pipe.send((True, []));continue
                output = []; changed = []
                for entry, info, module, states in plugins:
                    if not options.get('plugin') and entry.get('direction', 'Both') not in ('Both', context.get('direction', 'RX')):
                        continue
                    if options.get('plugin') and entry['id'] != options['plugin']:
                        continue
                    if operation == 'transform' and not entry.get('changes'):
                        continue
                    function = getattr(module, operation, None)
                    if function is None:
                        if options.get('plugin') and operation != 'process':raise ValueError(f"{info['name']} has no {operation}() hook.")
                        continue
                    flow = tuple(str(context.get(k, '')) for k in ('session', 'peer', 'client_peer'))
                    if flow not in states:
                        if len(states) >= 64:
                            if any(states[next(iter(states))]['buffers'].values()):raise ValueError('Plugin stream limit reached with an incomplete frame.')
                            states.popitem(last=False)
                        states[flow] = dict(user={},buffers={})
                    states.move_to_end(flow)
                    ctx = dict(context, operation=operation, manual=context.get('manual',False),state=states[flow]['user'],
                               settings=info.get('settings', {}) | entry.get('settings', {}))
                    started = time.perf_counter_ns()
                    try:
                        if operation == 'rebuild': value = function(data, options['fields'], ctx)
                        elif operation == 'action': value = function(options['action'], data, ctx)
                        elif operation == 'transform':
                            frames=[data];framing=info.get('framing',{})
                            if framing:
                                buffer=states[flow]['buffers'].setdefault(context['direction'],bytearray());buffer.extend(data)
                                if len(buffer)>MAX_DATA:raise ValueError('Incomplete plugin frame exceeds 1 MiB.')
                                frames=[];delimiter=bytes.fromhex(framing['delimiter']) if 'delimiter' in framing else None
                                while buffer:
                                    size=buffer.find(delimiter)+len(delimiter) if delimiter and delimiter in buffer else framing.get('size',0)
                                    if not size or len(buffer)<size:break
                                    frames.append(bytes(buffer[:size]));del buffer[:size]
                            parts=[]
                            for frame in frames:
                                part=function(frame,ctx)
                                if not isinstance(part,bytes) or len(part)>MAX_DATA:raise ValueError('transform() must return bytes, at most 1 MiB.')
                                parts.append(part)
                            value=b''.join(parts)
                        else: value = function(data, ctx)
                        if operation == 'transform':
                            if not isinstance(value, bytes) or len(value) > MAX_DATA:
                                raise ValueError('transform() must return bytes, at most 1 MiB.')
                            if data != value: changed.append(info['name'])
                            data = value
                        else:
                            if isinstance(value, bytes): value = {'data': value}
                            output.append(dict(id=entry['id'], name=info['name'], result=result(value),
                                               elapsed_ns=time.perf_counter_ns()-started))
                    except Exception as exc:
                        if operation != 'process': raise RuntimeError(f"{info['name']}: {exc}") from exc
                        output.append(dict(id=entry['id'], name=info['name'], error=str(exc)[:500]))
                pipe.send((True, {'data': data, 'changed': changed} if operation == 'transform' else output))
            except Exception as exc:
                pipe.send((False, str(exc)[:1000]))
    except (EOFError, BrokenPipeError):
        pass
    except BaseException as exc:
        try: pipe.send((False, str(exc)[:1000]))
        except (OSError, EOFError): pass
    finally:
        pipe.close()


class PluginWorker:
    def __init__(self, entries, timeout=2):
        self.entries = [dict(e) for e in entries if e.get('enabled')]
        self.changes = any(e.get('changes') for e in self.entries)
        self.timeout = timeout; self.failed = ''; self.closed = False
        self.requests = queue.PriorityQueue(maxsize=32); self.pending = 0; self.serial=0; self.lock = threading.Lock()
        self.process = None; self.thread = None

    def submit(self, operation, data, context, **options):
        future = Future()
        with self.lock:
            if self.closed or self.failed or len(data) > MAX_DATA or self.pending + len(data) > 8 * MAX_DATA:
                future.set_exception(RuntimeError(self.failed or 'Plugin unavailable or input exceeds its 1 MiB / queue limit.'))
                return future
            if self.thread is None:
                self.thread = threading.Thread(target=self._serve, name='Probe plugins', daemon=True)
                self.thread.start()
            try:
                self.serial+=1
                self.requests.put_nowait((1 if operation=='process' else 0,self.serial,(future, operation, bytes(data), dict(context), options)))
                self.pending += len(data)
            except queue.Full:
                future.set_exception(RuntimeError('Plugin queue full; analysis is incomplete.'))
        return future

    def _receive(self, pipe, timeout):
        deadline=time.monotonic()+timeout
        while not self.closed:
            if pipe.poll(.05):
                ok,value=pipe.recv()
                if not ok:raise RuntimeError(value)
                return value
            if time.monotonic()>=deadline:raise RuntimeError('Plugin timed out; Apply plugins again to restart it.')
        raise RuntimeError('Plugins stopped.')

    def _serve(self):
        pipe = None
        try:
            if self.closed:raise RuntimeError('Plugins stopped.')
            ctx = mp.get_context('spawn'); pipe, child = ctx.Pipe()
            self.process = ctx.Process(target=_worker, args=(child, self.entries), name='Probe plugins', daemon=True)
            self.process.start(); child.close()
            self._receive(pipe, 15)
            while not self.closed:
                try: request = self.requests.get(timeout=.05)[2]
                except queue.Empty: continue
                future, operation, data, context, options = request
                try:
                    pipe.send((operation, data, context, options))
                    # A plugin error is recoverable; a hung/dead worker is not.
                    if not pipe.poll(self.timeout): raise TimeoutError('Plugin timed out; Apply plugins again to restart it.')
                    ok, value = pipe.recv()
                    if not future.cancelled():
                        if ok: future.set_result(value)
                        else: future.set_exception(RuntimeError(value))
                except BaseException as exc:
                    if not future.done(): future.set_exception(RuntimeError(str(exc) or 'Plugin worker exited.'))
                    raise
                finally:
                    with self.lock: self.pending -= len(data)
        except BaseException as exc:
            self.failed = str(exc) or 'Plugin worker exited.'
        finally:
            if pipe: pipe.close()
            if self.process:
                if self.process.is_alive(): self.process.terminate()
                if self.process.pid is not None:self.process.join(1)
            with self.lock:
                self.closed = True
                while not self.requests.empty():
                    future, _, data, _, _ = self.requests.get_nowait()[2]; self.pending -= len(data)
                    if not future.done(): future.set_exception(RuntimeError(self.failed or 'Plugins stopped.'))

    def close(self):
        self.closed = True
        if self.process and self.process.is_alive(): self.process.terminate()
