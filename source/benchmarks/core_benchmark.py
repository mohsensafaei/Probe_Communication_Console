"""Reproducible CPU microbenchmarks; no transport timing or hardware claims."""
import json
from pathlib import Path
import statistics
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from probe.codec import Framer, visible
from probe.comparison import compare_bytes
from probe.trace_path import find_matches

def measure(fn, repeats=5):
    values=[]
    for _ in range(repeats):
        start=time.perf_counter();fn();values.append((time.perf_counter()-start)*1000)
    return round(statistics.median(values),3)

def run():
    data=bytes(range(256))*256
    a=bytes(range(256))*1024;b=a[:130000]+b'CHANGED'+a[130007:]
    rows=[(str(i),dict(direction='TX',peer='bench',time=i,data=b'x'*4096)) for i in range(2000)]
    rows[-1][1]['data']=b'x'*4091+b'\0LAST'
    def trace():
        matches=find_matches({'data':b'x\0LAST'},rows)
        assert len(matches)==1 and matches[0]['keys']==('1999',)
    return dict(python=sys.version.split()[0],milliseconds=dict(
        display_64k=measure(lambda:visible(data)),
        fixed_frames_64k=measure(lambda:Framer('Fixed length',size=1).feed(data,0)),
        diff_equal_256k=measure(lambda:compare_bytes(a,a)),
        diff_changed_256k=measure(lambda:compare_bytes(a,b)),
        trace_2000_rows_8mib=measure(trace)))
if __name__=='__main__':print(json.dumps(run(),indent=2))
