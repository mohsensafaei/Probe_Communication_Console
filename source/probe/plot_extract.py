"""Bounded read-only extraction for live plots. No scripts or expressions."""
import math
import re
import struct
from .protocol import json_frame, json_value

KINDS=("JSON field","Delimited column","Named value","Bytes")
TYPES={"Unsigned 8":("B",1),"Unsigned 16":("H",2),"Unsigned 32":("I",4),"Signed 16":("h",2),"Signed 32":("i",4),"Float 32":("f",4),"Float 64":("d",8)}

def validate(config):
    c=dict(config)
    if c.get("kind") not in KINDS:raise ValueError("Choose a value format.")
    if c.get("framing") not in ("LF lines","JSON messages","Fixed bytes"):raise ValueError("Choose a message boundary.")
    for key,default,low,high in (("size",16,1,65536),("offset",0,0,65535),("column",1,1,1024)):
        try:c[key]=int(c.get(key,default))
        except (ValueError,TypeError):raise ValueError(f"{key} must be an integer.") from None
        if not low<=c[key]<=high:raise ValueError(f"{key} must be {low}–{high}.")
    c.setdefault("field","value");c.setdefault("separator",",");c.setdefault("type","Unsigned 16");c.setdefault("endian","Little")
    if not c["field"] or len(c["field"])>256:raise ValueError("Enter a field name or path (up to 256 characters).")
    if len(c["separator"])>16:raise ValueError("Separator is limited to 16 characters; blank means whitespace.")
    if c["type"] not in TYPES or c["endian"] not in ("Little","Big"):raise ValueError("Choose a byte type and byte order.")
    if c["kind"]=="Bytes":
        if c["framing"]!="Fixed bytes":raise ValueError("Binary values require a fixed message size.")
        if c["offset"]+TYPES[c["type"]][1]>c["size"]:raise ValueError("Value extends past the message size.")
    if c["framing"]=="JSON messages" and c["kind"]!="JSON field":raise ValueError("Use JSON message boundaries only with JSON fields.")
    return c


def extract(frame,c):
    kind=c["kind"]
    if kind=="JSON field":value=json_value(frame,c["field"])
    elif kind=="Delimited column":
        text=frame.decode("utf-8").strip();parts=text.split(c["separator"]) if c["separator"] else text.split()
        value=parts[c["column"]-1]
    elif kind=="Named value":
        match=re.search(r"(?<![\w])"+re.escape(c["field"])+r"\s*[:=]\s*([-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?)",frame.decode("utf-8"))
        if not match:raise ValueError("Named value not present.")
        value=match.group(1)
    else:
        fmt,size=TYPES[c["type"]];value=struct.unpack_from(("<" if c["endian"]=="Little" else ">")+fmt,frame,c["offset"])[0]
    if isinstance(value,(bool,dict,list)) or value is None:raise ValueError("Field must be numeric.")
    value=float(value)
    if not math.isfinite(value):raise ValueError("Field must be finite.")
    return (value,)


def frames(state,data,c):
    """Consume partial/coalesced messages independently per peer."""
    buffer=state["tail"]+data;result=[]
    if c["framing"]=="LF lines":
        parts=buffer.split(b"\n");buffer=parts.pop()
        for part in parts:
            if state["discard"]:state["discard"]=False;continue
            if len(part)<=65536:result.append(part)
            else:state["ignored"]+=1
    elif c["framing"]=="Fixed bytes":
        size=c["size"];end=len(buffer)//size*size
        result=[buffer[i:i+size] for i in range(max(0,end-300*size),end,size)];buffer=buffer[end:]
    else:
        buffer=buffer.lstrip()
        while buffer:
            try:_,_,end=json_frame(buffer)
            except (ValueError,RecursionError):break
            result.append(buffer[:end]);buffer=buffer[end:].lstrip()
    if len(buffer)>65536:
        buffer=b"";state["discard"]=c["framing"]=="LF lines";state["ignored"]+=1
    state["tail"]=buffer
    return result
