"""Discoverable, offline protocol and comparison tools; no transport mutations."""
import json
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog

from .capture import load_capture
from .codec import CONTROLS, hexdump, visible
from .comparison import compare_bytes, comparison_report, parse_ranges
from .protocol import (CHECKSUMS, FIELD_TYPES, custom_fields, inspect_payload,
                       json_frame, validate_fields)


class Actions:
    def action(self, operation):
        try:return operation()
        except (ValueError, TypeError, KeyError, OSError, RuntimeError, RecursionError) as exc:self.feedback.set(str(exc))


def entry(parent, label, variable, row, column=0, values=None, width=20):
    box=ttk.Frame(parent);box.grid(row=row,column=column,sticky="ew",padx=(0,10),pady=4)
    ttk.Label(box,text=label).pack(anchor="w")
    widget=ttk.Combobox(box,textvariable=variable,values=values,state="readonly",width=width) if values else ttk.Entry(box,textvariable=variable,width=width)
    widget.pack(fill="x",pady=(3,0));return widget


def table(parent,columns,height=7):
    box=ttk.Frame(parent);box.pack(fill="both",expand=True,pady=6)
    view=ttk.Treeview(box,columns=tuple(key for key,_,_ in columns),show="headings",height=height,selectmode="browse")
    for key,title,width in columns:view.heading(key,text=title);view.column(key,width=width,minwidth=45,stretch=True)
    view.pack(side="left",fill="both",expand=True)
    scroll=ttk.Scrollbar(box,command=view.yview);scroll.pack(side="right",fill="y");view.configure(yscrollcommand=scroll.set)
    return view


def modal(parent,title,size="760x560",minimum=(700,500)):
    app=parent.app if hasattr(parent,"app") else parent
    win=tk.Toplevel(parent);win.title("Probe · "+title);win.geometry(size);win.minsize(*minimum)
    win.configure(bg=app.colors["panel"]);win.transient(parent.winfo_toplevel())
    win.bind("<Escape>",lambda event:win.destroy());return win


class TrafficPicker(tk.Toplevel,Actions):
    """One-direction, one-peer selection, with optional chunk concatenation."""
    def __init__(self,app,callback,parent=None,many=True):
        super().__init__(parent or app);self.app=app;self.callback=callback;self.many=many
        self.title("Probe · Choose traffic");self.geometry("850x560");self.minsize(760,500)
        self.configure(bg=app.colors["panel"]);self.transient((parent or app).winfo_toplevel())
        self.feedback=tk.StringVar();self.direction=tk.StringVar(value="RX");self.peer=tk.StringVar()
        self.rows=[dict(app.events[i]) for i in app.order if i in app.events]
        self.source_name="Traffic history"
        body=ttk.Frame(self,padding=16);body.pack(fill="both",expand=True)
        ttk.Label(body,text="Choose traffic",font=(app.ui_font,18,"bold")).pack(anchor="w")
        ttk.Label(body,text="Select one message, or combine ordered chunks from the same direction and peer.",wraplength=750).pack(anchor="w",pady=4)
        bar=ttk.Frame(body);bar.pack(fill="x")
        direction=entry(bar,"Direction",self.direction,0,values=("RX","TX"),width=8)
        self.peer_combo=entry(bar,"Peer",self.peer,0,1,values=("—",),width=35)
        ttk.Button(bar,text="Load capture / bytes…",command=lambda:self.action(self.load_file)).grid(row=0,column=2,sticky="s",pady=4)
        direction.bind("<<ComboboxSelected>>",lambda e:self.refresh());self.peer_combo.bind("<<ComboboxSelected>>",lambda e:self.refresh())
        footer=ttk.Frame(body);footer.pack(side="bottom",fill="x",pady=6)
        ttk.Button(footer,text="Use selected",style="Accent.TButton",command=lambda:self.action(self.choose)).pack(side="right")
        ttk.Button(footer,text="Cancel",command=self.destroy).pack(side="right",padx=6)
        if many:ttk.Button(footer,text="Select all shown",command=lambda:self.view.selection_set(self.view.get_children())).pack(side="left")
        ttk.Label(body,textvariable=self.feedback,wraplength=750).pack(side="bottom",anchor="w")
        self.view=table(body,(("direction","Flow",60),("peer","Peer",200),("bytes","Bytes",70),("preview","Payload",430)))
        self.view.configure(selectmode="extended" if many else "browse")
        self.view.bind("<Double-1>",lambda e:self.action(self.choose))
        self.refresh();self.bind("<Escape>",lambda e:self.destroy());self.grab_set()

    def refresh(self):
        peers=sorted({str(row.get("peer","")) for row in self.rows if row.get("direction")==self.direction.get()})
        self.peer_combo.configure(values=peers)
        if self.peer.get() not in peers:self.peer.set(peers[0] if peers else "")
        self.filtered=[row for row in self.rows if row.get("direction")==self.direction.get() and str(row.get("peer",""))==self.peer.get()]
        self.view.delete(*self.view.get_children())
        for i,row in enumerate(self.filtered):self.view.insert("","end",iid=str(i),values=(row["direction"],row.get("peer",""),len(row["data"]),visible(row["data"][:80])))
        if self.filtered:self.view.selection_set(str(len(self.filtered)-1))
        self.feedback.set(f"{self.source_name} · {len(self.filtered)} chunks. Captured bytes are unchanged.")

    def load_file(self):
        path=filedialog.askopenfilename(parent=self,filetypes=[("Capture or binary","*.jsonl *.csv *.bin"),("All files","*")])
        if not path:return
        file=Path(path)
        if file.suffix.lower() in (".jsonl",".csv"):
            self.rows=load_capture(file);self.source_name=file.name;self.refresh()
        else:
            if file.stat().st_size>1024*1024:raise ValueError("Choose at most 1 MiB of binary data.")
            data=file.read_bytes();self.callback(data,file.name);self.destroy()

    def choose(self):
        chosen=set(self.view.selection());rows=[row for i,row in enumerate(self.filtered) if str(i) in chosen]
        if not rows:raise ValueError("Select a message first, or load a capture / binary file.")
        size=sum(len(row["data"]) for row in rows)
        if size>1024*1024:raise ValueError("Select at most 1 MiB. Comparison supports 256 KiB per side.")
        data=b"".join(row["data"] for row in rows)
        self.callback(data,f"{self.source_name} · {self.direction.get()} · {self.peer.get()} · {len(rows)} chunks");self.destroy()


class ProtocolPane(ttk.Frame,Actions):
    MODES=("Auto","JSON","TLV (1-byte)","BER-TLV","Custom fields","Raw bytes")
    def __init__(self,parent,app,data=b"",label="No message selected"):
        super().__init__(parent,padding=12);self.app=app;self.data=data;self.source=tk.StringVar(value=label)
        self.feedback=tk.StringVar();self.mode=tk.StringVar(value="Auto");self.page=0;self.fields=()
        try:self.definitions=validate_fields(json.loads(app.vars["protocol_fields"].get()))
        except (ValueError,TypeError):self.definitions=[]
        ttk.Label(self,text="Interpret the selected bytes",font=(app.ui_font,16,"bold")).pack(anchor="w")
        ttk.Label(self,textvariable=self.source,wraplength=880).pack(anchor="w",pady=4)
        bar=ttk.Frame(self);bar.pack(fill="x")
        ttk.Button(bar,text="Choose traffic…",command=self.choose).pack(side="left",padx=(0,8))
        combo=ttk.Combobox(bar,textvariable=self.mode,values=self.MODES,state="readonly",width=17);combo.pack(side="left")
        combo.bind("<<ComboboxSelected>>",lambda e:self.refresh())
        ttk.Button(bar,text="Custom fields…",command=self.edit_fields).pack(side="left",padx=8)
        ttk.Button(bar,text="Load profile…",command=lambda:self.action(self.load_profile)).pack(side="right")
        ttk.Button(bar,text="Save profile…",command=lambda:self.action(self.save_profile)).pack(side="right",padx=6)
        lower=ttk.Frame(self);lower.pack(side="bottom",fill="x")
        ttk.Label(lower,textvariable=self.feedback,wraplength=880).pack(anchor="w",pady=4)
        controls=ttk.Frame(lower);controls.pack(fill="x")
        ttk.Button(controls,text="Copy field path",command=lambda:self.action(self.copy_path)).pack(side="left")
        ttk.Button(controls,text="Next bytes →",command=lambda:self.turn_page(1)).pack(side="right")
        ttk.Button(controls,text="← Previous bytes",command=lambda:self.turn_page(-1)).pack(side="right",padx=6)
        self.byte_caption=tk.StringVar();ttk.Label(controls,textvariable=self.byte_caption).pack(side="left",padx=12)
        self.hex=app.text_widget(lower,height=7,wrap="none");self.hex.pack(fill="x",pady=6)
        self.hex.tag_configure("field",background=app.colors["select"],foreground=app.colors["accent"])
        self.view=table(self,(("name","Field",240),("offset","Offset",70),("size","Bytes",65),("value","Value",280),("status","Status",90)))
        for status,color in (("Mismatch",app.colors["red"]),("Truncated",app.colors["red"]),("Valid",app.colors["accent"])):self.view.tag_configure(status,foreground=color)
        self.view.bind("<<TreeviewSelect>>",lambda e:self.highlight());self.refresh()

    def choose(self):return TrafficPicker(self.app,self.set_data,self)

    def set_data(self,data,label):self.data=data;self.source.set(label);self.page=0;self.refresh()

    def refresh(self):
        self.view.delete(*self.view.get_children());self.fields=()
        try:
            mode,self.fields=inspect_payload(self.data,self.mode.get(),self.definitions)
            for i,field in enumerate(self.fields):self.view.insert("","end",iid=str(i),values=(field.name,field.offset,field.size,field.value,field.status),tags=(field.status,))
            note="JSON and ASCII body-length prefixes are detected automatically." if mode=="JSON" else "Choose TLV explicitly; tag/length layouts are not guessed." if mode=="Raw bytes" else "Select a field to highlight its original bytes."
            self.feedback.set(f"{mode} · {len(self.fields)} fields. {note}")
        except (ValueError,TypeError,KeyError,RecursionError) as exc:self.feedback.set(str(exc))
        self.render_bytes()

    def render_bytes(self):
        self.page=max(0,min(self.page,max(0,(len(self.data)-1)//4096)))
        start=self.page*4096;shown=self.data[start:start+4096]
        self.app.put_text(self.hex,hexdump(shown,start));self.byte_caption.set(f"Bytes {start}–{start+len(shown)} of {len(self.data)}")

    def turn_page(self,delta):self.page+=delta;self.render_bytes();self.highlight(move=False)

    def highlight(self,move=True):
        ids=self.view.selection();self.hex.tag_remove("field","1.0","end")
        if not ids:return
        field=self.fields[int(ids[0])]
        if move:self.page=field.offset//4096;self.render_bytes()
        start=self.page*4096
        for offset in range(max(field.offset,start),min(field.offset+field.size,start+4096,len(self.data))):
            line=(offset-start)//16+1;col=10+3*(offset%16)
            self.hex.tag_add("field",f"{line}.{col}",f"{line}.{col+2}")
        self.hex.see(f"{max(1,(field.offset-start)//16+1)}.0")

    def copy_path(self):
        ids=self.view.selection()
        if not ids:raise ValueError("Select a JSON or TLV field first.")
        field=self.fields[int(ids[0])]
        value=field.selector or f"{field.offset}:{field.offset+field.size}"
        self.clipboard_clear();self.clipboard_append(value);self.feedback.set("Copied field path: "+value)

    def edit_fields(self):
        self.mode.set("Custom fields");return FieldsEditor(self)

    def set_fields(self,fields):
        self.definitions=validate_fields(fields);self.app.vars["protocol_fields"].set(json.dumps(fields));self.app.save_settings();self.refresh()

    def load_profile(self):
        path=filedialog.askopenfilename(parent=self,filetypes=[("Protocol profile","*.json")])
        if not path:return
        if Path(path).stat().st_size>262144:raise ValueError("A protocol profile is limited to 256 KiB.")
        profile=json.loads(Path(path).read_text(encoding="utf-8-sig"))
        if not isinstance(profile,dict) or profile.get("format")!="probe-protocol" or profile.get("version")!=1:raise ValueError("Choose a Probe protocol profile.")
        fields=validate_fields(profile.get("fields"));self.mode.set("Custom fields");self.set_fields(fields)

    def save_profile(self):
        validate_fields(self.definitions)
        path=filedialog.asksaveasfilename(parent=self,defaultextension=".json",filetypes=[("Protocol profile","*.json")])
        if path:Path(path).write_text(json.dumps(dict(format="probe-protocol",version=1,fields=self.definitions),indent=2),encoding="utf-8");self.feedback.set("Saved custom field definitions. Original traffic is unchanged.")


class FieldsEditor(tk.Toplevel,Actions):
    def __init__(self,pane):
        super().__init__(pane);self.pane=pane;self.app=pane.app;self.items=[dict(item) for item in pane.definitions]
        self.title("Probe · Custom fields");self.geometry("760x520");self.minsize(700,480);self.transient(pane.winfo_toplevel());self.configure(bg=self.app.colors["panel"])
        self.feedback=tk.StringVar(value="Offsets start at 0. A length of 0 reads to the end. Changes apply only after Save fields.")
        body=ttk.Frame(self,padding=16);body.pack(fill="both",expand=True)
        ttk.Label(body,text="Describe your message",font=(self.app.ui_font,18,"bold")).pack(anchor="w")
        footer=ttk.Frame(body);footer.pack(side="bottom",fill="x",pady=6)
        ttk.Button(footer,text="Save fields",style="Accent.TButton",command=lambda:self.action(self.save)).pack(side="right")
        ttk.Button(footer,text="Cancel",command=self.destroy).pack(side="right",padx=6)
        ttk.Label(body,textvariable=self.feedback,wraplength=680).pack(side="bottom",anchor="w")
        bar=ttk.Frame(body);bar.pack(fill="x",pady=6)
        ttk.Button(bar,text="Add field…",command=self.edit).pack(side="left")
        ttk.Button(bar,text="Edit…",command=lambda:self.action(lambda:self.edit(self.selected()))).pack(side="left",padx=6)
        ttk.Button(bar,text="Remove",command=lambda:self.action(self.remove)).pack(side="left")
        self.view=table(body,(("name","Name",230),("offset","Offset",80),("length","Bytes",80),("kind","Interpret as",220)))
        self.view.bind("<Double-1>",lambda e:self.action(lambda:self.edit(self.selected())))
        self.refresh();self.grab_set();self.bind("<Escape>",lambda e:self.destroy())

    def selected(self):
        if not self.view.selection():raise ValueError("Select a field first.")
        return int(self.view.selection()[0])

    def refresh(self):
        self.view.delete(*self.view.get_children())
        for i,item in enumerate(self.items):self.view.insert("","end",iid=str(i),values=(item.get("name",""),item.get("offset",0),item.get("length",1),item.get("kind","Hex")))

    def remove(self):del self.items[self.selected()];self.refresh()

    def save(self):self.pane.set_fields(self.items);self.destroy()

    def edit(self,index=None):
        item=self.items[index] if index is not None else dict(name="New field",offset=0,length=1,kind="Hex")
        win=modal(self,"Field","650x430",(620,410));variables={key:tk.StringVar(value=str(item.get(key,default))) for key,default in dict(name="Field",offset=0,length=1,kind="Hex",algorithm="SUM8",start="",end="").items()}
        body=ttk.Frame(win,padding=16);body.pack(fill="both",expand=True)
        entry(body,"Field name",variables["name"],0);kind=entry(body,"Interpret as",variables["kind"],0,1,FIELD_TYPES)
        entry(body,"Byte offset (0-based)",variables["offset"],1);entry(body,"Length (0 = rest)",variables["length"],1,1)
        validation=ttk.Frame(body);validation.grid(row=2,column=0,columnspan=2,sticky="ew")
        entry(validation,"Checksum algorithm",variables["algorithm"],0,values=CHECKSUMS)
        entry(validation,"Range start (blank = auto)",variables["start"],1)
        entry(validation,"Range end (excluded; blank = auto)",variables["end"],1,1)
        def changed(*_):
            if variables["kind"].get().startswith(("Length","Checksum")):validation.grid()
            else:validation.grid_remove()
        kind.bind("<<ComboboxSelected>>",changed);changed()
        feedback=tk.StringVar();ttk.Label(body,textvariable=feedback,wraplength=590).grid(row=3,column=0,columnspan=2,sticky="w",pady=6)
        def save():
            try:
                row={key:var.get() for key,var in variables.items() if var.get()!=""}
                validate_fields([row])
                if self.pane.data:custom_fields(self.pane.data,[row])
                if index is None:self.items.append(row)
                else:self.items[index]=row
                validate_fields(self.items);self.refresh();win.destroy();self.grab_set()
            except (ValueError,TypeError) as exc:feedback.set(str(exc))
        controls=ttk.Frame(body);controls.grid(row=4,column=0,columnspan=2,sticky="e",pady=8)
        ttk.Button(controls,text="Cancel",command=win.destroy).pack(side="right",padx=6)
        ttk.Button(controls,text="Save field",style="Accent.TButton",command=save).pack(side="right")
        win.grab_set();self.field_window=win;self.field_variables=variables;self.save_field=save


class ComparePane(ttk.Frame,Actions):
    def __init__(self,parent,app,a=b"",a_label="Choose A",b=b"",b_label="Choose B"):
        super().__init__(parent,padding=12);self.app=app;self.a=a;self.b=b;self.ranges=[];self.selectors=[];self.differences=();self.page=0
        self.feedback=tk.StringVar();self.a_label=tk.StringVar(value=a_label);self.b_label=tk.StringVar(value=b_label)
        self.a_ready=bool(a) or a_label!="Choose A";self.b_ready=bool(b) or b_label!="Choose B"
        self.show_equal=tk.BooleanVar(value=False)
        ttk.Label(self,text="Compare messages",font=(app.ui_font,16,"bold")).pack(anchor="w")
        ttk.Label(self,text="1. Choose a reference (A).   2. Choose a message to check (B).   Differences appear automatically.",wraplength=880).pack(anchor="w",pady=4)
        for letter,label in (("A",self.a_label),("B",self.b_label)):
            bar=ttk.Frame(self);bar.pack(fill="x",pady=3)
            ttk.Button(bar,text="1. Reference (A)…" if letter=="A" else "2. Message (B)…",command=lambda side=letter:self.choose(side)).pack(side="left",padx=(0,10))
            ttk.Label(bar,textvariable=label,wraplength=730).pack(side="left")
        bar=ttk.Frame(self);bar.pack(fill="x",pady=4)
        ttk.Button(bar,text="Swap A / B",command=lambda:self.action(self.swap)).pack(side="left")
        ttk.Button(bar,text="Ignore variable fields…",command=self.ignore_dialog).pack(side="left",padx=6)
        ttk.Checkbutton(bar,text="Show unchanged",variable=self.show_equal,command=self.render).pack(side="left",padx=6)
        ttk.Button(bar,text="Save comparison…",command=lambda:self.action(self.save)).pack(side="right")
        lower=ttk.Frame(self);lower.pack(side="bottom",fill="x")
        ttk.Label(lower,textvariable=self.feedback,wraplength=880).pack(anchor="w",pady=4)
        paging=ttk.Frame(lower);paging.pack(fill="x")
        ttk.Button(paging,text="← Previous",command=lambda:self.turn_page(-1)).pack(side="left")
        ttk.Button(paging,text="Next →",command=lambda:self.turn_page(1)).pack(side="left",padx=6)
        ttk.Label(lower,text="Changed = different bytes · Added = only in B · Removed = only in A · Click a result for text and hex.",wraplength=880).pack(anchor="w",pady=4)
        self.page_label=tk.StringVar();ttk.Label(paging,textvariable=self.page_label).pack(side="left")
        self.detail=app.text_widget(lower,height=7,wrap="word");self.detail.pack(fill="x",pady=6)
        self.view=table(self,(("kind","Change",95),("a","A offset / bytes",115),("av","Reference (A) · Hex",270),("b","B offset / bytes",115),("bv","Message (B) · Hex",270)))
        for kind,color in (("changed",app.colors["red"]),("added",app.colors["accent"]),("removed",app.colors["red"]),("ignored",app.colors["muted"])):self.view.tag_configure(kind,foreground=color)
        self.view.bind("<<TreeviewSelect>>",lambda e:self.show_detail());self.refresh()

    def choose(self,side):return TrafficPicker(self.app,lambda data,label:self.set_data(side,data,label),self)

    def set_data(self,side,data,label):
        if side=="A":self.a=data;self.a_label.set(label);self.a_ready=True
        else:self.b=data;self.b_label.set(label);self.b_ready=True
        self.page=0;self.refresh()

    def swap(self):
        self.a,self.b=self.b,self.a;self.a_ready,self.b_ready=self.b_ready,self.a_ready
        a,b=self.a_label.get(),self.b_label.get();self.a_label.set(b);self.b_label.set(a);self.refresh()

    def refresh(self):
        self.differences=();self.view.delete(*self.view.get_children());self.app.put_text(self.detail,"")
        if not self.a_ready or not self.b_ready:self.feedback.set("Choose a reference (A) and a message (B) above to begin. No traffic is sent.");return
        try:
            self.differences=compare_bytes(self.a,self.b,self.ranges,self.selectors)
            counts={kind:sum(max(d.a_end-d.a_start,d.b_end-d.b_start) for d in self.differences if d.kind==kind) for kind in ("changed","added","removed","ignored")}
            self.feedback.set(("Messages match. " if not any(counts[k] for k in ("changed","added","removed")) else "Differences found. ")+f"A: {len(self.a)} bytes · B: {len(self.b)} bytes · "+" · ".join(f"{key}: {value}" for key,value in counts.items())+". Original bytes are preserved.")
        except (ValueError,TypeError) as exc:self.feedback.set(str(exc))
        self.render()

    def render(self):
        self.view.delete(*self.view.get_children());self.shown=[d for d in self.differences if d.kind!="equal" or self.show_equal.get()]
        pages=max(1,(len(self.shown)+127)//128);self.page=max(0,min(self.page,pages-1))
        for i,item in enumerate(self.shown[self.page*128:(self.page+1)*128],self.page*128):
            a=self.a[item.a_start:item.a_end];b=self.b[item.b_start:item.b_end]
            self.view.insert("","end",iid=str(i),values=(item.kind.title(),f"{item.a_start} / {len(a)}",a[:24].hex(" ").upper()+(" …" if len(a)>24 else ""),
                             f"{item.b_start} / {len(b)}",b[:24].hex(" ").upper()+(" …" if len(b)>24 else "")),tags=(item.kind,))
        self.page_label.set(f"Page {self.page+1}/{pages} · {len(self.shown)} ranges")
        children=self.view.get_children()
        if children:self.view.selection_set(children[0]);self.show_detail()
        if not self.shown and self.differences:self.app.put_text(self.detail,"The inputs are identical. Enable Show unchanged to inspect their ranges.")

    def turn_page(self,delta):self.page+=delta;self.render()

    def show_detail(self):
        ids=self.view.selection()
        if not ids:return
        item=self.shown[int(ids[0])]
        a=self.a[item.a_start:min(item.a_end,item.a_start+2048)];b=self.b[item.b_start:min(item.b_end,item.b_start+2048)]
        text=f"{item.kind.upper()} · A [{item.a_start}:{item.a_end}] → B [{item.b_start}:{item.b_end}]\nA:\n{hexdump(a,item.a_start)}\nB:\n{hexdump(b,item.b_start)}"
        text+="\nReference text: "+visible(a,self.app.vars["encoding"].get())+"\nMessage text: "+visible(b,self.app.vars["encoding"].get())
        if item.a_end-item.a_start>2048 or item.b_end-item.b_start>2048:text+="\n[Preview limited to 2048 bytes per side. Save comparison includes every byte.]"
        self.app.put_text(self.detail,text)

    def save(self):
        if not self.a_ready or not self.b_ready:raise ValueError("Choose both A and B before saving a comparison.")
        differences=compare_bytes(self.a,self.b,self.ranges,self.selectors)
        path=filedialog.asksaveasfilename(parent=self,defaultextension=".json",filetypes=[("Comparison report","*.json")])
        if path:
            report=comparison_report(self.a,self.b,differences,self.ranges,self.selectors);report.update(a_source=self.a_label.get(),b_source=self.b_label.get())
            Path(path).write_text(json.dumps(report,indent=2,ensure_ascii=False),encoding="utf-8");self.feedback.set("Saved original A/B bytes, ignored fields and all difference ranges.")

    def ignore_dialog(self):
        win=modal(self,"Ignore changing fields","760x540",(700,500));body=ttk.Frame(win,padding=16);body.pack(fill="both",expand=True)
        ttk.Label(body,text="Ignore known variable data",font=(self.app.ui_font,17,"bold")).pack(anchor="w")
        ttk.Label(body,text="Select JSON value fields to ignore. Their source bytes stay intact, even when value lengths differ.",wraplength=690).pack(anchor="w",pady=4)
        ranges=tk.StringVar(value=" ".join(f"{a}:{b}" for a,b in self.ranges));feedback=tk.StringVar()
        footer=ttk.Frame(body);footer.pack(side="bottom",fill="x",pady=6)
        fieldbox=ttk.Frame(body);fieldbox.pack(side="bottom",fill="x")
        entry(fieldbox,"Also ignore byte ranges in both inputs (0-based, end excluded)",ranges,0,width=65)
        ttk.Label(body,textvariable=feedback,wraplength=690).pack(side="bottom",anchor="w")
        view=table(body,(("path","JSON field",300),("a","A value",180),("b","B value",180)));view.configure(selectmode="extended")
        maps=[]
        for data in (self.a,self.b):
            try:maps.append({f.selector:f.value for f in json_frame(data)[1] if f.kind=="JSON"})
            except ValueError:maps.append({})
        paths=sorted(set(maps[0])&set(maps[1]))
        for i,path in enumerate(paths):
            view.insert("","end",iid=str(i),values=(path,maps[0][path][:60],maps[1][path][:60]))
            if path in self.selectors:view.selection_add(str(i))
        def apply():
            try:
                parsed=parse_ranges(ranges.get());selected=[paths[int(i)] for i in view.selection()]
                compare_bytes(self.a,self.b,parsed,selected)
                self.ranges=parsed;self.selectors=selected;self.page=0;self.refresh();win.destroy()
            except ValueError as exc:feedback.set(str(exc))
        ttk.Button(footer,text="Apply ignores",style="Accent.TButton",command=apply).pack(side="right")
        ttk.Button(footer,text="Cancel",command=win.destroy).pack(side="right",padx=6)
        ttk.Button(footer,text="Clear selection",command=lambda:view.selection_remove(view.selection())).pack(side="left")
        win.grab_set();self.ignore_window=win;self.ignore_view=view;self.ignore_ranges=ranges;self.apply_ignores=apply
        return win


class PayloadViews:
    """Three synchronized byte-exact message views inside Analyze only."""
    def __init__(self,tabs,app):
        self.app=app;self.data=b"";self.page=0;self.tabs=tabs;self.pages={};self.page_labels=[];self.buttons=[]
        self.encoding=tk.StringVar(value=app.vars["encoding"].get())
        for name in ("Decoded text","Hex + ASCII","Every byte"):
            page=ttk.Frame(tabs,padding=12);self.pages[name]=page;tabs.add(page,text=name)
            footer=ttk.Frame(page);footer.pack(side="bottom",fill="x",pady=(6,0))
            previous=ttk.Button(footer,text="← Previous bytes",command=lambda:self.change_page(-1));previous.pack(side="left")
            next_=ttk.Button(footer,text="Next bytes →",command=lambda:self.change_page(1));next_.pack(side="left",padx=6)
            label=tk.StringVar();ttk.Label(footer,textvariable=label).pack(side="right");self.page_labels.append(label);self.buttons.append((previous,next_))
            if name=="Every byte":
                self.byte_table=table(page,(("offset","Offset",110),("hex","Hex",80),("dec","Decimal",90),("binary","Binary",160),("char","ASCII / control",240)))
            else:
                if name=="Decoded text":
                    bar=ttk.Frame(page);bar.pack(fill="x",pady=(0,6))
                    ttk.Label(bar,text="Text encoding").pack(side="left",padx=(0,6))
                    combo=ttk.Combobox(bar,textvariable=self.encoding,values=("utf-8","ascii","latin-1","cp1256","gbk","utf-16-le"),state="readonly",width=15)
                    combo.pack(side="left");combo.bind("<<ComboboxSelected>>",lambda e:self.render())
                    ttk.Label(bar,text="Control bytes are named; original bytes stay intact.").pack(side="left",padx=12)
                box=ttk.Frame(page);box.pack(fill="both",expand=True)
                text=app.text_widget(box,height=10,wrap="word" if name=="Decoded text" else "none")
                text.grid(row=0,column=0,sticky="nsew");box.rowconfigure(0,weight=1);box.columnconfigure(0,weight=1)
                scroll=ttk.Scrollbar(box,command=text.yview);scroll.grid(row=0,column=1,sticky="ns");text.configure(yscrollcommand=scroll.set)
                if name=="Hex + ASCII":
                    horizontal=ttk.Scrollbar(box,orient="horizontal",command=text.xview);horizontal.grid(row=1,column=0,sticky="ew");text.configure(xscrollcommand=horizontal.set);self.hextext=text
                else:self.decoded=text
        self.render()

    def set_data(self,data):self.data=data;self.page=0;self.render()

    def change_page(self,delta):
        self.page=max(0,min(self.page+delta,max(0,(len(self.data)-1)//4096)));self.render()

    def render(self):
        start=self.page*4096;shown=self.data[start:start+4096]
        self.app.put_text(self.decoded,visible(shown,self.encoding.get()) if shown else "Double-click a traffic row or Choose traffic to inspect a message.")
        self.app.put_text(self.hextext,hexdump(shown,start))
        self.byte_table.delete(*self.byte_table.get_children())
        for offset,byte in enumerate(shown,start):
            self.byte_table.insert("","end",iid=f"b{offset}",values=(f"{offset:08X} ({offset})",f"{byte:02X}",byte,f"{byte:08b}",CONTROLS.get(byte,chr(byte) if 32<=byte<127 else "—")))
        for label in self.page_labels:label.set(f"Bytes {start}–{start+len(shown)-1 if shown else 0} of {len(self.data)} · page {self.page+1}")
        for previous,next_ in self.buttons:
            previous.configure(state="normal" if self.page else "disabled");next_.configure(state="normal" if start+4096<len(self.data) else "disabled")


class AnalysisWindow(tk.Toplevel,Actions):
    def __init__(self,app):
        super().__init__(app);self.app=app;self.data=b"";self.label="";self.event_key=None
        self.title("Probe · Analyze traffic")
        self.geometry(f"{min(1000,max(920,app.winfo_screenwidth()-80))}x{min(760,max(700,app.winfo_screenheight()-90))}")
        self.minsize(920,700)
        self.configure(bg=app.colors["panel"]);self.transient(app);self.bind("<Escape>",lambda e:self.destroy())
        self.bind("<Control-plus>",lambda e:app.zoom(1));self.bind("<Control-minus>",lambda e:app.zoom(-1))
        self.feedback=tk.StringVar();self.source=tk.StringVar(value="Choose traffic to inspect; no connection is required.")
        body=ttk.Frame(self,padding=12);body.pack(fill="both",expand=True)
        ttk.Label(body,text="Analyze traffic",font=(app.ui_font,19,"bold")).pack(anchor="w")
        ttk.Label(body,textvariable=self.source,wraplength=870).pack(anchor="w",pady=(3,6))
        actions=ttk.Frame(body);actions.pack(fill="x",pady=(0,6))
        ttk.Button(actions,text="Choose traffic…",command=lambda:TrafficPicker(app,self.set_data,self)).pack(side="left")
        ttk.Button(actions,text="Copy hex",command=lambda:self.action(self.copy_hex)).pack(side="left",padx=6)
        ttk.Button(actions,text="Save bytes…",command=lambda:self.action(self.save_bytes)).pack(side="left")
        ttk.Button(actions,text="Load into composer",command=lambda:self.action(self.load_composer)).pack(side="right")
        ttk.Label(body,textvariable=self.feedback,wraplength=870).pack(side="bottom",anchor="w")
        self.tabs=ttk.Notebook(body);self.tabs.pack(fill="both",expand=True)
        self.payload=PayloadViews(self.tabs,app)
        self.protocol=ProtocolPane(self.tabs,app);self.tabs.add(self.protocol,text="Protocol Inspector")
        self.protocol.choose=lambda:TrafficPicker(app,self.set_data,self)
        self.comparison=ComparePane(self.tabs,app,a_label="Choose A",b_label="Choose B");self.tabs.add(self.comparison,text="Capture Diff")

    def set_data(self,data,label):
        self.data=data;self.label=label;self.source.set(label);self.payload.set_data(data);self.protocol.set_data(data,label)
        self.comparison.set_data("B",data,label)
        self.feedback.set("Inspection never sends or modifies traffic. Load into composer requires a separate Send action.")

    def copy_hex(self):
        if not self.data:raise ValueError("Choose a message first.")
        self.clipboard_clear();self.clipboard_append(self.data.hex(" ").upper());self.feedback.set("Copied every original byte as hex.")

    def save_bytes(self):
        path=filedialog.asksaveasfilename(parent=self,defaultextension=".bin",filetypes=[("Binary bytes","*.bin")])
        if path:Path(path).write_bytes(self.data);self.feedback.set(f"Saved {len(self.data)} original bytes.")

    def load_composer(self):
        if not self.data:raise ValueError("Choose a message first.")
        self.app.load_payload_bytes(self.data);self.feedback.set("Loaded exact bytes into the composer. Press Send in the main window to transmit.")


def open_analysis(app,tab=None):
    event=app.selected();data=event["data"] if event else b""
    label=f"{event['direction']} · {event.get('peer','')} · {len(data)} bytes" if event else "Choose traffic to begin. No connection is required."
    previous=None
    if event:
        candidates=[app.events[i] for i in app.order if i in app.events]
        for row in candidates:
            if row is event:break
            if row.get("direction")==event.get("direction") and row.get("peer")==event.get("peer"):previous=row
    win=getattr(app,"analysis_window",None)
    if win is None or not win.winfo_exists():win=AnalysisWindow(app)
    key=app.table.selection()[0] if event else None
    if win.event_key!=key or win.data!=data:
        win.set_data(data,label);win.event_key=key
        if previous:win.comparison.set_data("A",previous["data"],"Previous message · "+str(previous.get("peer","")))
        else:win.comparison.a=b"";win.comparison.a_ready=False;win.comparison.a_label.set("Choose A");win.comparison.refresh()
    if tab is not None:
        names={"Protocol":win.protocol,"Compare":win.comparison,**win.payload.pages}
        if tab in names:win.tabs.select(names[tab])
    win.lift();win.focus_set()
    app.analysis_window=win;return win
