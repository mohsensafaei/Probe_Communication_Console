'Validated capture imports and replay timing. Never execute file contents.'
import csv
import hashlib
import json
import math
from pathlib import Path

from .evidence.identity import restore


def load_capture(path,max_events=2000,max_bytes=8*1024*1024):
    if Path(path).stat().st_size>24*1024*1024:raise ValueError("Capture file is too large to import (24 MiB file limit).")
    digest=hashlib.sha256()
    with open(path,'rb') as stream:
        for block in iter(lambda:stream.read(65536),b''):digest.update(block)
    origin=digest.hexdigest()[:24]
    events=[];used=0
    with open(path,"r",encoding="utf-8-sig",newline="") as handle:
        rows=csv.DictReader(handle) if str(path).lower().endswith(".csv") else (json.loads(line) for line in handle if line.strip())
        for ordinal,row in enumerate(rows,1):
            if not isinstance(row,dict):raise ValueError('Each capture row must be a JSON object.')
            if row.get("kind","data")!="data":continue
            if row.get('redacted'):raise ValueError('Sanitized diagnostic evidence cannot be imported for replay. Use the original capture.')
            direction=row.get("direction")
            if direction not in ("TX","RX"):raise ValueError("Capture rows must have TX or RX direction.")
            if "hex" not in row:raise ValueError("This export contains decoded text only. Export with Hex enabled to import or replay exact bytes.")
            data=bytes.fromhex(row["hex"])
            original=None
            if 'original_hex' in row:
                if not isinstance(row['original_hex'],str):raise ValueError('Original bytes must be hexadecimal text.')
                original=bytes.fromhex(row['original_hex'])
            timestamp=row.get("time",row.get("timestamp",0))
            try:timestamp=float(timestamp)
            except (ValueError,TypeError):
                import datetime
                timestamp=datetime.datetime.fromisoformat(timestamp).timestamp()
            if not math.isfinite(timestamp):raise ValueError("Capture timestamp must be finite.")
            used+=len(data)+(len(original) if original is not None else 0)
            if len(events)>=max_events or used>max_bytes:raise ValueError("Capture exceeds the import limit (2000 events / 8 MiB). Split the file first.")
            event=dict(kind="data",time=timestamp,direction=direction,peer=str(row.get("peer","Imported")),data=data)
            event.update({key:row[key] for key in ('session','client_peer','modified_by','plugin_error','source_time',
                          'source_monotonic_ns','plugin_elapsed_ns','display_partial','display_reason') if key in row})
            event.update(restore(row))
            if event.get('source_refs_complete') and sum(ref['end']-ref['start'] for ref in event.get('source_refs',()))!=len(data):raise ValueError('Source byte ranges do not cover the message.')
            event.setdefault('event_id',f'import-{origin}:{ordinal}')
            event.setdefault('event_version',1)
            if original is not None:event['original_hex']=original.hex()
            if 'hid' in row:
                from .hid_reports import imported_metadata
                event['hid']=imported_metadata(row['hid'],data)
            events.append(event)
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
