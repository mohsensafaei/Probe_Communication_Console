"""Native Tk display benchmark. Requires a display; accepts a baseline source root.

Run the same script/interpreter/display against both checkouts. Measures one
64 KiB read framed into one-byte rows, including Tk idle layout/paint work.
It does not measure transport throughput, scheduler precision or physical COM.
"""
import json
from pathlib import Path
import statistics
import sys
import tempfile
import time
from unittest.mock import patch

source = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path(__file__).resolve().parents[1]
sys.path.insert(0, str(source))
from probe.app import Probe


def run():
    elapsed = []
    insertions = []
    wire = bytes(range(256)) * 256
    with tempfile.TemporaryDirectory() as directory, patch("probe.app.data_directory", return_value=Path(directory)):
        window = Probe()
        app = window.current_probe if hasattr(window,"current_probe") else window
        try:
            app.vars["framing"].set("Fixed length")
            app.vars["frame_size"].set("1")
            app.update()
            for _ in range(3):
                app.clear()
                app.emit(dict(kind="data", time=time.time(), direction="RX", peer="benchmark", data=wire))
                count = 0
                original_insert = app.table.insert
                def counted_insert(*args, **kwargs):
                    nonlocal count
                    count += 1
                    return original_insert(*args, **kwargs)
                # Count calls without Mock's per-call recording/allocation cost.
                with patch.object(app.table, "insert", counted_insert), patch.object(app, "after"):
                    start = time.perf_counter()
                    app.poll()
                    app.update_idletasks()
                    elapsed.append((time.perf_counter() - start) * 1000)
                    insertions.append(count)
                assert len(app.events) == len(app.table.get_children()) == 2000
                assert b"".join(app.events[key]["data"] for key in app.order) == wire[-2000:]
            return dict(python=sys.version.split()[0], tk=app.tk.call("info", "patchlevel"),
                        workload="64 KiB -> 65,536 one-byte display frames; 2,000 retained",
                        milliseconds=[round(v, 3) for v in elapsed],
                        median_ms=round(statistics.median(elapsed), 3), table_insertions=insertions)
        finally:
            window.close()


if __name__ == "__main__":
    print(json.dumps(run(), indent=2))
