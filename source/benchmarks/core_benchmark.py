"""Reproducible CPU microbenchmarks; no transport timing or hardware claims."""
import json
from pathlib import Path
import statistics
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from probe.codec import Framer, visible
from probe.comparison import compare_bytes

def measure(fn, repeats=5):
    values=[]
    for _ in range(repeats):
        start=time.perf_counter();fn();values.append((time.perf_counter()-start)*1000)
    return round(statistics.median(values),3)

def run():
    data=bytes(range(256))*256
    a=bytes(range(256))*1024;b=a[:130000]+b'CHANGED'+a[130007:]
    return dict(python=sys.version.split()[0],milliseconds=dict(
        display_64k=measure(lambda:visible(data)),
        fixed_frames_64k=measure(lambda:Framer('Fixed length',size=1).feed(data,0)),
        diff_equal_256k=measure(lambda:compare_bytes(a,a)),
        diff_changed_256k=measure(lambda:compare_bytes(a,b))))
if __name__=='__main__':print(json.dumps(run(),indent=2))
