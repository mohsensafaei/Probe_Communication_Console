"""Measure reusable worker overhead, without transport timing claims."""
import json
from pathlib import Path
import statistics
import sys
import tempfile
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from probe.plugins import PluginWorker


def run():
    with tempfile.TemporaryDirectory() as directory:
        path=Path(directory)/'main.py'
        path.write_text('def process(data, context):return {"values":{"bytes":len(data)}}\ndef transform(data, context):return data\n')
        worker=PluginWorker([dict(id='bench',path=str(path),enabled=True,changes=True)])
        context=dict(direction='TX',peer='bench',session='bench');payload=b'x'*1024
        try:
            worker.submit('ready',b'',context).result(20)
            timings=[]
            for _ in range(200):
                start=time.perf_counter_ns();value=worker.submit('transform',payload,context).result(5)
                timings.append((time.perf_counter_ns()-start)/1e6);assert value['data']==payload
            start=time.perf_counter()
            for _ in range(40):
                futures=[worker.submit('process',payload,context) for _ in range(16)]
                for f in futures:assert f.result(5)[0]['result']['values']['bytes']==1024
            elapsed=time.perf_counter()-start
            return dict(warm_transform_median_ms=round(statistics.median(timings),3),
                        warm_transform_p99_ms=round(sorted(timings)[197],3),
                        analysis_per_second=round(640/elapsed),
                        note='1 KiB, trivial plugin, one reused process; excludes startup and is not a real-time guarantee')
        finally:
            worker.close()
            if worker.thread:worker.thread.join(3)


if __name__=='__main__':print(json.dumps(run(),indent=2))
