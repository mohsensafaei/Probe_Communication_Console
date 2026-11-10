import json
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, ttk

from ..codec import hexdump, visible
from ..comparison import compare_bytes, comparison_report, parse_ranges
from ..protocol import json_frame
from .traffic_picker import TrafficPicker
from .widgets import Actions, entry, modal, table


class ComparePane(ttk.Frame,Actions):
    def __init__(self,parent,app,a=b"",a_label="Choose A",b=b"",b_label="Choose B"):
        super().__init__(parent,padding=12);self.app=app;self.a=a;self.b=b;self.ranges=[];self.selectors=[];self.differences=();self.page=0
        self.feedback=tk.StringVar();self.a_label=tk.StringVar(value=a_label);self.b_label=tk.StringVar(value=b_label)
        self.a_ready=bool(a) or a_label!="Choose A";self.b_ready=bool(b) or b_label!="Choose B"
        self.direction="RX";self.peer="";self.picker_state={}
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

    def choose(self,side):
        state=self.picker_state.get(side,(self.direction,self.peer))
        source=getattr(self,'sources',{}).get(side,self.app)
        picker=TrafficPicker(source,lambda data,label:self.set_data(side,data,label),self,direction=state[0],peer=state[1])
        def remember(event):
            if event.widget is picker:self.picker_state[side]=(picker.direction.get(),picker.peer.get())
        picker.bind("<Destroy>",remember,add="+")
        return picker

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
