import concurrent.futures
import hashlib
import json
from pathlib import Path
import socket
import sys
import time

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from probe.diagnostics import received, session, wait_for
from probe.evidence.case import build_preview


def run():
    data=b'{"temperature":21,"padding":"'+b'x'*32000+b'"}'
    rows=[dict(event_id=f'bench:{i}',time=i,direction='RX',peer='sensor',data=data) for i in range(64)]
    stream=bytes(range(256))*16384
    with session('TCP Server') as (engine,events,_):
        address=engine.server.sockets[0].getsockname()[:2]
        with socket.create_connection(address,timeout=5) as client,concurrent.futures.ThreadPoolExecutor(1) as worker:
            start=time.perf_counter();future=worker.submit(build_preview,[dict(name='Sensor',rows=rows)])
            client.sendall(stream)
            wait_for(lambda:engine.rx==len(stream),events,timeout=15)
            captured=received(events)
            assert hashlib.sha256(captured).digest()==hashlib.sha256(stream).digest()
            case=future.result(timeout=30)
            assert len(case['events'])==64
            return dict(tcp_bytes=len(stream),case_payload_bytes=sum(len(row['data']) for row in rows),
                        case_messages=len(case['events']),seconds=round(time.perf_counter()-start,3),
                        byte_exact=True,note='TCP loopback concurrent with a process-based preview; not physical timing evidence.')


if __name__=='__main__':print(json.dumps(run(),indent=2))
