"""Optional real socket benchmark; never a hard real-time certification.
Run: python benchmarks/transport_benchmark.py --output benchmark.json
No physical serial hardware is opened. No GUI is instantiated.
"""
import argparse
import contextlib
import hashlib
import json
import os
from pathlib import Path
import platform
import socket
import struct
import sys
import tempfile
import threading
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from probe.diagnostics import session, wait_for
from probe.scenario import Step


def payload(size,frame=32):
    return b''.join(struct.pack('!Q',i)+bytes((j+i)%256 for j in range(frame-8)) for i in range(size//frame))


def stats(values):
    values=sorted(values)
    def pct(p):return values[round((len(values)-1)*p)]
    return dict(n=len(values),min=min(values),median=pct(.5),p95=pct(.95),p99=pct(.99),max=max(values),mean=sum(values)/len(values))


def capture_hash(path,direction):
    digest=hashlib.sha256();count=0
    with open(path,encoding='utf-8') as f:
        for line in f:
            row=json.loads(line)
            if row.get('kind')=='data' and row.get('direction')==direction:
                data=bytes.fromhex(row['hex']);count+=len(data);digest.update(data)
    return count,digest.hexdigest()


def receive_test(size,chunk,record):
    wire=payload(size);expected=hashlib.sha256(wire).hexdigest();digest=hashlib.sha256();done=threading.Event();errors=[];count=0;end=0
    with tempfile.TemporaryDirectory() as temp,session('TCP Server') as (engine,events,ready):
        def observe(event):
            nonlocal count,end
            if event.get('direction')=='RX':
                count+=len(event['data']);digest.update(event['data'])
                if count>=len(wire):end=time.perf_counter_ns();done.set()
        # Engine.event notifies observers before writing the same event to capture.
        engine.observers.add(observe)
        path=Path(temp)/'rx.jsonl'
        if record:engine.record(path)
        with socket.create_connection(ready['address'][:2],timeout=60) as client:
            client.setsockopt(socket.IPPROTO_TCP,socket.TCP_NODELAY,1)
            started=time.perf_counter_ns()
            for offset in range(0,len(wire),chunk):client.sendall(wire[offset:offset+chunk])
            if not done.wait(60):raise RuntimeError('RX timed out')
            # Queue a barrier on the engine loop after the last event/capture write.
            barrier=threading.Event();engine.loop.call_soon_threadsafe(barrier.set)
            if not barrier.wait(10):raise RuntimeError('Capture barrier timed out')
        if record:engine.record()
        drained=time.perf_counter_ns()
        verified=count==len(wire) and digest.hexdigest()==expected
        recorded=capture_hash(path,'RX') if record else None
        return dict(test='TCP receive',record=record,bytes_expected=len(wire),bytes_received=count,send_chunk=chunk,
                    stream_exact=verified,capture_exact=recorded==(len(wire),expected) if record else None,
                    elapsed_s=(end-started)/1e9,capture_drained_elapsed_s=(drained-started)/1e9,MiB_s=len(wire)/((end-started)/1e9)/1048576)


def proxy_test():
    wire=payload(8*1024*1024,4096);expected=hashlib.sha256(wire).hexdigest();errors=[]
    with socket.socket() as listener,tempfile.TemporaryDirectory() as temp:
        listener.bind(('127.0.0.1',0));listener.listen();listener.settimeout(60)
        def echo():
            try:
                with listener.accept()[0] as peer:
                    peer.settimeout(60)
                    while data:=peer.recv(65536):peer.sendall(data)
            except Exception as exc:errors.append(str(exc))
        worker=threading.Thread(target=echo,daemon=True);worker.start()
        with session('TCP Proxy',port=listener.getsockname()[1]) as (engine,events,ready):
            path=Path(temp)/'proxy.jsonl';engine.record(path)
            with socket.create_connection(ready['address'][:2],timeout=60) as client:
                received=bytearray()
                def read():
                    try:
                        while len(received)<len(wire):
                            data=client.recv(65536)
                            if not data:break
                            received.extend(data)
                    except Exception as exc:errors.append(str(exc))
                reader=threading.Thread(target=read,daemon=True);reader.start();started=time.perf_counter_ns()
                client.sendall(wire);reader.join(60);elapsed=(time.perf_counter_ns()-started)/1e9
                if reader.is_alive():raise RuntimeError('Proxy read timeout')
            barrier=threading.Event();engine.loop.call_soon_threadsafe(barrier.set)
            if not barrier.wait(10):raise RuntimeError('Proxy capture timeout')
            engine.record();tx=capture_hash(path,'TX');rx=capture_hash(path,'RX')
        worker.join(5)
    return dict(test='TCP proxy echo',record=True,bytes_each_direction=len(wire),stream_exact=bytes(received)==wire,
                capture_tx_exact=tx==(len(wire),expected),capture_rx_exact=rx==(len(wire),expected),elapsed_s=elapsed,
                roundtrip_payload_MiB_s=len(wire)/elapsed/1048576,errors=errors)


def process_load(stop,ready):
    ready.set()
    n=1
    while not stop.is_set():n=(n*1664525+1013904223)&0xffffffff


def timing_test(record=False,load=False,count=1000):
    wire=bytes(range(32));sent=[];arrivals=[];received=bytearray();stop=threading.Event();errors=[]
    with socket.socket() as listener,tempfile.TemporaryDirectory() as temp:
        listener.bind(('127.0.0.1',0));listener.listen();listener.settimeout(90)
        def receive():
            try:
                with listener.accept()[0] as peer:
                    peer.settimeout(90)
                    while len(received)<len(wire)*count:
                        data=peer.recv(65536);now=time.perf_counter_ns()
                        if not data:break
                        before=len(received)//len(wire);received.extend(data)
                        arrivals.extend([now]*(len(received)//len(wire)-before))
                    # Keep the peer open until the sequence reports its final completion.
                    stop.wait(90)
            except Exception as exc:errors.append(str(exc))
        def busy():
            n=1
            while not stop.is_set():n=(n*1664525+1013904223)&0xffffffff
        reader=threading.Thread(target=receive,daemon=True);reader.start();loader=None
        with session('TCP Client',port=listener.getsockname()[1]) as (engine,events,_):
            engine.observers.add(lambda e:sent.append(time.perf_counter_ns()) if e.get('direction')=='TX' else None)
            if record:engine.record(Path(temp)/'timing.jsonl')
            process_stop=None
            if load=='process':
                import multiprocessing
                ctx=multiprocessing.get_context('spawn');process_stop=ctx.Event();process_ready=ctx.Event()
                loader=ctx.Process(target=process_load,args=(process_stop,process_ready),daemon=True);loader.start()
                if not process_ready.wait(10):process_stop.set();raise RuntimeError('CPU worker did not start.')
            elif load:loader=threading.Thread(target=busy,daemon=True);loader.start()
            try:
                engine.start_scenario((Step('1 ms',wire,delay_ms=1,repeat=count),))
                wait_for(lambda:any(e.get('kind')=='scenario' and e.get('state') in ('complete','failed') for e in events),events,90)
                stop.set();reader.join(5)
            finally:
                stop.set()
                if process_stop:process_stop.set()
                if loader:loader.join(2)
            success=any(e.get('kind')=='scenario' and e.get('state')=='complete' for e in events)
        reader.join(5)
        captured=capture_hash(Path(temp)/'timing.jsonl','TX') if record else None
    if len(sent)<2:raise RuntimeError('Too few TX samples')
    intervals=[b-a for a,b in zip(sent,sent[1:])];errors_ns=[x-1000000 for x in intervals]
    return dict(test='Sequence 1 ms',record=record,python_cpu_contention=bool(load),cpu_contention_kind='separate process' if load=='process' else 'same-process Python thread' if load else 'none',messages_expected=count,messages_tx=len(sent),messages_rx=len(arrivals),
                stream_exact=bytes(received)==wire*count,scenario_complete=success,errors=errors,
                capture_exact=captured==(count*len(wire),hashlib.sha256(wire*count).hexdigest()) if record else None,
                scheduler_summary=next((e.get('timing') for e in reversed(events) if e.get('state')=='complete'),None),
                tx_interval_us=stats([x/1000 for x in intervals]),tx_interval_error_us=stats([x/1000 for x in errors_ns]),
                max_absolute_interval_error_us=max(abs(x) for x in errors_ns)/1000,
                accumulated_drift_ms=(sent[-1]-sent[0]-(len(sent)-1)*1000000)/1e6,
                rx_observed_interval_us=stats([(b-a)/1000 for a,b in zip(arrivals,arrivals[1:])]),
                note='TX timestamp is an application observer after writer.write; RX is application full-frame availability. Neither is a wire timestamp.')


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,default=Path('transport-benchmark.json'));args=parser.parse_args()
    result=dict(platform=platform.platform(),python=sys.version,processor=platform.processor(),cpu_count=os.cpu_count(),source_commit=os.getenv('GITHUB_SHA','local working tree'),
                scope='Real TCP localhost sockets, Probe Engine and actual Sequence runner. No Tk UI. No physical serial hardware. Host scheduling, not hard real-time certification.',
                perf_counter_resolution_s=time.get_clock_info('perf_counter').resolution,results=[])
    for operation in (lambda:receive_test(16*1048576,65536,False),lambda:receive_test(16*1048576,65536,True),
                      lambda:receive_test(100000*32,32,True),proxy_test,
                      lambda:timing_test(False,False),lambda:timing_test(True,False),lambda:timing_test(True,True,500),lambda:timing_test(True,'process',500)):
        row=operation();result['results'].append(row);print(json.dumps(row),flush=True)
        args.output.write_text(json.dumps(result,indent=2),encoding='utf-8')
    result['serial_115200_8N1']=dict(physical_test=False,reason='No physical UART/USB adapter connected; loop:// and PTYs do not enforce wire baud rate.',
        bits_per_byte=10,max_bytes_s=11520,byte_time_us=10/115200*1e6,
        sizes=[dict(bytes=n,min_wire_time_ms=n*10/115200*1000,max_messages_s=115200/(n*10),can_sustain_1000_messages_s=n*1000<=11520) for n in (1,8,11,12,16,32,64,128,256)])
    result['data_checks_passed']=all(row.get('stream_exact',False) and row.get('capture_exact') is not False and row.get('capture_tx_exact') is not False and row.get('capture_rx_exact') is not False and not row.get('errors') and row.get('scenario_complete',True) for row in result['results'])
    args.output.write_text(json.dumps(result,indent=2),encoding='utf-8')
    if not result['data_checks_passed']:raise SystemExit('Data integrity benchmark failed')

if __name__=='__main__':main()
