'Bounded numeric acquisition model; independent of Tk and transport I/O.'
import math
import re
from collections import OrderedDict, deque

from .plot_extract import extract, frames, validate


class NumericSamples:
    """Keep partial lines and channels independent for each incoming peer."""
    def __init__(self,config=None):self.peers=OrderedDict();self.first=None;self.config=validate(config) if config else None

    def feed(self,peer,data):
        if peer not in self.peers:
            if len(self.peers)>=16:self.peers.popitem(last=False)
            self.peers[peer]=dict(tail=b"",discard=False,rows=deque(maxlen=300),received=0,ignored=0)
        self.peers.move_to_end(peer);state=self.peers[peer];state["received"]+=len(data)
        if self.config:
            for frame in frames(state,data,self.config):
                try:
                    state["rows"].append(extract(frame,self.config))
                    if self.first not in self.peers or self.first is None:self.first=peer
                except (ValueError,TypeError,IndexError,OverflowError):state["ignored"]+=1
            return
        parts=(state["tail"]+data).split(b"\n");state["tail"]=parts.pop()
        for line in parts:
            if state["discard"]:state["discard"]=False;continue
            try:
                if len(line)>1024:raise ValueError
                values=[float(value) for value in re.split(rb"[,;\s]+",line.strip()) if value]
                if not values or len(values)>4 or not all(math.isfinite(value) for value in values):raise ValueError
                state["rows"].append(tuple(values))
                if self.first not in self.peers or self.first is None:self.first=peer
            except (ValueError,OverflowError):state["ignored"]+=1
        if len(state["tail"])>1024:state["tail"]=b"";state["discard"]=True
