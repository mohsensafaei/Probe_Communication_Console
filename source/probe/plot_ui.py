"""Small, bounded numeric RX plot. No acquisition/plotting dependencies."""
from collections import OrderedDict, deque
import math
import json
from .plot_extract import KINDS, TYPES, validate, extract, frames
from .protocol import json_frame
import re
import tkinter as tk
from tkinter import ttk


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


class LivePlotPane(ttk.Frame):
    AUTO="Auto (first numeric peer)"
    def __init__(self,parent,app):
        super().__init__(parent,padding=12);self.app=app;self.model=NumericSamples();self.dirty=True
        self.mode=tk.StringVar(value="Auto");self.config=None
        try:
            saved=json.loads(app.vars["plot_config"].get())
            if saved:self.config=validate(saved)
            if self.config and app.vars["plot_mode"].get()=="Custom":
                self.mode.set("Custom");self.model=NumericSamples(self.config)
        except (KeyError,ValueError,TypeError):pass
        self.peer=tk.StringVar(value=self.AUTO);self.status=tk.StringVar()
        ttk.Label(self,text="Live numeric plot",font=(app.ui_font,16,"bold")).pack(anchor="w")
        self.description=tk.StringVar(value="Auto: numbers / CSV, up to four channels. End each sample with LF: 12.3,45.6\\n")
        ttk.Label(self,textvariable=self.description,wraplength=760).pack(anchor="w",pady=(4,8))
        modes=ttk.Frame(self);modes.pack(fill="x",pady=(0,6))
        ttk.Label(modes,text="Value source").pack(side="left",padx=(0,8))
        selector=ttk.Combobox(modes,textvariable=self.mode,values=("Auto","Custom"),state="readonly",width=10);selector.pack(side="left")
        selector.bind("<<ComboboxSelected>>",lambda e:self.change_mode())
        ttk.Button(modes,text="Configure custom…",command=self.configure_custom).pack(side="left",padx=8)
        bar=ttk.Frame(self);bar.pack(fill="x")
        ttk.Label(bar,text="RX peer").pack(side="left",padx=(0,6))
        self.peer_combo=ttk.Combobox(bar,textvariable=self.peer,values=(self.AUTO,),state="readonly",width=30);self.peer_combo.pack(side="left")
        self.peer_combo.bind("<<ComboboxSelected>>",lambda e:self.render(force=True))
        ttk.Button(bar,text="Clear plot",command=self.clear).pack(side="right")
        ttk.Label(self,textvariable=self.status,wraplength=680).pack(side="bottom",anchor="w",pady=6)
        self.canvas=tk.Canvas(self,bg=app.colors["input"],highlightthickness=0,height=150);self.canvas.pack(fill="both",expand=True,pady=(8,0))
        self.canvas.bind("<Configure>",lambda e:self.render(force=True));self.describe();self.render(force=True)

    def change_mode(self):
        if self.mode.get()=="Custom" and self.config is None:
            self.configure_custom()
            return
        self.clear()
        self.describe();self.save_config()

    def save_config(self):
        self.app.vars["plot_mode"].set(self.mode.get())
        self.app.vars["plot_config"].set(json.dumps(self.config or {}))
        self.app.save_settings()

    def describe(self):
        if self.mode.get()=="Auto":self.description.set("Auto: numbers / CSV, up to four channels. Each sample ends with LF.")
        elif self.config:
            c=self.config
            value=c["field"] if c["kind"] in ("JSON field","Named value") else f"column {c['column']}" if c["kind"]=="Delimited column" else f"offset {c['offset']} · {c['type']} · {c['endian']} endian"
            self.description.set(f"Custom: {c['kind']} · {value} · {c['framing']}. Applies to new RX; changing settings clears only the plot.")

    def configure_custom(self):
        win=tk.Toplevel(self);win.title("Probe · Plot one parameter");win.transient(self.winfo_toplevel());win.configure(bg=self.app.colors["panel"])
        win.geometry("620x530");win.minsize(600,500)
        body=ttk.Frame(win,padding=18);body.pack(fill="both",expand=True)
        ttk.Label(body,text="Choose the value to plot",font=(self.app.ui_font,17,"bold")).pack(anchor="w")
        ttk.Label(body,text="One value per message. Original traffic stays unchanged.").pack(anchor="w",pady=6)
        defaults=dict(kind="JSON field",field="value",column=1,separator=",",offset=0,type="Unsigned 16",endian="Little",size=16,framing="JSON messages")
        defaults.update(self.config or {});v={key:tk.StringVar(value=str(value)) for key,value in defaults.items()}
        feedback=tk.StringVar();form=ttk.Frame(body);form.pack(fill="x")
        def add(label,key,values=None):
            box=ttk.Frame(form);box.pack(fill="x",pady=4)
            ttk.Label(box,text=label,width=24).pack(side="left")
            widget=ttk.Combobox(box,textvariable=v[key],values=values,state="readonly") if values else ttk.Entry(box,textvariable=v[key])
            widget.pack(side="left",fill="x",expand=True);return widget
        def layout(event=None):
            for child in form.winfo_children():child.destroy()
            kind=add("Message format","kind",KINDS);kind.bind("<<ComboboxSelected>>",changed)
            if v["kind"].get()=="JSON field":
                field=add("JSON path","field")
                paths=[]
                for key in reversed(self.app.order):
                    event=self.app.events.get(key,{})
                    if event.get("direction")!="RX":continue
                    try:paths=[f.selector for f in json_frame(event["data"])[1] if f.kind=="JSON"];break
                    except (ValueError,RecursionError):pass
                if paths:
                    picker=ttk.Combobox(form,values=paths,state="readonly");picker.pack(fill="x",pady=4)
                    picker.bind("<<ComboboxSelected>>",lambda e:v["field"].set(picker.get()))
                help_text="Example: data.temperature or /data/temperature. The list offers fields from the latest complete RX JSON."
            elif v["kind"].get()=="Delimited column":
                add("Column (first is 1)","column");add("Separator (blank = space)","separator");help_text="Example: 12.5,3.3,42 with column 2 plots 3.3."
            elif v["kind"].get()=="Named value":
                add("Parameter name","field");help_text="Example: temp=25.4 voltage=3.3 with name temp plots 25.4. Also accepts name: value."
            else:
                add("Byte offset (starts at 0)","offset");add("Numeric type","type",tuple(TYPES));add("Byte order","endian",("Little","Big"));help_text="Fixed-size binary frames: choose the start offset and numeric representation."
            ttk.Label(form,text=help_text,wraplength=550).pack(anchor="w",pady=8)
            framing=add("Message boundary","framing",("JSON messages","LF lines","Fixed bytes") if v["kind"].get()=="JSON field" else ("Fixed bytes",) if v["kind"].get()=="Bytes" else ("LF lines","Fixed bytes"))
            framing.bind("<<ComboboxSelected>>",layout)
            if v["framing"].get()=="Fixed bytes":add("Bytes per message","size")
        def changed(event=None):
            v["framing"].set("JSON messages" if v["kind"].get()=="JSON field" else "Fixed bytes" if v["kind"].get()=="Bytes" else "LF lines")
            layout()
        def apply():
            try:self.config=validate({k:value.get() for k,value in v.items()})
            except ValueError as exc:feedback.set(str(exc));return
            self.mode.set("Custom");self.clear();self.describe();self.save_config();win.destroy()
        def cancel():
            if self.config is None:self.mode.set("Auto")
            win.destroy()
        actions=ttk.Frame(body);actions.pack(side="bottom",fill="x",pady=8)
        ttk.Button(actions,text="Apply",style="Accent.TButton",command=apply).pack(side="right")
        ttk.Button(actions,text="Cancel",command=cancel).pack(side="right",padx=8)
        ttk.Label(body,textvariable=feedback,wraplength=550).pack(side="bottom",anchor="w")
        layout();win.protocol("WM_DELETE_WINDOW",cancel);win.bind("<Escape>",lambda e:cancel());win.grab_set()
        self.custom_window=win;self.custom_variables=v;self.apply_custom=apply
        return win

    def feed(self,event):
        if event.get("direction")!="RX":return
        self.model.feed(str(event.get("peer","")),event["data"]);self.dirty=True
        values=(self.AUTO,)+tuple(self.model.peers)
        if tuple(self.peer_combo.cget("values"))!=values:self.peer_combo.configure(values=values)

    def clear(self):
        self.model=NumericSamples(self.config if self.mode.get()=="Custom" else None);self.peer.set(self.AUTO);self.peer_combo.configure(values=(self.AUTO,));self.render(force=True)

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
            cv.create_text(18,68,text="Select Auto for numeric lines, or Custom to extract a JSON field, text parameter or binary value. Only RX is plotted.",anchor="nw",fill=c["muted"],font=(self.app.ui_font,11),width=max(100,w-36))
            self.status.set(f"{connection} · {self.mode.get()} · last 300 samples per peer · unmatched / invalid messages are skipped.")
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
