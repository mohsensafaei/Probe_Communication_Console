'Discoverable, offline protocol and comparison tools; no transport mutations.'
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, ttk

from ..analysis.codec import CONTROLS, hexdump, visible
from .comparison import ComparePane
from .inspector import ProtocolPane
from .traffic_picker import TrafficPicker
from .widgets import Actions, entry, modal, table


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
        self.app.put_text(self.decoded,visible(shown,self.encoding.get()) if shown else "Double-click a traffic row to inspect a message.")
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
        self.configure(bg=app.colors["panel"]);self.transient(app.winfo_toplevel());self.bind("<Escape>",lambda e:self.destroy())
        self.bind("<Control-plus>",lambda e:app.zoom(1));self.bind("<Control-minus>",lambda e:app.zoom(-1))
        self.feedback=tk.StringVar();self.source=tk.StringVar(value="Double-click a message to inspect it.")
        body=ttk.Frame(self,padding=12);body.pack(fill="both",expand=True)
        ttk.Label(body,text="Analyze traffic",font=(app.ui_font,19,"bold")).pack(anchor="w")
        ttk.Label(body,textvariable=self.source,wraplength=870).pack(anchor="w",pady=(3,6))
        actions=ttk.Frame(body);actions.pack(fill="x",pady=(0,6))
        ttk.Button(actions,text="Copy hex",command=lambda:self.action(self.copy_hex)).pack(side="left",padx=6)
        ttk.Button(actions,text="Save bytes…",command=lambda:self.action(self.save_bytes)).pack(side="left")
        ttk.Button(actions,text="Load into composer",command=lambda:self.action(self.load_composer)).pack(side="right")
        ttk.Label(body,textvariable=self.feedback,wraplength=870).pack(side="bottom",anchor="w")
        self.tabs=ttk.Notebook(body);self.tabs.pack(fill="both",expand=True)
        self.payload=PayloadViews(self.tabs,app)
        self.protocol=ProtocolPane(self.tabs,app);self.tabs.add(self.protocol,text="Protocol Inspector")
        self.protocol.choose=lambda:TrafficPicker(app,self.set_data,self)
        self.comparison=ComparePane(self.tabs,app,a_label="Choose A",b_label="Choose B");self.tabs.add(self.comparison,text="Capture Diff")
        from .hid import HidReportPane
        self.hid=HidReportPane(self.tabs,app)
        from .plugin import PluginPane
        self.plugins=PluginPane(self.tabs,app)
        self.tabs.bind("<<NotebookTabChanged>>",self.remember_tab)
        self.wm_protocol("WM_DELETE_WINDOW",self.hide)
        self.bind("<Escape>",lambda e:self.hide())

    def hide(self):
        self.remember_tab();self.withdraw()

    def remember_tab(self,event=None):
        if self.event_key is not None:
            if not hasattr(self.app,"analysis_tabs"):self.app.analysis_tabs={}
            if not hasattr(self.app,"analysis_picker_states"):self.app.analysis_picker_states={}
            self.app.analysis_tabs[self.event_key]=self.tabs.tab(self.tabs.select(),"text")
            self.app.analysis_picker_states[self.event_key]=dict(self.comparison.picker_state)
            if len(self.app.analysis_tabs)>2000:
                old=next(iter(self.app.analysis_tabs));self.app.analysis_tabs.pop(old)
                self.app.analysis_picker_states.pop(old,None)

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


def open_analysis(app,tab=None,*,event=None,event_key=None):
    event=app.selected() if event is None else event;data=event["data"] if event else b""
    label=f"{event['direction']} · {event.get('peer','')} · {len(data)} bytes" if event else "Choose traffic to begin. No connection is required."
    previous=None
    if event:
        for candidate in app.order:
            row=app.events.get(candidate)
            if row is None:continue
            if row is event or candidate==event_key:break
            if row.get("direction")==event.get("direction") and row.get("peer")==event.get("peer"):previous=row
    win=getattr(app,"analysis_window",None)
    if win is None or not win.winfo_exists():win=AnalysisWindow(app)
    key=event_key if event_key is not None else app.table.selection()[0] if event else None
    if app.plugins.entries or event and 'original_hex' in event:
        if str(win.plugins) not in win.tabs.tabs():win.tabs.add(win.plugins,text="Plugins")
        win.plugins.set_event(event,key)
    elif str(win.plugins) in win.tabs.tabs():win.tabs.forget(win.plugins)
    if event and event.get("hid"):
        if str(win.hid) not in win.tabs.tabs():win.tabs.add(win.hid,text="HID Report")
        win.hid.set_event(event)
    elif str(win.hid) in win.tabs.tabs():win.tabs.forget(win.hid)
    if win.event_key!=key or win.data!=data:
        win.remember_tab()
        win.set_data(data,label);win.event_key=key
        if event and event.get("hid") and key not in getattr(app,"analysis_tabs",{}):win.tabs.select(win.hid)
        win.comparison.direction=event.get("direction","RX") if event else "RX"
        win.comparison.peer=event.get("peer","") if event else ""
        win.comparison.picker_state=dict(getattr(app,"analysis_picker_states",{}).get(key,{}))
        remembered=getattr(app,"analysis_tabs",{}).get(key)
        if remembered:
            for page in win.tabs.tabs():
                if win.tabs.tab(page,"text")==remembered:win.tabs.select(page)
        if previous:win.comparison.set_data("A",previous["data"],"Previous message · "+str(previous.get("peer","")))
        else:win.comparison.a=b"";win.comparison.a_ready=False;win.comparison.a_label.set("Choose A");win.comparison.refresh()
    if tab is not None:
        names={"Protocol":win.protocol,"Compare":win.comparison,"Plugins":win.plugins,**win.payload.pages}
        if tab in names:win.tabs.select(names[tab])
    win.deiconify();win.lift();win.focus_set()
    app.analysis_window=win;return win


def compare_selected(app,rows):
    """Compare exact selected payloads. Never concatenate unrelated messages."""
    def label(row):
        key,event=row
        return f"#{key} · {event['direction']} · {event.get('peer','')} · {len(event['data'])} bytes"

    def show(a,b):
        win=open_analysis(app,"Compare",event=b[1],event_key=b[0])
        win.comparison.set_data("A",a[1]['data'],label(a))
        win.comparison.set_data("B",b[1]['data'],label(b))
        win.source.set(f"Selected traffic · reference #{a[0]} → message #{b[0]}")
        return win

    if len(rows)==2:return show(rows[0],rows[1])
    win=modal(app,"Capture Diff · selected messages","760x340",(650,320))
    body=ttk.Frame(win,padding=16);body.pack(fill="both",expand=True)
    ttk.Label(body,text="Choose two selected messages",font=(app.ui_font,17,"bold")).pack(anchor="w")
    ttk.Label(body,text=f"Choose a reference (A) and a message (B) from your {len(rows)} selected messages.",wraplength=700).pack(anchor="w",pady=6)
    choices={label(row):row for row in rows}
    win.reference=tk.StringVar(value=label(rows[0]));win.message=tk.StringVar(value=label(rows[1]))
    fields=ttk.Frame(body);fields.pack(fill="x");fields.columnconfigure(0,weight=1)
    reference=entry(fields,"Reference (A)",win.reference,0,values=tuple(choices),width=65)
    message=entry(fields,"Message (B)",win.message,1,values=tuple(choices),width=65)
    feedback=tk.StringVar();ttk.Label(body,textvariable=feedback).pack(anchor="w",pady=6)
    controls=ttk.Frame(body);controls.pack(side="bottom",fill="x")
    def choose():
        a,b=choices[win.reference.get()],choices[win.message.get()]
        if a[0]==b[0]:return
        win.destroy();show(a,b)
    confirm=ttk.Button(controls,text="Compare",style="Accent.TButton",command=choose);confirm.pack(side="right")
    ttk.Button(controls,text="Cancel",command=win.destroy).pack(side="right",padx=6)
    def changed(*_):
        same=win.reference.get()==win.message.get();confirm.configure(state="disabled" if same else "normal")
        feedback.set("Choose two different messages." if same else "Only your selected messages are listed; original bytes stay separate.")
    reference.bind("<<ComboboxSelected>>",changed);message.bind("<<ComboboxSelected>>",changed)
    win.reference.trace_add("write",changed);win.message.trace_add("write",changed);changed()
    win.confirm=confirm;win.grab_set();return win
