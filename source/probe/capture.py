"""Validated capture imports and replay timing. Never execute file contents."""
import csv
import json
import math
from pathlib import Path

def load_capture(path,max_events=2000,max_bytes=8*1024*1024):
    if Path(path).stat().st_size>24*1024*1024:raise ValueError("Capture file is too large to import (24 MiB file limit).")
    events=[];used=0
    with open(path,"r",encoding="utf-8-sig",newline="") as handle:
        rows=csv.DictReader(handle) if str(path).lower().endswith(".csv") else (json.loads(line) for line in handle if line.strip())
        for row in rows:
            if row.get("kind","data")!="data":continue
            direction=row.get("direction")
            if direction not in ("TX","RX"):raise ValueError("Capture rows must have TX or RX direction.")
            if "hex" not in row:raise ValueError("This export contains decoded text only. Export with Hex enabled to import or replay exact bytes.")
            data=bytes.fromhex(row["hex"])
            timestamp=row.get("time",row.get("timestamp",0))
            try:timestamp=float(timestamp)
            except (ValueError,TypeError):
                import datetime
                timestamp=datetime.datetime.fromisoformat(timestamp).timestamp()
            if not math.isfinite(timestamp):raise ValueError("Capture timestamp must be finite.")
            used+=len(data)
            if len(events)>=max_events or used>max_bytes:raise ValueError("Capture exceeds the import limit (2000 events / 8 MiB). Split the file first.")
            events.append(dict(kind="data",time=timestamp,direction=direction,peer=str(row.get("peer","Imported")),data=data))
    return events

def replay_plan(events,speed=1.0,direction="TX"):
    if not math.isfinite(speed) or not .1<=speed<=10:raise ValueError("Replay speed must be 0.1–10×.")
    selected=[e for e in events if e["direction"]==direction]
    if not selected:return []
    first=selected[0]["time"]
    previous=0.0;plan=[]
    for event in selected:
        offset=max(previous,(event["time"]-first)/speed)
        plan.append((offset,event["data"]));previous=offset
    return plan
