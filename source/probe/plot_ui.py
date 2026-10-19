"""Small, bounded numeric RX plot. No acquisition/plotting dependencies."""
from collections import OrderedDict, deque
import math
import re
import tkinter as tk
from tkinter import ttk


class NumericSamples:
    """Keep partial lines and channels independent for each incoming peer."""
    def __init__(self):self.peers=OrderedDict();self.first=None

    def feed(self,peer,data):
        if peer not in self.peers:
            if len(self.peers)>=16:self.peers.popitem(last=False)
            self.peers[peer]=dict(tail=b"",discard=False,rows=deque(maxlen=300),received=0,ignored=0)
        self.peers.move_to_end(peer);state=self.peers[peer];state["received"]+=len(data)
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


class LivePlotPane(ttk.Frame):
    AUTO="Auto (first numeric peer)"
    def __init__(self,parent,app):
        super().__init__(parent,padding=12);self.app=app;self.model=NumericSamples();self.dirty=True
        self.peer=tk.StringVar(value=self.AUTO);self.status=tk.StringVar()
        ttk.Label(self,text="Live numeric plot",font=(app.ui_font,16,"bold")).pack(anchor="w")
        ttk.Label(self,text="Receives numbers or CSV, up to four channels. End each sample with LF: 12.3,45.6\\n",wraplength=680).pack(anchor="w",pady=(4,8))
        bar=ttk.Frame(self);bar.pack(fill="x")
        ttk.Label(bar,text="RX peer").pack(side="left",padx=(0,6))
        self.peer_combo=ttk.Combobox(bar,textvariable=self.peer,values=(self.AUTO,),state="readonly",width=30);self.peer_combo.pack(side="left")
        self.peer_combo.bind("<<ComboboxSelected>>",lambda e:self.render(force=True))
        ttk.Button(bar,text="Clear plot",command=self.clear).pack(side="right")
        ttk.Label(self,textvariable=self.status,wraplength=680).pack(side="bottom",anchor="w",pady=6)
        self.canvas=tk.Canvas(self,bg=app.colors["input"],highlightthickness=0,height=150);self.canvas.pack(fill="both",expand=True,pady=(8,0))
        self.canvas.bind("<Configure>",lambda e:self.render(force=True));self.render(force=True)

    def feed(self,event):
        if event.get("direction")!="RX":return
        self.model.feed(str(event.get("peer","")),event["data"]);self.dirty=True
        values=(self.AUTO,)+tuple(self.model.peers)
        if tuple(self.peer_combo.cget("values"))!=values:self.peer_combo.configure(values=values)

    def clear(self):
        self.model=NumericSamples();self.peer.set(self.AUTO);self.peer_combo.configure(values=(self.AUTO,));self.render(force=True)

    def render(self,force=False):
        connected=self.app.engine is not None and self.app.engine.ready
        connection="Connected" if connected else "Disconnected"
        if not force and (self.app.paused or not self.dirty and getattr(self,"connection",None)==connection):return
        self.connection=connection;self.dirty=False;cv=self.canvas;c=self.app.colors;cv.delete("all")
        peer=self.model.first if self.peer.get()==self.AUTO else self.peer.get()
        state=self.model.peers.get(peer);rows=list(state["rows"]) if state else []
        w=max(120,cv.winfo_width());h=max(100,cv.winfo_height())
        if not rows:
            received=sum(state["received"] for state in self.model.peers.values())
            note="Waiting for numeric RX samples." if not received else f"Received {received} bytes; no complete numeric sample for this peer."
            cv.create_text(18,25,text=note,anchor="w",fill=c["text"],font=(self.app.ui_font,12,"bold"),width=max(100,w-36))
            cv.create_text(18,68,text="Example: send 1,2 then LF; send 2,3 then LF. JSON, binary frames and TX-only data are not plotted.",anchor="nw",fill=c["muted"],font=(self.app.ui_font,11),width=max(100,w-36))
            self.status.set(f"{connection} · Numeric RX only · last 300 samples per peer (up to 16 peers).")
            return
        lo=min(min(row) for row in rows);hi=max(max(row) for row in rows)
        if hi==lo:lo-=.5;hi+=.5
        # Avoid overflow for otherwise finite values near float's endpoints.
        scale=max(abs(lo),abs(hi),1);low,high=lo/scale,hi/scale
        if high==low:high=low+1
        for j in range(4):
            y=15+(h-40)*j/3;value=hi*(1-j/3)+lo*(j/3)
            cv.create_line(55,y,w-15,y,fill=c["border"])
            cv.create_text(5,y,text=f"{value:.3g}",anchor="w",fill=c["muted"],font=(self.app.mono,8))
        colors=(c["accent"],c["blue"],c["red"],"#c7a0fa")
        for channel,color in enumerate(colors):
            points=[]
            for index,row in enumerate(rows):
                if channel<len(row):points.extend((55+(w-75)*index/max(1,len(rows)-1),15+(h-40)*(high-row[channel]/scale)/(high-low)))
            if len(points)>=4:cv.create_line(*points,fill=color,width=2,tags=("curve",))
            elif points:
                x,y=points;cv.create_oval(x-3,y-3,x+3,y+3,fill=color,outline=color,tags=("curve",))
        values=" · ".join(f"CH{i+1}={value:g}" for i,value in enumerate(rows[-1]))
        self.status.set(f"{connection} · {peer} · {len(rows)} samples · {values}")
