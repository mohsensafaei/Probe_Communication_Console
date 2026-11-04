"""Native Tk CPU/Python-memory measurements for one, two and four probes."""
import gc
import json
from pathlib import Path
import statistics
import sys
import tempfile
import time
import tracemalloc
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from probe.app import Probe


def run(count):
    gc.collect();tracemalloc.start()
    with tempfile.TemporaryDirectory() as directory,patch('probe.app.data_directory',return_value=Path(directory)):
        start=time.perf_counter();window=Probe()
        try:
            for _ in range(count-1):window.new_probe()
            window.update();creation=(time.perf_counter()-start)*1000
            samples=[];insertions=[];wire=bytes(range(256))*256
            for probe in window.probes:
                probe.vars['framing'].set('Fixed length');probe.vars['frame_size'].set('1')
            for _ in range(3):
                for probe in window.probes:probe.clear()
                calls=[0]*count;original=[]
                for i,probe in enumerate(window.probes):
                    original.append(probe.table.insert)
                    def insert(*a,index=i,**kw):
                        calls[index]+=1;return original[index](*a,**kw)
                    probe.table.insert=insert
                start=time.perf_counter()
                for probe in window.probes:
                    probe.emit(dict(kind='data',time=time.time(),direction='RX',peer='bench',data=wire))
                    probe.poll()
                window.update_idletasks()
                samples.append((time.perf_counter()-start)*1000);insertions.append(calls)
                for i,probe in enumerate(window.probes):
                    probe.table.insert=original[i]
                    assert b''.join(e['data'] for e in probe.events.values())==wire[-2000:]
                assert calls==[0]*(count-1)+[2000],calls
            used,peak=tracemalloc.get_traced_memory()
            return dict(probes=count,create_ms=round(creation,2),median_batch_ms=round(statistics.median(samples),2),
                        python_retained_mib=round(used/1048576,2),python_peak_mib=round(peak/1048576,2),
                        table_insertions=insertions)
        finally:window.close();tracemalloc.stop()


if __name__=='__main__':
    print(json.dumps(dict(python=sys.version.split()[0],platform=sys.platform,
        note='64 KiB per probe, one-byte framing, 2000 retained rows each; tracemalloc enabled; Python allocations only, not RSS or wire timing',
        samples=[run(n) for n in (1,2,4)]),indent=2))
