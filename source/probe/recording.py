"""Bounded asynchronous capture. Serialization and disk I/O live in a process."""
import contextlib
import json
import multiprocessing as mp
import queue
import threading
import time


def _writer(commands,replies,errors,pending):
    handles={'capture':None,'raw':None};failed=False;last_flush=time.monotonic()
    def close_all():
        for key,f in handles.items():
            if f:
                try:f.close()
                except OSError as exc:errors.send(str(exc))
                handles[key]=None
    try:
        while True:
            try:kind,value,cost=commands.get(timeout=.05)
            except queue.Empty:
                for f in handles.values():
                    if f:f.flush()
                last_flush=time.monotonic();continue
            if kind=='data':
                try:
                    if not failed:
                        if handles['capture']:
                            row=dict(value)
                            if 'data' in row:row['hex']=row.pop('data').hex().upper()
                            handles['capture'].write(json.dumps(row,ensure_ascii=True)+'\n')
                        if handles['raw'] and value.get('kind')=='data' and value.get('direction')=='RX':handles['raw'].write(value['data'])
                        if time.monotonic()-last_flush>=.05:
                            for f in handles.values():
                                if f:f.flush()
                            last_flush=time.monotonic()
                except (OSError,ValueError) as exc:
                    failed=True;close_all();errors.send(str(exc))
                finally:
                    with pending.get_lock():pending.value-=cost
            else:
                try:
                    stream,path=value
                    if kind=='shutdown':close_all();replies.put(None);break
                    # Preserve the previous stream if opening its replacement fails.
                    fresh=open(path,'ab' if stream=='raw' else 'a',**({} if stream=='raw' else {'encoding':'utf-8'})) if path else None
                    old=handles[stream]
                    if old:old.close()
                    handles[stream]=fresh;failed=False;replies.put(None)
                except OSError as exc:replies.put(str(exc))
    except Exception as exc:
        with contextlib.suppress(Exception):errors.send(str(exc))
    finally:
        close_all()
        with contextlib.suppress(Exception):errors.send(None)
        errors.close()


class CaptureWriter:
    MAX_BYTES=64*1024*1024
    def __init__(self,on_error,max_bytes=MAX_BYTES):
        ctx=mp.get_context('spawn');self.commands=ctx.Queue(maxsize=4096);self.replies=ctx.Queue()
        self.pending=ctx.Value('q',0);self.max_bytes=max_bytes;self.on_error=on_error
        self.lock=threading.Lock();self.control_lock=threading.Lock();self.failed=False;self.closing=False
        reader,writer=ctx.Pipe(duplex=False)
        self.process=ctx.Process(target=_writer,args=(self.commands,self.replies,writer,self.pending),name='Probe capture',daemon=True)
        self.process.start();writer.close();self.reader=reader
        self.monitor=threading.Thread(target=self._watch,name='Probe capture status',daemon=True);self.monitor.start()

    def _watch(self):
        try:
            while True:
                message=self.reader.recv()
                if message is None:break
                self.fail(message)
        except (EOFError,OSError):
            if not self.closing:self.fail('Capture worker exited unexpectedly.')
        finally:self.reader.close()

    def fail(self,message):
        if not self.failed:
            self.failed=True;self.on_error(message)

    def enqueue(self,event):
        if self.failed:return
        if not self.process.is_alive():self.fail('Capture worker is not running.');return
        cost=512;stack=list(event.values())
        while stack:
            value=stack.pop()
            if isinstance(value,bytes):cost+=len(value)
            elif isinstance(value,str):cost+=len(value)*4
            elif isinstance(value,dict):cost+=128*len(value);stack.extend(value.values())
            elif isinstance(value,(list,tuple)):cost+=64+8*len(value);stack.extend(value)
            else:cost+=32
        with self.lock:
            with self.pending.get_lock():
                if self.pending.value+cost>self.max_bytes:
                    self.fail('Capture queue exceeded its byte limit; the recording is incomplete.');return
                self.pending.value+=cost
            try:self.commands.put_nowait(('data',dict(event),cost))
            except queue.Full:
                with self.pending.get_lock():self.pending.value-=cost
                self.fail('Capture queue is full; the recording is incomplete.')

    def control(self,stream,path=None):
        with self.control_lock:
            if not self.process.is_alive():raise OSError('Capture worker is not running.')
            try:self.commands.put(('stream',(stream,str(path) if path else None),0),timeout=10)
            except queue.Full:
                self.fail('Capture queue did not drain; recording is incomplete.')
                raise OSError('Capture queue did not drain.') from None
            try:error=self.replies.get(timeout=10)
            except queue.Empty:
                self.fail('Capture flush timed out; the recording may be incomplete.')
                raise OSError('Capture flush timed out.') from None
            if error:raise OSError(error)
            self.failed=False

    def close(self):
        self.closing=True
        try:
            with self.control_lock:
                self.commands.put(('shutdown',(None,None),0),timeout=5)
                self.replies.get(timeout=5)
        except (queue.Empty,queue.Full,OSError):self.fail('Capture shutdown timed out; the recording may be incomplete.')
        finally:
            self.process.join(5)
            if self.process.is_alive():self.fail('Capture worker failed to stop.');self.process.terminate();self.process.join(2)
            self.commands.cancel_join_thread();self.commands.close();self.replies.close();self.monitor.join(1)
