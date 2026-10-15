"""Tk desktop UI. Standard-library widgets, no browser or Qt runtime."""
import csv
import datetime as dt
import json
import math
import os
from pathlib import Path
import queue
import re
import sys
import threading
import time
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, colorchooser

from . import __version__
from .codec import encode, hexdump, visible, CONTROLS, Framer
from .engine import Engine, MODES
from .terminal_ui import TerminalPane
from .capture import load_capture, replay_plan
from .typography import load_fonts, font_roles
from .skin import Chassis, MeterStrip, Rail

DARK = dict(bg="#121a28", panel="#202d43", input="#101c2e", border="#53637c",
            text="#eef3fc", muted="#b0bfd4", accent="#b6ed8a", blue="#82c7ff",
            red="#ff8b8b", select="#354963", metal="#b9c2cf", shine="#edf3fc",
            ink="#243047", lcd="#0e1825")
LIGHT = dict(bg="#d1d8e2", panel="#e8edf3", input="#f8fafc", border="#8698af",
             text="#152941", muted="#50647e", accent="#36710d", blue="#16679e",
             red="#b32737", select="#c6d6e7", metal="#bbc8d9", shine="#ffffff",
             ink="#243951", lcd="#e0e9d6")

def data_directory():
    base = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent.parent
    preferred = base / "probe-data"
    try:
        preferred.mkdir(exist_ok=True)
        check = preferred / ".writable"; check.write_text(""); check.unlink()
        return preferred
    except OSError:
        base = Path(os.environ.get("LOCALAPPDATA", Path.home()/".local"/"share")) / "Probe"
        base.mkdir(parents=True, exist_ok=True); return base

class Probe(tk.Tk):
    MAX_ROWS = 2000
    MAX_BYTES = 8 * 1024 * 1024

    def __init__(self, demo=False):
        load_fonts()
        super().__init__()
        self.title("Probe · Communications workbench")
        icon_base=Path(getattr(sys,"_MEIPASS",Path(__file__).resolve().parent.parent))
        try:
            self.icon_image=tk.PhotoImage(file=str(icon_base/"assets"/"probe.png"))
            self.iconphoto(True,self.icon_image)
        except tk.TclError:pass
        self.geometry(f"{min(1360,max(1060,self.winfo_screenwidth()-80))}x{min(900,max(700,self.winfo_screenheight()-80))}")
        self.minsize(1060,700)
        self.colors = dict(DARK)
        self.ui_font, self.display_font, self.mono = font_roles(self)
        self.font_size = 11
        self.configure(bg=self.colors["bg"])
        self.option_add("*Font", (self.ui_font, 12))
        self.style = ttk.Style(self); self.style.theme_use("clam")
        self.settings_path = data_directory() / "settings.json"
        self.profiles = {}; self.macros = []
        self.events = {}; self.order = []; self.retained_bytes = 0; self.sequence = 0
        self.queue = queue.Queue(maxsize=1024)
        self.dropped = 0; self.evicted = 0; self.pressed = False
        self.engine = None; self.active = False; self.paused = False
        self.repeat_job = None; self.sequence_job = None
        self.replay_job=None
        self.last_capture=[]
        self.simulator_model = None
        self.simulator_endpoint = ""
        self.simulator_info = tk.StringVar(value="Simulator stopped. Build or load a device model to start.")
        self.sequence_info = tk.StringVar(value="Sequence idle. Connect a transport, add steps, then Run sequence.")
        self.terminal_popup=None
        self.terminal_popout_pane=None
        self.file_cancel = threading.Event()
        self.started = 0; self.rx_total = self.tx_total = 0
        self.framers = {}; self.frame_meta = {}
        self.numeric_tail = ""; self.samples = []
        self.record_path = None; self.raw_path = None
        self.search_job = None
        self.last_error = ""
        self.inspector_offset=0
        self.manual_disconnect=False
        self.closing=False
        self.vars = {}
        defaults = dict(mode="TCP Client", host="127.0.0.1", port="9000", bind="127.0.0.1",
                        listen_port="9001", serial_port="", baud="115200", bits="8", parity="N",
                        stopbits="1", flow="None", app_port="Auto PTY" if os.name != "nt" else "COM20",
                        send_mode="Text", encoding="utf-8", ending="None", checksum="None",
                        prefix="", suffix="", interval="1000", framing="Chunks", delimiter="0A",
                        frame_size="16", gap="50", view="Text + Hex", search="", direction="All",
                        target="All clients", side="Device / upstream", profile="Default", auto="Off",
                        theme="Probe II", sequence_cycles="1", simulator_transport="TCP socket",
                        simulator_matching="Conversation order", simulator_timing="1")
        for k,v in defaults.items(): self.vars[k] = tk.StringVar(value=v)
        self.vars["dtr"] = tk.BooleanVar(value=False); self.vars["rts"] = tk.BooleanVar(value=False)
        self.vars["autoscroll"] = tk.BooleanVar(value=True)
        self.vars["repeat"] = tk.BooleanVar(value=False)
        self.vars["reconnect"] = tk.BooleanVar(value=False)
        self.vars["sequence_loop"] = tk.BooleanVar(value=False)
        self.vars["simulator_repeat"] = tk.BooleanVar(value=True)
        self._load_settings()
        if self.vars["theme"].get() == "Midnight": self.vars["theme"].set("Probe II")
        if self.vars["theme"].get() == "Light": self.colors = dict(LIGHT)
        self._style()
        self._build()
        self.compact=False
        self.bind("<Configure>",self.resized,add="+")
        self._mode_changed()
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.bind("<Control-Return>", lambda e: self.send())
        self.bind("<Control-l>", lambda e: self.clear())
        self.bind("<Control-s>", lambda e: self.export())
        self.bind("<F1>", lambda e: self.help())
        self.bind("<Control-plus>", lambda e: self.zoom(1))
        self.bind("<Control-minus>", lambda e: self.zoom(-1))
        self.after(40, self.poll)
        if demo: self.after(150, self.demo)

    def _style(self):
        c = self.colors
        s = self.style
        s.configure(".", background=c["panel"], foreground=c["text"], font=(self.ui_font,12),
                    bordercolor=c["border"], lightcolor=c["shine"], darkcolor=c["bg"])
        s.configure("TFrame", background=c["panel"])
        s.configure("TLabel", background=c["panel"], foreground=c["text"])
        s.configure("Muted.TLabel", foreground=c["muted"])
        s.configure("TButton", background=c["metal"], foreground=c["ink"], padding=(9,3), borderwidth=1,
                    relief="raised", font=(self.ui_font,11,"bold"))
        s.map("TButton", background=[("active",c["shine"])], foreground=[("disabled",c["muted"])])
        s.configure("Accent.TButton", background=c["accent"], foreground="#ffffff" if self.vars["theme"].get()=="Light" else "#1e3312", font=(self.ui_font,12,"bold"))
        s.map("Accent.TButton", background=[("active",c["accent"]),("disabled",c["border"])])
        s.configure("TEntry", fieldbackground=c["input"], foreground=c["text"], padding=3, insertcolor=c["accent"])
        s.configure("TCombobox", fieldbackground=c["input"], background=c["input"], foreground=c["text"],
                    arrowcolor=c["muted"], padding=3, selectbackground=c["select"], selectforeground=c["text"])
        s.map("TCombobox", fieldbackground=[("readonly",c["input"]),("disabled",c["panel"])],
              foreground=[("readonly",c["text"]),("disabled",c["muted"])], selectbackground=[("readonly",c["select"])])
        self.option_add("*TCombobox*Listbox.background", c["input"])
        self.option_add("*TCombobox*Listbox.foreground", c["text"])
        s.configure("TCheckbutton", background=c["panel"], foreground=c["muted"])
        s.map("TCheckbutton", background=[("active",c["panel"])])
        s.configure("Treeview", background=c["panel"], fieldbackground=c["panel"], foreground=c["text"],
                    borderwidth=1, rowheight=31, font=(self.mono,self.font_size))
        s.map("Treeview", background=[("selected",c["select"])], foreground=[("selected",c["text"])])
        s.configure("Treeview.Heading", background=c["metal"], foreground=c["ink"], relief="raised",
                    font=(self.ui_font,10,"bold"), padding=3)
        s.map("Treeview.Heading", background=[("active",c["border"])])
        s.configure("Bytes.Treeview", rowheight=25, font=(self.mono,10))
        s.configure("TNotebook", background=c["panel"], borderwidth=0)
        s.configure("TNotebook.Tab", background=c["panel"], foreground=c["muted"], padding=(14,4), font=(self.ui_font,11,"bold"))
        s.map("TNotebook.Tab", background=[("selected",c["input"])], foreground=[("selected",c["accent"])])
        s.configure("Vertical.TScrollbar", background=c["border"], troughcolor=c["panel"], borderwidth=0, arrowcolor=c["muted"])
        s.configure("TPanedwindow", background=c["bg"])

    def label(self, parent, text, size=10, bold=False, color=None, **kwargs):
        return tk.Label(parent, text=text, bg=parent.cget("bg"), fg=color or self.colors["text"],
                        font=(self.display_font,max(8,size-4)) if bold and size>=12 else
                             (self.ui_font,size+1,"bold" if bold else "normal"), **kwargs)

    def frame(self, parent, **kw): return tk.Frame(parent,bg=self.colors["panel"],**kw)

    def bezel(self, parent, **kw):
        return self.frame(parent, highlightbackground=self.colors["border"], highlightthickness=1,
                          bd=2, relief="raised", **kw)

    def combo(self, parent, key, values, width=15, callback=None, readonly=True):
        w = ttk.Combobox(parent, textvariable=self.vars[key], values=values, width=width,
                         state="readonly" if readonly else "normal")
        if callback: w.bind("<<ComboboxSelected>>", lambda e: callback())
        return w

    def text_widget(self, parent, height=4, **kw):
        c=self.colors
        return tk.Text(parent,bg=c["input"], fg=c["text"], insertbackground=c["accent"],
                       selectbackground=c["select"], relief="flat", bd=0, padx=12,pady=6,
                       height=height, width=1, font=(self.mono,self.font_size), undo=True, **kw)

    def _build(self):
        c = self.colors
        self.sidebar = self.bezel(self,width=252); self.sidebar.pack(side="left",fill="y",padx=(12,0),pady=12)
        self.sidebar.pack_propagate(False)
        brand = tk.Frame(self.sidebar,bg=c["metal"]); brand.pack(fill="x",padx=5,pady=(5,12))
        self.label(brand,"CONTROL PANEL",14,True,color=c["ink"]).pack(anchor="w",padx=12,pady=(10,3))
        self.label(brand,f"01–{len(MODES):02}  /  TRANSPORT SELECT",9,color=c["ink"]).pack(anchor="w",padx=12,pady=(0,10))
        self.nav=[]
        for i,mode in enumerate(MODES):
            button=tk.Button(self.sidebar,text=f"{i+1:02}    {mode}",anchor="w",relief="raised",bd=1,
                bg=c["panel"],fg=c["muted"],activebackground=c["select"],activeforeground=c["accent"],
                highlightthickness=0,
                padx=13,pady=7,font=(self.ui_font,12,"bold"),cursor="hand2",command=lambda m=mode:self.choose_mode(m))
            button.pack(fill="x",padx=12,pady=(0,4)); self.nav.append(button)
        self.label(self.sidebar,"ENDPOINT CONFIGURATION",9,True,color=c["blue"]).pack(anchor="w",padx=16,pady=(15,8))
        bottom=self.frame(self.sidebar); bottom.pack(side="bottom",fill="x",padx=16,pady=(0,12))
        ttk.Button(bottom,text="Help  F1",command=self.help).pack(side="left")
        ttk.Button(bottom,text="Test lab",command=self.test_lab).pack(side="right")
        self.connection_button=ttk.Button(self.sidebar,text="Connect",style="Accent.TButton",command=self.toggle)
        self.connection_button.pack(side="bottom",fill="x",padx=16,pady=(10,8))
        config_wrap=self.frame(self.sidebar);config_wrap.pack(fill="both",expand=True,padx=16)
        self.config_canvas=tk.Canvas(config_wrap,bg=c["panel"],highlightthickness=0,height=150)
        self.config_canvas.pack(side="left",fill="both",expand=True)
        config_scroll=ttk.Scrollbar(config_wrap,command=self.config_canvas.yview);config_scroll.pack(side="right",fill="y")
        self.config_canvas.configure(yscrollcommand=config_scroll.set)
        self.config_frame=self.frame(self.config_canvas)
        self.config_window=self.config_canvas.create_window((0,0),window=self.config_frame,anchor="nw")
        self.config_frame.bind("<Configure>",lambda e:self.config_canvas.configure(scrollregion=self.config_canvas.bbox("all")))
        self.config_canvas.bind("<Configure>",lambda e:self.config_canvas.itemconfigure(self.config_window,width=e.width))
        def wheel(event):
            widget=self.winfo_containing(event.x_root,event.y_root)
            if widget and str(widget).startswith(str(config_wrap)):
                step=-1 if getattr(event,"num",0)==4 else 1 if getattr(event,"num",0)==5 else -1 if event.delta>0 else 1
                self.config_canvas.yview_scroll(step,"units")
        self.bind_all("<MouseWheel>",wheel,add="+")
        self.bind_all("<Button-4>",wheel,add="+");self.bind_all("<Button-5>",wheel,add="+")
        self.rail=Rail(self,self);self.rail.pack(side="left",fill="y",padx=(3,0),pady=24)
        self.content=tk.Frame(self,bg=c["bg"]); self.content.pack(side="left",fill="both",expand=True,padx=12,pady=12)
        self.content.columnconfigure(0,weight=1);self.content.rowconfigure(3,weight=1)
        self.chassis=Chassis(self.content,self,bg=c["bg"]);self.chassis.grid(row=0,column=0,sticky="ew",pady=(0,10))
        header=tk.Frame(self.content,bg=c["bg"]); header.grid(row=1,column=0,sticky="ew",pady=(0,10))
        title=tk.Frame(header,bg=c["bg"]); title.pack(side="left")
        self.hero=self.label(title,"SIGNAL WORKSPACE",16,True);self.hero.pack(anchor="w")
        self.subtitle=self.label(title,"Inspect the link. Keep the original bytes.",10,color=c["muted"])
        self.subtitle.pack(anchor="w",pady=(3,0))
        profile=tk.Frame(header,bg=c["bg"]); profile.pack(side="right")
        self.profile_combo=self.combo(profile,"profile",list(self.profiles) or ["Default"],width=14,readonly=False)
        self.profile_combo.pack(side="left",padx=4)
        ttk.Button(profile,text="Load",command=self.load_profile).pack(side="left",padx=3)
        ttk.Button(profile,text="Save",command=self.save_profile).pack(side="left",padx=3)
        stats=tk.Frame(self.content,bg=c["bg"]); stats.grid(row=2,column=0,sticky="ew",pady=(0,10))
        self.stat_labels={}
        self.stat_headings=[]
        for index,(name,heading,color) in enumerate([("state","SESSION",c["accent"]),("tx","SENT / TX",c["blue"]),
                                   ("rx","RECEIVED / RX",c["accent"]),("uptime","UPTIME",c["muted"])]):
            stats.columnconfigure(index,weight=1,uniform="meters")
            card=self.bezel(stats); card.grid(row=0,column=index,sticky="nsew",padx=(0,7 if name!="uptime" else 0))
            heading_widget=tk.Label(card,text=heading,bg=c["metal"],fg=c["ink"],anchor="w",font=(self.ui_font,10,"bold"))
            heading_widget.pack(fill="x",padx=2,pady=(2,3),ipadx=8);self.stat_headings.append(heading_widget)
            lcd=tk.Frame(card,bg=c["lcd"]);lcd.pack(fill="both",expand=True,padx=3,pady=(0,3))
            self.stat_labels[name]=tk.Label(lcd,text="Disconnected" if name=="state" else "0 B" if name in ("tx","rx") else "00:00",
                                            bg=c["lcd"],fg=color,font=(self.mono,17),anchor="w")
            self.stat_labels[name].pack(fill="x",padx=10,pady=(4,4))
            strip=MeterStrip(lcd,self,bg=c["lcd"]);strip.pack(fill="x",padx=10,pady=(0,3))
        self.split=ttk.Panedwindow(self.content,orient="vertical"); self.split.grid(row=3,column=0,sticky="nsew")
        self.split.bind("<Configure>",lambda event:self.after_idle(self._fit_panes,event.height))
        traffic=self.bezel(self.split); self.split.add(traffic,weight=3)
        traffic.columnconfigure(0,weight=1);traffic.rowconfigure(1,weight=1)
        toolbar=self.frame(traffic); toolbar.grid(row=0,column=0,sticky="ew",padx=10,pady=6)
        self.traffic_toolbar=toolbar
        self.label(toolbar,"TRAFFIC",12,True,color=c["blue"]).pack(side="left",padx=(0,14))
        self.combo(toolbar,"direction",["All","RX","TX"],width=4,callback=self.refresh).pack(side="left",padx=(0,6))
        search=ttk.Entry(toolbar,textvariable=self.vars["search"],width=14); search.pack(side="left",padx=(0,6))
        self.vars["search"].trace_add("write",self.search_changed)
        ttk.Button(toolbar,text="Clear",width=5,command=self.clear).pack(side="right",padx=(4,0))
        ttk.Button(toolbar,text="Export",width=6,command=self.export).pack(side="right",padx=(4,0))
        self.pause_button=ttk.Button(toolbar,text="Pause",width=6,command=self.pause); self.pause_button.pack(side="right",padx=(4,0))
        self.record_button=ttk.Button(toolbar,text="● Record",width=10,command=self.record); self.record_button.pack(side="right")
        tableframe=self.frame(traffic); tableframe.grid(row=1,column=0,sticky="nsew",padx=12)
        self.table=ttk.Treeview(tableframe,columns=("id","time","dir","peer","size","payload"),show="headings",selectmode="browse",height=5)
        for col,title,width,stretch in [("id","#",46,False),("time","TIME",110,False),("dir","FLOW",55,False),
                                        ("peer","PEER",130,False),("size","BYTES",60,False),("payload","PAYLOAD",420,True)]:
            self.table.heading(col,text=title); self.table.column(col,width=width,minwidth=width if not stretch else 140,stretch=stretch)
        self.table.pack(side="left",fill="both",expand=True)
        scroll=ttk.Scrollbar(tableframe,command=self.table.yview); scroll.pack(side="right",fill="y"); self.table.configure(yscrollcommand=scroll.set)
        self.table.tag_configure("RX",foreground=c["accent"]); self.table.tag_configure("TX",foreground=c["blue"])
        self.table.bind("<<TreeviewSelect>>",lambda e:self.select_event())
        self.table.bind("<Button-3>",self.traffic_menu)
        self.table.bind("<Double-1>",lambda e:self.load_selected_payload())
        options=self.frame(traffic); options.grid(row=2,column=0,sticky="ew",padx=12,pady=(3,5))
        self.traffic_options=options
        self.history_label=self.label(options,"0 events",9,color=c["muted"],width=18,anchor="w"); self.history_label.pack(side="left")
        self.combo(options,"view",["Text + Hex","Text","Hex","Decimal"],width=11,callback=self.refresh).pack(side="left",padx=8)
        ttk.Button(options,text="Framing",command=self.framing_dialog).pack(side="right",padx=4)
        ttk.Button(options,text="Raw RX file",command=self.raw_record).pack(side="right",padx=4)
        ttk.Checkbutton(options,text="Follow",variable=self.vars["autoscroll"]).pack(side="right")
        detail=self.bezel(self.split); self.split.add(detail,weight=2)
        detailbar=self.frame(detail); detailbar.pack(fill="x",padx=12,pady=(6,4))
        self.detailbar=detailbar
        self.selection_label=self.label(detailbar,"BYTE INSPECTOR",12,True,color=c["blue"]); self.selection_label.pack(side="left")
        ttk.Button(detailbar,text="Save bytes",width=9,command=self.save_bytes).pack(side="right",padx=(5,0))
        ttk.Button(detailbar,text="Copy hex",width=8,command=self.copy_hex).pack(side="right")
        self.page_next=ttk.Button(detailbar,text="→",width=3,command=lambda:self.change_page(1));self.page_next.pack(side="right",padx=4)
        self.page_prev=ttk.Button(detailbar,text="←",width=3,command=lambda:self.change_page(-1));self.page_prev.pack(side="right")
        self.notebook=ttk.Notebook(detail); self.notebook.pack(fill="both",expand=True,padx=12,pady=(0,10))
        decoded=ttk.Frame(self.notebook); raw=ttk.Frame(self.notebook); values=ttk.Frame(self.notebook); plot=ttk.Frame(self.notebook)
        self.notebook.add(decoded,text="Decoded text"); self.notebook.add(raw,text="Hex + ASCII")
        self.notebook.add(values,text="Every byte"); self.notebook.add(plot,text="Live plot")
        self.terminal=TerminalPane(self.notebook,self)
        self.notebook.add(self.terminal,text="Terminal")
        self.decoded=self.text_widget(decoded,height=4,wrap="word"); self.decoded.pack(fill="both",expand=True)
        self.hextext=self.text_widget(raw,height=4,wrap="none"); self.hextext.pack(fill="both",expand=True)
        self.byte_table=ttk.Treeview(values,columns=("offset","hex","dec","binary","char"),show="headings",style="Bytes.Treeview",height=5)
        for key,title,width in [("offset","OFFSET",90),("hex","HEX",75),("dec","DECIMAL",80),("binary","BINARY",125),("char","ASCII / CONTROL",140)]:
            self.byte_table.heading(key,text=title); self.byte_table.column(key,width=width,anchor="center")
        self.byte_table.pack(side="left",fill="both",expand=True)
        bscroll=ttk.Scrollbar(values,command=self.byte_table.yview); bscroll.pack(side="right",fill="y"); self.byte_table.configure(yscrollcommand=bscroll.set)
        self.byte_table.bind("<<TreeviewSelect>>",lambda e:self.byte_selected())
        self.plot_canvas=tk.Canvas(plot,bg=c["input"],highlightthickness=0,height=130); self.plot_canvas.pack(fill="both",expand=True)
        self.plot_canvas.bind("<Configure>",lambda e:self.draw_plot())
        self.notebook.bind("<<NotebookTabChanged>>",self._tab_changed)
        self.vars["target"].trace_add("write",lambda *_:self.terminal.reset())
        self.put_text(self.decoded,"Choose a traffic row. Control bytes are shown as ⟨STX⟩, ⟨CR⟩ and ⟨LF⟩.\nOriginal bytes are always preserved.")
        self.put_text(self.hextext,"Offset    Hex bytes                                       ASCII\n\nSelect a row to see a byte-exact dump.")
        composer=self.bezel(self.content); composer.grid(row=4,column=0,sticky="ew",pady=(10,0));self.composer=composer
        composebar=self.frame(composer); composebar.pack(fill="x",padx=12,pady=(6,6))
        self.composebar=composebar
        self.label(composebar,"TRANSMIT",12,True,color=c["blue"]).pack(side="left",padx=(0,14))
        self.combo(composebar,"send_mode",["Text","Hex","Escaped","Decimal","Hercules"],width=8,callback=self.preview).pack(side="left",padx=(0,6))
        self.combo(composebar,"encoding",["utf-8","ascii","latin-1","cp1256","gbk","utf-16-le"],width=8,callback=self.encoding_changed).pack(side="left",padx=(0,6))
        self.combo(composebar,"ending",["None","LF","CR","CRLF"],width=5,callback=self.preview).pack(side="left")
        ttk.Button(composebar,text="Tools",width=5,command=self.tools).pack(side="right",padx=(4,0))
        ttk.Button(composebar,text="Sequences",width=9,command=self.macro_dialog).pack(side="right",padx=(4,0))
        self.file_button=ttk.Button(composebar,text="Send file",width=9,command=self.send_file); self.file_button.pack(side="right")
        payloadrow=self.frame(composer); payloadrow.pack(fill="x",padx=12)
        self.payload=self.text_widget(payloadrow,height=2,wrap="word"); self.payload.pack(side="left",fill="x",expand=True,padx=(0,10))
        self.payload.insert("1.0","Hello, Probe!")
        self.payload.bind("<<Modified>>",self.payload_changed)
        self.send_button=ttk.Button(payloadrow,text="Send  ↗\nCtrl + Enter",style="Accent.TButton",command=self.send)
        self.send_button.pack(side="right",fill="y")
        composefoot=self.frame(composer); composefoot.pack(fill="x",padx=12,pady=(6,6))
        self.preview_label=self.label(composefoot,"13 bytes · no line ending",9,color=c["muted"]); self.preview_label.pack(side="bottom",anchor="w",pady=(5,0))
        self.side_combo=self.combo(composefoot,"side",["Device / upstream","App / downstream"],width=16); self.side_combo.pack(side="right",padx=(6,0))
        self.target_combo=self.combo(composefoot,"target",["All clients"],width=14); self.target_combo.pack(side="right",padx=(6,0))
        ttk.Entry(composefoot,textvariable=self.vars["interval"],width=6).pack(side="right",padx=(3,0))
        ttk.Checkbutton(composefoot,text="Repeat (ms)",variable=self.vars["repeat"],command=self.repeat).pack(side="right")
        self.status=self.label(self.content,"Ready · TCP and Serial streams have no inherent message boundaries.",9,color=c["muted"],anchor="w")
        self.status.grid(row=5,column=0,sticky="ew",pady=(7,0))

    def _mode_changed(self):
        mode=self.vars["mode"].get(); c=self.colors
        for button,m in zip(self.nav,MODES):
            button.configure(bg=c["select"] if m==mode else c["input"],fg=c["accent"] if m==mode else c["muted"],
                             relief="sunken" if m==mode else "raised")
        for w in self.config_frame.winfo_children(): w.destroy()
        self.config_canvas.yview_moveto(0)
        self.config_controls=[]
        def field(label,key,values=None,readonly=False):
            self.label(self.config_frame,label,9,color=c["muted"]).pack(anchor="w",pady=(6,4))
            w=self.combo(self.config_frame,key,values,readonly=readonly,width=20) if values is not None else ttk.Entry(self.config_frame,textvariable=self.vars[key])
            w.pack(fill="x"); self.config_controls.append(w); return w
        if mode in ("TCP Client","TCP Proxy","UDP"):
            field("Upstream host" if mode=="TCP Proxy" else "Remote host","host")
            field("Upstream port" if mode=="TCP Proxy" else "Remote port","port")
        if mode in ("TCP Server","TCP Proxy","UDP","Serial ↔ TCP","Device Simulator"):
            field("Listen address","bind"); field("Listen port (0 = automatic)","listen_port")
        if mode == "Device Simulator":
            field("Expose device as", "simulator_transport", ["TCP socket", "Virtual serial (PTY)"], True)
            count = len(self.simulator_model.exchanges) if self.simulator_model else 0
            self.label(self.config_frame, f"{count} recorded exchanges loaded.\nNo physical device is needed.", 9,
                       color=c["muted"], wraplength=200, justify="left").pack(anchor="w", pady=8)
            ttk.Button(self.config_frame, text="Open Test lab", command=self.test_lab).pack(fill="x", pady=6)
        if "Serial" in mode:
            self.port_combo=field("Physical port / serial URL","serial_port",[],False)
            ttk.Button(self.config_frame,text="Refresh ports",command=self.refresh_ports).pack(anchor="e",pady=4)
            field("Baud rate","baud",["300","1200","2400","4800","9600","19200","38400","57600","115200","230400","460800","921600"],False)
            row=self.frame(self.config_frame); row.pack(fill="x",pady=(7,2))
            for text,key,vals in [("Bits","bits",["5","6","7","8"]),("Parity","parity",["N","E","O","M","S"]),("Stop","stopbits",["1","1.5","2"])]:
                part=self.frame(row);part.pack(side="left",fill="x",expand=True,padx=(0,3))
                self.label(part,text,8,color=c["muted"]).pack(anchor="w")
                w=self.combo(part,key,vals,width=4);w.pack(fill="x",pady=4);self.config_controls.append(w)
            field("Flow control","flow",["None","RTS/CTS","XON/XOFF","DSR/DTR"],True)
            controls=self.frame(self.config_frame);controls.pack(fill="x",pady=6)
            for key in ("dtr","rts"):
                ttk.Checkbutton(controls,text=key.upper(),variable=self.vars[key],command=lambda k=key:self.control(k)).pack(side="left")
            ttk.Button(controls,text="Break",command=lambda:self.control("break")).pack(side="right")
            self.line_label=self.label(self.config_frame,"CTS  —   DSR  —   DCD  —   RI  —",8,color=c["muted"]); self.line_label.pack(anchor="w")
            self.refresh_ports()
        if mode=="Serial Proxy":
            field("Probe-side virtual port","app_port",["Auto PTY"] if os.name!="nt" else [],False)
            hint="Linux: Auto PTY creates a port for the other app." if os.name!="nt" else "COM pair: app → COM21; Probe → COM20. Install the pair first."
            self.label(self.config_frame,hint,9,color=c["muted"],wraplength=220,justify="left").pack(anchor="w",pady=7)
        if mode=="TCP Proxy":
            self.label(self.config_frame,"Point your app at the listen address. Probe forwards both directions unchanged.",9,color=c["muted"],wraplength=220,justify="left").pack(anchor="w",pady=10)
        if mode=="USB / Serial":
            self.label(self.config_frame,"USB here means a COM / tty serial device. Use loop:// to test without hardware.",9,color=c["muted"],wraplength=220,justify="left").pack(anchor="w",pady=10)
        if mode in ("TCP Client","USB / Serial"):
            ttk.Checkbutton(self.config_frame,text="Reconnect on disconnect",variable=self.vars["reconnect"]).pack(anchor="w",pady=8)
        self.connection_button.configure(text="Start proxy" if "Proxy" in mode else "Listen" if mode in ("TCP Server","Serial ↔ TCP","UDP") else "Connect")
        if mode == "Device Simulator": self.connection_button.configure(text="Start simulator")
        self.side_combo.configure(state="readonly" if mode in ("TCP Proxy","Serial Proxy","Serial ↔ TCP") else "disabled")
        self.vars["side"].set("Device / upstream")

    def _fit_panes(self, height):
        # The terminal's preferred screen size must not squeeze traffic away.
        # This runs when the overall pane area changes, not while dragging a sash.
        if not self.closing and len(self.split.panes()) == 2:
            if self.notebook.select()==str(self.terminal):
                self.split.sashpos(0,round(height*.40))
            else:self.split.sashpos(0,min(height-155,max(185,round(height*.55))))

    def _tab_changed(self,event=None):
        if not hasattr(self,"composer"):return
        # The live terminal already has its own direct keyboard input.
        if self.notebook.select()==str(self.terminal):self.composer.grid_remove()
        else:self.composer.grid()
        self.draw_plot();self.terminal.render(force=True)
        self.after_idle(self._fit_panes,self.split.winfo_height())

    def choose_mode(self,mode):
        if self.active:
            self.set_status("Disconnect the current session before changing transport.",error=True); return
        self.vars["mode"].set(mode); self._mode_changed()

    def refresh_ports(self):
        try:
            from serial.tools import list_ports
            ports=list(list_ports.comports())
            if hasattr(self,"port_combo"):
                self.port_combo.configure(values=[p.device for p in ports]+["loop://"])
            usable=[p for p in ports if p.description != "n/a"]
            if not self.vars["serial_port"].get() and usable: self.vars["serial_port"].set(usable[0].device)
            self.set_status(" · ".join(f"{p.device}: {p.description}" for p in ports) or "No serial devices found. You can enter a port manually or use loop://.")
        except ImportError: self.set_status("Install pyserial to enable serial devices.",True)

    def values(self): return {k:v.get() for k,v in self.vars.items()}

    def validate(self,cfg):
        mode=cfg["mode"]
        if mode not in MODES: raise ValueError("Choose a supported transport mode.")
        if mode in ("TCP Client","TCP Proxy","UDP"):
            if not cfg["host"].strip(): raise ValueError("Enter a remote host.")
            p=int(cfg["port"])
            if not 1<=p<=65535: raise ValueError("Remote port must be 1–65535.")
        if mode in ("TCP Server","TCP Proxy","UDP","Serial ↔ TCP","Device Simulator"):
            p=int(cfg["listen_port"])
            if not 0<=p<=65535: raise ValueError("Listen port must be 0–65535.")
        if mode == "Device Simulator":
            from .simulation import RequestMatcher
            if not self.simulator_model: raise ValueError("Open Test lab and load a capture or build a device model first.")
            RequestMatcher(self.simulator_model, cfg["simulator_matching"] == "Conversation order", cfg["simulator_repeat"])
            scale=float(cfg["simulator_timing"])
            if not math.isfinite(scale) or not 0 <= scale <= 10: raise ValueError("Reply timing multiplier must be 0–10.")
        if "Serial" in mode:
            if not cfg["serial_port"]: raise ValueError("Choose or enter a physical serial port.")
            if int(cfg["baud"])<1: raise ValueError("Baud must be positive.")
        self.new_framer()

    def new_framer(self):
        from .codec import parse_hex
        return Framer(self.vars["framing"].get(),parse_hex(self.vars["delimiter"].get()),
                      int(self.vars["frame_size"].get()),max(1,int(self.vars["gap"].get()))/1000)

    def emit(self,event):
        try: self.queue.put_nowait(event)
        except queue.Full:
            # UI capture is a bounded rolling window. Recording happens before this queue.
            try: self.queue.get_nowait()
            except queue.Empty: pass
            self.dropped+=1
            try: self.queue.put_nowait(event)
            except queue.Full: self.dropped+=1

    def toggle(self):
        if self.active:
            self.manual_disconnect=True
            self.stop_replay()
            self.stop_repeat(); self.stop_sequence(); self.file_cancel.set()
            self.engine.stop(); self.connection_button.configure(text="Stopping…",state="disabled")
            return
        try:
            cfg=self.values(); self.validate(cfg)
            if cfg["mode"] == "Device Simulator": cfg["simulator_model"] = self.simulator_model
            if self.engine and self.engine.thread and self.engine.thread.is_alive():
                raise RuntimeError("Previous session is still stopping.")
            self.flush_frames(); self.started=time.monotonic()
            self.last_error=""
            self.manual_disconnect=False
            self.engine=Engine(self.emit)
            self.terminal.reset()
            self.apply_auto()
            if self.record_path:self.engine.record(self.record_path)
            if self.raw_path:self.engine.record(self.raw_path,raw=True)
            self.active=True
            self._lock_config(True)
            self.connection_button.configure(text="Disconnect")
            self.stat_labels["state"].configure(text="Connecting…")
            self.engine.start(cfg)
        except Exception as exc:
            self.active=False;self._lock_config(False);self.set_status(str(exc),True)

    def _lock_config(self,locked):
        for w in self.config_controls:
            if locked: w.configure(state="disabled")
            elif isinstance(w,ttk.Combobox): w.configure(state="normal")
            else: w.configure(state="normal")
        for b in self.nav: b.configure(state="disabled" if locked else "normal")

    def set_status(self,message,error=False):
        if hasattr(self,"status"): self.status.configure(text=message,fg=self.colors["red"] if error else self.colors["muted"])

    def poll(self):
        changed=False
        for _ in range(180):
            try: event=self.queue.get_nowait()
            except queue.Empty: break
            kind=event["kind"]
            if kind=="data":
                self.terminal.feed(event)
                direction=event["direction"]
                if direction=="TX": self.tx_total+=len(event["data"])
                else:
                    self.rx_total+=len(event["data"]); self.add_samples(event["data"])
                key=(direction,event["peer"])
                if key not in self.framers: self.framers[key]=self.new_framer()
                for data in self.framers[key].tick(event["time"]):
                    self.add_event({**self.frame_meta[key],"data":data});changed=True
                self.frame_meta[key]=event
                for data in self.framers[key].feed(event["data"],event["time"]):
                    self.add_event({**event,"data":data});changed=True
            elif kind=="state":
                state=event["state"]; self.stat_labels["state"].configure(text=state)
                if state=="Connected":
                    self.set_status(event.get("message","Connected"))
                    if self.vars["mode"].get() == "Device Simulator":
                        self.simulator_endpoint = event.get("message", "Simulator ready")
                        self.simulator_info.set(self.simulator_endpoint)
                    if "app_path" in event:
                        self.set_status("App-side port: "+event["app_path"]+(" · simulated device; no hardware connected." if self.vars["mode"].get()=="Device Simulator" else " · app uses this port; Probe owns the physical device."))
                        self.clipboard_clear(); self.clipboard_append(event["app_path"])
                else:
                    if self.vars["mode"].get() == "Device Simulator": self.simulator_info.set("Simulator stopped.")
                    self.flush_frames(); self.active=False; self._lock_config(False)
                    self.connection_button.configure(text="Connect",state="normal")
                    self.stop_repeat(); self.stop_sequence();self.stop_replay()
                    self.target_combo.configure(values=["All clients"]); self.vars["target"].set("All clients")
                    self.pressed=False;self.file_button.configure(text="Send file")
                    self.set_status(self.last_error or "Disconnected. Recordings closed; paths stay armed for your next connection.",bool(self.last_error))
                    mode=self.vars["mode"].get()
                    if self.vars["reconnect"].get() and not self.manual_disconnect and mode in ("TCP Client","USB / Serial"):
                        def retry(m=mode):
                            if not self.closing and not self.active and self.vars["reconnect"].get() and not self.manual_disconnect and self.vars["mode"].get()==m:self.toggle()
                        self.after(1500,retry)
            elif kind=="peers":
                peers=["All clients"]+event["peers"];self.target_combo.configure(values=peers)
                if self.vars["mode"].get() in ("TCP Client","TCP Server","TCP Proxy") and self.terminal.peer and self.terminal.peer not in event["peers"]:self.terminal.reset()
                if self.vars["target"].get() not in peers: self.vars["target"].set("All clients")
            elif kind=="lines" and hasattr(self,"line_label"):
                self.line_label.configure(text="   ".join(f"{k} {'●' if event[k] else '○'}" for k in ("CTS","DSR","DCD","RI")))
            elif kind in ("error","info"):
                if kind=="error":self.last_error=event.get("message","")
                self.set_status(event.get("message",""),kind=="error")
            elif kind=="file_done":self.pressed=False;self.file_button.configure(text="Send file")
            elif kind == "scenario":
                self.sequence_info.set(event["message"])
                self.set_status(event["message"], event["state"] == "failed")
            elif kind == "simulator":
                self.simulator_info.set(self.simulator_endpoint + " · " + event["message"])
                self.set_status(event["message"], event["state"] == "unmatched")
        now=time.monotonic()
        for key,framer in self.framers.items():
            for data in framer.tick(time.time()): self.add_event({**self.frame_meta[key],"data":data});changed=True
        self.stat_labels["tx"].configure(text=self.format_bytes(self.engine.tx if self.engine else self.tx_total))
        self.stat_labels["rx"].configure(text=self.format_bytes(self.engine.rx if self.engine else self.rx_total))
        if self.active:
            sec=int(now-self.started);self.stat_labels["uptime"].configure(text=f"{sec//60:02}:{sec%60:02}")
        suffix=f" · {self.evicted} older events evicted" if self.evicted else ""
        if self.dropped: suffix+=f" · {self.dropped} UI events dropped; use Record for full capture"
        self.history_label.configure(text=f"{len(self.order)} events"+(f" · {self.dropped} drops" if self.dropped else f" · {self.evicted} evicted" if self.evicted else ""))
        if changed and self.vars["autoscroll"].get() and not self.paused:
            items=self.table.get_children()
            if items: self.table.see(items[-1])
        if self.notebook.index(self.notebook.select())==4:self.terminal.render()
        if self.terminal_popup and self.terminal_popup.winfo_exists():self.terminal_popout_pane.render()
        self.after(40,self.poll)

    @staticmethod
    def format_bytes(n):
        if n<1024:return f"{n:,} B"
        if n<1048576:return f"{n/1024:.1f} KiB"
        return f"{n/1048576:.1f} MiB"

    def flush_frames(self):
        for key,framer in self.framers.items():
            for data in framer.flush(): self.add_event({**self.frame_meta[key],"data":data})
        self.framers.clear();self.frame_meta.clear()

    def matches(self,event):
        if self.vars["direction"].get() not in ("All",event["direction"]):return False
        term=self.vars["search"].get().lower().strip()
        if not term:return True
        if term.startswith("hex:"):
            return re.sub(r"\s","",term[4:]) in event["data"].hex()
        return term in visible(event["data"],self.vars["encoding"].get()).lower() or term in event["peer"].lower()

    def row_values(self,idx,event):
        data=event["data"]; view=self.vars["view"].get()
        text=visible(data[:512],self.vars["encoding"].get())
        hx=data[:128].hex(" ").upper()
        if view=="Text + Hex": payload=f"{text}   ·   {hx}"
        elif view=="Hex":payload=hx
        elif view=="Decimal":payload=" ".join(str(b) for b in data[:128])
        else:payload=text
        if len(data)>512:payload+=" …"
        return (idx,dt.datetime.fromtimestamp(event["time"]).strftime("%H:%M:%S.%f")[:-3],event["direction"],event["peer"],len(data),payload)

    def add_event(self,event):
        self.sequence+=1; idx=str(self.sequence)
        self.events[idx]=event;self.order.append(idx);self.retained_bytes+=len(event["data"])
        while len(self.order)>self.MAX_ROWS or self.retained_bytes>self.MAX_BYTES:
            old=self.order.pop(0);self.retained_bytes-=len(self.events.pop(old)["data"]);self.evicted+=1
            if self.table.exists(old):self.table.delete(old)
        if not self.paused and self.matches(event):
            self.table.insert("","end",iid=idx,values=self.row_values(idx,event),tags=(event["direction"],))

    def search_changed(self,*_):
        if self.search_job:self.after_cancel(self.search_job)
        self.search_job=self.after(180,self.refresh)

    def refresh(self):
        self.search_job=None
        if self.paused:return
        selected=self.table.selection()
        self.table.delete(*self.table.get_children())
        for idx in self.order:
            event=self.events[idx]
            if self.matches(event):self.table.insert("","end",iid=idx,values=self.row_values(idx,event),tags=(event["direction"],))
        if selected and self.table.exists(selected[0]):self.table.selection_set(selected[0])

    def pause(self):
        self.paused=not self.paused;self.pause_button.configure(text="Resume" if self.paused else "Pause")
        if not self.paused:self.refresh()
        if not self.paused:self.terminal.render(force=True)
        self.set_status("Display paused. Transport and recording continue." if self.paused else "Live display resumed.")

    def clear(self):
        self.events.clear();self.order.clear();self.retained_bytes=0;self.evicted=0;self.dropped=0
        self.framers.clear();self.frame_meta.clear();self.samples.clear();self.numeric_tail=""
        self.table.delete(*self.table.get_children());self.byte_table.delete(*self.byte_table.get_children())
        self.selection_label.configure(text="Byte inspector");self.put_text(self.decoded,"");self.put_text(self.hextext,"")
        self.draw_plot();self.set_status("Display cleared. Recorded files and session byte counters continue.")

    def selected(self):
        ids=self.table.selection();return self.events.get(ids[0]) if ids else None

    @staticmethod
    def put_text(widget,text):
        widget.configure(state="normal");widget.delete("1.0","end");widget.insert("1.0",text);widget.configure(state="disabled")

    def select_event(self):
        self.inspector_offset=0;self.inspect()

    def change_page(self,delta):
        event=self.selected()
        if not event:return
        last=max(0,(len(event["data"])-1)//4096*4096)
        self.inspector_offset=max(0,min(last,self.inspector_offset+delta*4096));self.inspect()

    def inspect(self):
        event=self.selected()
        if not event:return
        data=event["data"];start=self.inspector_offset;shown=data[start:start+4096]
        self.selection_label.configure(text=f"{event['direction']} · {len(data):,} bytes"+(f" · page {start//4096+1}" if len(data)>4096 else ""))
        self.page_prev.configure(state="normal" if start else "disabled")
        self.page_next.configure(state="normal" if start+len(shown)<len(data) else "disabled")
        notice=f"\n\n[Bytes {start:,}–{start+len(shown)-1:,} of {len(data):,}. Use ← / → for other pages.]" if len(data)>len(shown) else ""
        self.put_text(self.decoded,visible(shown,self.vars["encoding"].get())+notice)
        self.put_text(self.hextext,hexdump(shown,start)+notice)
        self.byte_table.delete(*self.byte_table.get_children())
        for i,b in enumerate(shown,start):
            self.byte_table.insert("","end",iid=f"b{i}",values=(f"{i:04X} ({i})",f"{b:02X}",b,f"{b:08b}",CONTROLS.get(b,chr(b) if 32<=b<127 else "—")))

    def byte_selected(self):
        event=self.selected();ids=self.byte_table.selection()
        if not event or not ids:return
        i=int(ids[0][1:]);b=event["data"][i]
        self.set_status(f"Byte at offset {i}: hex 0x{b:02X} · decimal {b} · binary {b:08b} · {CONTROLS.get(b,repr(chr(b)) if 32<=b<127 else 'non-ASCII')}")

    def copy_hex(self):
        event=self.selected()
        if event:self.clipboard_clear();self.clipboard_append(event["data"].hex(" ").upper());self.set_status("Selected payload copied as hex.")

    def save_bytes(self):
        event=self.selected()
        if not event:self.set_status("Select a traffic row first.",True);return
        path=filedialog.asksaveasfilename(parent=self,defaultextension=".bin",filetypes=[("Binary bytes","*.bin"),("All files","*")])
        if path:
            try:Path(path).write_bytes(event["data"]);self.set_status(f"Saved {len(event['data'])} exact bytes.")
            except OSError as exc:self.set_status(str(exc),True)

    def send_terminal(self,data,peer=None):
        if not self.engine or not self.engine.ready:raise RuntimeError("Connect before sending terminal keys.")
        target=self.vars["target"].get()
        if self.vars["mode"].get() in ("TCP Server","TCP Proxy") and target=="All clients":
            if peer not in self.engine.clients:raise ValueError("Select a connected peer for the terminal.")
            target=peer
        self.engine.send(data,target,self.vars["side"].get())

    def traffic_menu(self,event):
        row=self.table.identify_row(event.y)
        if row:self.table.selection_set(row)
        menu=tk.Menu(self,tearoff=False,bg=self.colors["panel"],fg=self.colors["text"])
        menu.add_command(label="Load payload into composer",command=self.load_selected_payload)
        menu.add_command(label="Copy hex",command=self.copy_hex)
        menu.add_command(label="Save exact bytes",command=self.save_bytes)
        menu.add_separator()
        menu.add_command(label="Import capture…",command=self.import_capture)
        menu.add_command(label="Replay captured traffic…",command=self.replay_capture)
        menu.add_command(label="Stop replay",command=self.stop_replay)
        menu.add_command(label="Reset byte counters",command=self.reset_counters)
        try:menu.tk_popup(event.x_root,event.y_root)
        finally:menu.grab_release()

    def load_selected_payload(self):
        event=self.selected()
        if not event:return
        self.vars["send_mode"].set("Hex");self.vars["ending"].set("None")
        for key in ("prefix","suffix"):self.vars[key].set("")
        self.vars["checksum"].set("None")
        self.payload.delete("1.0","end");self.payload.insert("1.0",event["data"].hex(" ").upper());self.preview()
        self.set_status("Exact captured payload loaded; press Send to transmit it.")

    def import_capture(self,path=None):
        if self.active:self.set_status("Disconnect before loading an offline capture.",True);return
        path=path or filedialog.askopenfilename(parent=self,filetypes=[("Probe capture","*.jsonl *.csv")])
        if not path:return
        try:
            rows=load_capture(path)
            self.clear();self.engine=None;self.terminal.reset();self.last_capture=rows
            self.tx_total=sum(len(e["data"]) for e in rows if e["direction"]=="TX")
            self.rx_total=sum(len(e["data"]) for e in rows if e["direction"]=="RX")
            self.paused=False;self.pause_button.configure(text="Pause")
            for event in rows:self.add_event(event);self.terminal.feed(event)
            self.terminal.render(force=True);self.set_status(f"Imported {len(rows)} events. No bytes were sent.")
        except Exception as exc:self.set_status(f"Import failed: {exc}",True)

    def replay_capture(self):
        if not self.engine or not self.engine.ready:self.set_status("Connect before replaying traffic.",True);return
        rows=self.last_capture or [self.events[i] for i in self.order]
        if not rows:self.set_status("Import a capture or collect traffic first.",True);return
        win=self.dialog("Replay captured traffic","440x260")
        self.label(win,"Replay exact bytes",17,True).pack(anchor="w",padx=20,pady=20)
        direction=tk.StringVar(value="TX");speed=tk.StringVar(value="1.0")
        form=self.frame(win);form.pack(fill="x",padx=20)
        self.label(form,"Captured direction").pack(anchor="w")
        ttk.Combobox(form,textvariable=direction,values=["TX","RX"],width=12,state="readonly").pack(anchor="w",pady=4)
        self.label(form,"Speed (0.1–10×)").pack(anchor="w")
        ttk.Entry(form,textvariable=speed,width=14).pack(anchor="w",pady=4)
        def run():
            try:self.start_replay(rows,float(speed.get()),direction.get());win.destroy()
            except Exception as exc:messagebox.showerror("Replay",str(exc),parent=win)
        ttk.Button(win,text="Start replay",style="Accent.TButton",command=run).pack(anchor="e",padx=20,pady=10)

    def start_replay(self,rows,speed=1.0,direction="TX"):
        plan=replay_plan(rows,speed,direction)
        if not plan:raise ValueError(f"The capture has no {direction} records.")
        if plan[-1][0]>86400:raise ValueError("Replay duration exceeds 24 hours. Split the capture first.")
        if not self.engine or not self.engine.ready:raise ValueError("Connect before replaying.")
        self.stop_replay();self.stop_repeat();self.stop_sequence()
        engine=self.engine;target=self.vars["target"].get();side=self.vars["side"].get();started=time.monotonic()
        def tick(index=0):
            self.replay_job=None
            if self.engine is not engine or not engine.ready:self.set_status("Replay stopped: connection closed.",True);return
            try:engine.send(plan[index][1],target,side)
            except Exception as exc:self.set_status(f"Replay stopped: {exc}",True);return
            if index+1==len(plan):self.set_status(f"Replay queued {len(plan)} records.");return
            delay=max(0,int((started+plan[index+1][0]-time.monotonic())*1000))
            self.replay_job=self.after(delay,lambda:tick(index+1))
        tick()

    def stop_replay(self):
        if self.replay_job:self.after_cancel(self.replay_job);self.replay_job=None

    def reset_counters(self):
        self.rx_total=self.tx_total=0
        if self.engine:self.engine.reset_counters()
        self.set_status("Byte counters reset. Captured traffic remains available.")

    def payload_bytes(self,text=None):
        return encode(self.payload.get("1.0","end-1c") if text is None else text,self.vars["send_mode"].get(),
                      self.vars["encoding"].get(),self.vars["ending"].get(),self.vars["checksum"].get(),
                      self.vars["prefix"].get(),self.vars["suffix"].get())

    def payload_changed(self,*_):
        if self.payload.edit_modified():self.payload.edit_modified(False);self.preview()

    def preview(self):
        try:
            data=self.payload_bytes()
            self.preview_label.configure(text=f"{len(data):,} bytes · {data[:12].hex(' ').upper()}{' …' if len(data)>12 else ''}",fg=self.colors["muted"])
        except Exception as exc:self.preview_label.configure(text=str(exc),fg=self.colors["red"])

    def encoding_changed(self):self.preview();self.refresh();self.inspect();self.terminal.reset()

    def send(self,text=None):
        try:
            data=self.payload_bytes(text)
            if not data:raise ValueError("Enter a payload to send.")
            if not self.engine:raise RuntimeError("Connect before sending.")
            self.engine.send(data,self.vars["target"].get(),self.vars["side"].get())
            self.set_status(f"Sending {len(data):,} bytes…")
            return True
        except Exception as exc:self.set_status(str(exc),True);self.stop_repeat();return False

    def repeat(self):
        self.stop_repeat(keep_flag=True)
        if not self.vars["repeat"].get():return
        self.stop_sequence()
        self.stop_replay()
        try:
            delay=int(self.vars["interval"].get())
            if delay<50:raise ValueError("Repeat interval must be at least 50 ms.")
            if not self.engine or not self.engine.ready:raise ValueError("Connect before starting repeat.")
        except Exception as exc:self.vars["repeat"].set(False);self.set_status(str(exc),True);return
        def tick():
            self.repeat_job=None
            if self.vars["repeat"].get() and self.send():self.repeat_job=self.after(delay,tick)
        tick()

    def stop_repeat(self,keep_flag=False):
        if self.repeat_job:self.after_cancel(self.repeat_job);self.repeat_job=None
        if not keep_flag:self.vars["repeat"].set(False)

    def control(self,name):
        if self.engine and self.engine.ready:self.engine.control(name,self.vars[name].get() if name!="break" else True)

    def send_file(self):
        if self.pressed:self.file_cancel.set();return
        if not self.engine or not self.engine.ready:self.set_status("Connect before sending a file.",True);return
        path=filedialog.askopenfilename(parent=self,title="Send file as original binary bytes")
        if not path:return
        self.file_cancel.clear();self.pressed=True;self.file_button.configure(text="Cancel file")
        engine=self.engine;target=self.vars["target"].get();side=self.vars["side"].get()
        async def transfer():
            total=0
            try:
                with open(path,"rb") as f:
                    while not self.file_cancel.is_set() and engine.ready:
                        data=await __import__("asyncio").to_thread(f.read,4096)
                        if not data:break
                        if not await engine._send(data,target,side):raise IOError("Transport rejected the file chunk.")
                        total+=len(data)
                        await __import__("asyncio").sleep(.01)
                engine.event("info",message=f"File {'cancelled' if self.file_cancel.is_set() else 'sent'}: {total:,} bytes.")
            except Exception as exc:engine.event("error",message=f"File send: {exc}")
            finally:engine.emit({"kind":"file_done","time":time.time()})
        engine.schedule(transfer())

    def record(self):
        if self.record_path:
            self.record_path=None
            if self.engine:self.engine.record()
            self.record_button.configure(text="● Record");self.set_status("Session recording stopped.");return
        path=filedialog.asksaveasfilename(parent=self,defaultextension=".jsonl",filetypes=[("Lossless session log","*.jsonl")])
        if path:
            try:
                if self.engine and self.engine.ready:self.engine.record(path)
                else:
                    with open(path,"a",encoding="utf-8"):pass
                self.record_path=path;self.record_button.configure(text="■ Recording")
                self.set_status("Recording armed: all transport chunks and metadata are saved before display filtering.")
            except OSError as exc:self.set_status(str(exc),True)

    def raw_record(self):
        if self.raw_path:
            if self.engine:self.engine.record(raw=True)
            self.raw_path=None;self.set_status("Raw RX recording stopped.");return
        path=filedialog.asksaveasfilename(parent=self,defaultextension=".bin",filetypes=[("Raw received bytes","*.bin")])
        if path:
            try:
                if self.engine and self.engine.ready:self.engine.record(path,raw=True)
                else:
                    with open(path,"ab"):pass
                self.raw_path=path;self.set_status("Raw RX recording armed. Click Raw RX file again to stop.")
            except OSError as exc:self.set_status(str(exc),True)

    def export(self):
        path=filedialog.asksaveasfilename(parent=self,defaultextension=".jsonl",filetypes=[("Session JSON Lines","*.jsonl"),("CSV","*.csv"),("Readable log","*.txt")])
        if not path:return
        try:
            rows=[self.events[i] for i in self.order]
            with open(path,"w",encoding="utf-8",newline="") as f:
                if path.lower().endswith(".csv"):
                    writer=csv.writer(f);writer.writerow(["timestamp","direction","peer","byte_count","hex","text"])
                    for e in rows:writer.writerow([dt.datetime.fromtimestamp(e["time"]).isoformat(),e["direction"],e["peer"],len(e["data"]),e["data"].hex(" ").upper(),visible(e["data"],self.vars["encoding"].get())])
                elif path.lower().endswith(".txt"):
                    for e in rows:f.write(f"{dt.datetime.fromtimestamp(e['time']).isoformat()} {e['direction']} {e['peer']} {len(e['data'])} bytes\n{hexdump(e['data'])}\n\n")
                else:
                    for e in rows:f.write(json.dumps({k:v for k,v in e.items() if k!="data"}|{"hex":e["data"].hex().upper()})+"\n")
            self.set_status(f"Exported {len(rows)} retained events (including rows hidden by the filter).")
        except OSError as exc:self.set_status(str(exc),True)

    def dialog(self,title,size="610x470"):
        win=tk.Toplevel(self);win.title(title);win.geometry(size);win.configure(bg=self.colors["panel"])
        win.transient(self);win.grab_set();return win

    def tools(self):
        win=self.dialog("Payload tools & session tools","620x630")
        self.label(win,"Build the exact bytes you need",17,True).pack(anchor="w",padx=20,pady=(20,8))
        self.label(win,"Layout: prefix + payload + checksum + suffix + line ending",10,color=self.colors["muted"]).pack(anchor="w",padx=20)
        form=self.frame(win);form.pack(fill="x",padx=20,pady=12)
        for name,key in [("Prefix (hex)","prefix"),("Suffix (hex)","suffix")]:
            self.label(form,name,9,color=self.colors["muted"]).pack(anchor="w",pady=5)
            ttk.Entry(form,textvariable=self.vars[key]).pack(fill="x")
        self.label(form,"Checksum covers prefix + payload",9,color=self.colors["muted"]).pack(anchor="w",pady=7)
        self.combo(form,"checksum",["None","SUM8","LRC8","XOR8","CRC16 Modbus","CRC16 CCITT","CRC32"],width=25).pack(anchor="w")
        self.label(win,"Automatic reply",13,True).pack(anchor="w",padx=20,pady=(14,4))
        self.label(win,"Replies once per receive chunk / UDP datagram. Disabled in proxies.\nUse framing only for display; automatic replies are not protocol aware.",9,color=self.colors["muted"],justify="left").pack(anchor="w",padx=20)
        self.combo(win,"auto",["Off","Echo received bytes","Reply with composer"],width=27).pack(anchor="w",padx=20,pady=8)
        actions=self.frame(win);actions.pack(fill="x",padx=20,pady=8)
        ttk.Button(actions,text="Import capture",command=self.import_capture).pack(side="left",padx=(0,5))
        ttk.Button(actions,text="Replay TX",command=self.replay_capture).pack(side="left",padx=5)
        ttk.Button(actions,text="Stop replay",command=self.stop_replay).pack(side="left",padx=5)
        ttk.Button(actions,text="Reset counters",command=self.reset_counters).pack(side="left",padx=5)
        def apply():
            try:
                self.payload_bytes()
                if self.vars["auto"].get()!="Off" and self.vars["mode"].get() in ("TCP Proxy","Serial Proxy","Serial ↔ TCP"):
                    raise ValueError("Automatic reply is available in direct terminal modes.")
                self.apply_auto();self.preview();win.destroy()
            except Exception as exc:messagebox.showerror("Payload tools",str(exc),parent=win)
        ttk.Button(win,text="Apply",style="Accent.TButton",command=apply).pack(anchor="e",padx=20,pady=18)

    def apply_auto(self):
        if not self.engine:return
        mode=self.vars["auto"].get()
        self.engine.echo=mode=="Echo received bytes"
        self.engine.auto_reply=self.payload_bytes() if mode=="Reply with composer" else None

    def framing_dialog(self):
        win=self.dialog("Display framing","560x360")
        self.label(win,"Turn a stream into readable rows",16,True).pack(anchor="w",padx=20,pady=20)
        self.label(win,"Grouping changes the display only. Proxy forwarding and recorded\nraw transport bytes remain unchanged. Chunks are not TCP packets.",10,color=self.colors["muted"],justify="left").pack(anchor="w",padx=20)
        form=self.frame(win);form.pack(fill="x",padx=20,pady=15)
        for label,key,values in [("Mode","framing",["Chunks","Delimiter","Fixed length","Idle gap"]),
                                  ("Delimiter (hex, included)","delimiter",None),("Fixed byte count","frame_size",None),("Idle gap (milliseconds)","gap",None)]:
            row=self.frame(form);row.pack(fill="x",pady=3)
            self.label(row,label,10).pack(side="left")
            w=self.combo(row,key,values,width=18) if values else ttk.Entry(row,textvariable=self.vars[key],width=20)
            w.pack(side="right")
        def apply():
            try:self.new_framer();self.flush_frames();win.destroy();self.set_status("Framing changed. Existing rows keep their original grouping.")
            except Exception as exc:messagebox.showerror("Framing",str(exc),parent=win)
        ttk.Button(win,text="Apply",style="Accent.TButton",command=apply).pack(anchor="e",padx=20,pady=15)

    def test_lab(self, tab=0):
        from .testlab_ui import open_lab
        return open_lab(self, tab)

    def macro_dialog(self):
        return self.test_lab(1)

    def run_sequence(self):
        from .scenario import compile_steps, integer
        self.stop_sequence(); self.stop_repeat(); self.stop_replay()
        try:
            if not self.engine or not self.engine.ready:
                raise ValueError("Connect before running a test sequence.")
            steps = compile_steps(self.macros, int(self.vars["interval"].get()))
            cycles = 0 if self.vars["sequence_loop"].get() else integer(self.vars["sequence_cycles"].get(), "Cycles", 0, 1000000)
            self.engine.start_scenario(steps, cycles, self.vars["target"].get(), self.vars["side"].get())
            self.sequence_info.set("Starting test sequence…")
            return True
        except (ValueError, RuntimeError, TypeError) as exc:
            self.sequence_info.set(str(exc)); self.set_status(str(exc), True)
            return False

    def stop_sequence(self):
        if self.sequence_job:
            self.after_cancel(self.sequence_job); self.sequence_job = None
        if self.engine: self.engine.stop_scenario()

    def import_macros(self):
        self.test_lab(1)
        self.sequence_panel.action(self.sequence_panel.load_file)

    def export_macros(self):
        self.test_lab(1)
        self.sequence_panel.action(self.sequence_panel.save_file)

    def add_samples(self,data):
        self.numeric_tail+=data.decode("ascii",errors="replace")
        lines=self.numeric_tail.split("\n");self.numeric_tail=lines.pop()[-1024:]
        for line in lines:
            try:
                values=[float(x) for x in re.split(r"[,;\s]+",line.strip()) if x]
                if values and all(math.isfinite(x) for x in values):self.samples.append(values[:4])
            except ValueError:pass
        self.samples=self.samples[-300:]
        if self.notebook.index(self.notebook.select())==3:self.draw_plot()

    def draw_plot(self):
        cv=self.plot_canvas;c=self.colors;cv.delete("all")
        w=max(100,cv.winfo_width());h=max(80,cv.winfo_height())
        if not self.samples:
            cv.create_text(20,25,text="Live numeric plot",anchor="w",fill=c["text"],font=(self.ui_font,11,"bold"))
            cv.create_text(20,52,text="Receive newline-separated numbers or CSV (up to four channels).",anchor="w",fill=c["muted"],font=(self.ui_font,9));return
        lo=min(min(x) for x in self.samples);hi=max(max(x) for x in self.samples)
        if hi==lo:hi=lo+1
        for j in range(4):
            y=15+(h-35)*j/3;cv.create_line(50,y,w-15,y,fill=c["border"])
            cv.create_text(6,y,text=f"{hi-(hi-lo)*j/3:.3g}",anchor="w",fill=c["muted"],font=(self.mono,8))
        for channel,color in enumerate([c["accent"],c["blue"],c["red"],"#c7a0fa"]):
            coords=[]
            for i,sample in enumerate(self.samples):
                if channel<len(sample):coords.extend([50+(w-65)*i/max(1,len(self.samples)-1),15+(h-35)*(hi-sample[channel])/(hi-lo)])
            if len(coords)>=4:cv.create_line(*coords,fill=color,width=2)

    def _load_settings(self):
        try:
            config=json.loads(self.settings_path.read_text(encoding="utf-8"))
            self.profiles=config.get("profiles",{});self.macros=config.get("macros",[])[:1000]
            for k,v in config.get("last",{}).items():
                if k in self.vars and k not in ("repeat","search","target","auto"):self.vars[k].set(v)
            if self.vars["mode"].get() not in MODES:self.vars["mode"].set("TCP Client")
        except (OSError,ValueError,TypeError):pass

    def save_settings(self):
        try:
            temp=self.settings_path.with_suffix(".tmp")
            temp.write_text(json.dumps({"version":1,"profiles":self.profiles,"macros":self.macros,"last":self.values()},indent=2),encoding="utf-8")
            temp.replace(self.settings_path)
        except OSError as exc:self.set_status(f"Preferences could not be saved: {exc}",True)

    def save_profile(self):
        name=self.vars["profile"].get().strip() or "Default"
        self.profiles[name]=self.values()|{"payload":self.payload.get("1.0","end-1c")}
        self.profile_combo.configure(values=list(self.profiles))
        self.save_settings();self.set_status(f"Profile saved: {name}")

    def load_profile(self):
        if self.active:self.set_status("Disconnect before loading a profile.",True);return
        profile=self.profiles.get(self.vars["profile"].get())
        if not profile:self.set_status("This profile has not been saved yet.",True);return
        for k,v in profile.items():
            if k in self.vars and k not in ("repeat","target","auto","theme"):self.vars[k].set(v)
        self.payload.delete("1.0","end");self.payload.insert("1.0",profile.get("payload",""));self._mode_changed();self.preview()

    def zoom(self,delta):
        self.font_size=max(8,min(16,self.font_size+delta));self._style()
        for w in (self.payload,self.hextext,self.decoded):w.configure(font=(self.mono,self.font_size))
        panes=[self.terminal]
        if self.terminal_popup and self.terminal_popup.winfo_exists():panes.append(self.terminal_popout_pane)
        for pane in panes:
            pane.text.configure(font=(self.mono,self.font_size));pane.tags.clear();pane.render(force=True)

    def resized(self,event):
        if event.widget is not self:return
        tight=event.height<740
        if tight!=getattr(self,"tight",False):
            self.tight=tight
            if tight:self.chassis.grid_remove()
            else:self.chassis.grid()
        compact=event.height<840
        if compact==self.compact:return
        self.compact=compact
        if compact:self.subtitle.pack_forget();self.preview_label.pack_forget()
        else:
            self.subtitle.pack(anchor="w",pady=(3,0))
            self.preview_label.pack(side="bottom",anchor="w",pady=(5,0))
        self.hero.configure(font=(self.display_font,10 if compact else 12))
        self.chassis.configure(height=46 if compact else 66)
        self.traffic_toolbar.grid_configure(pady=4 if compact else 6)
        self.detailbar.pack_configure(pady=(4,3) if compact else (6,4))
        self.composebar.pack_configure(pady=(4,4) if compact else (6,6))
        self.payload.configure(height=2)
        for label in self.stat_labels.values():
            label.configure(font=(self.mono,14 if compact else 17))
            label.pack_configure(pady=(2,2) if compact else (4,4))
        for b in self.nav:b.configure(pady=4 if compact else 7)

    def _redraw_skin(self, widget):
        if isinstance(widget,(Chassis,MeterStrip,Rail)):widget.redraw()
        for child in widget.winfo_children():self._redraw_skin(child)

    def help(self):
        win=self.dialog("Probe · Quick guide","780x620")
        text=self.text_widget(win,height=25,wrap="word");text.pack(fill="both",expand=True,padx=16,pady=16)
        self.put_text(text,f"PROBE {__version__}\n\n"
            "GET STARTED\nChoose a mode, enter its endpoint, then Connect. Type a payload and press Ctrl+Enter. Select any traffic row for text, hex, decimal and binary inspection.\n\n"
            "TCP CLIENT / SERVER\nClient connects to a device. Server accepts up to 16 clients. Choose a client or All clients before sending. Bind to 0.0.0.0 to accept LAN connections.\n\n"
            "TCP PROXY\nSet Listen to 127.0.0.1:9001 and Upstream to the real server. Point the other app to 127.0.0.1:9001. TX = app to upstream; RX = upstream to app. Each client has its own upstream connection. Binary bytes and half-close are preserved. TLS traffic remains encrypted.\n\n"
            "USB / SERIAL\nSupports COM / tty serial devices, including USB CDC and USB-to-UART adapters. Refresh lists ports. Set baud, bits, parity, stop and flow. DTR/RTS start OFF. Use loop:// for a hardware-free check; rfc2217://host:port for remote serial. Raw USB HID / bulk protocols are device-specific and not supported.\n\n"
            "SERIAL PROXY\nLinux: select Auto PTY; copy the created /dev/pts/N into your other app. Windows: install a virtual COM pair; Probe opens one end, the app opens its partner. Probe also opens the physical device. The bridge forwards bytes, not virtual-port baud changes or modem lines. Configure the physical port here.\n\n"
            "SERIAL ↔ TCP\nOne TCP app at a time talks to the physical serial device. This is a raw-byte bridge, not an RFC2217 server.\n\n"
            "PAYLOADS\nText, hex, escaped text (\\r, \\n, \\xHH), decimal bytes, encoding and line ending. Tools adds prefix, checksum and suffix. Checksum covers prefix+payload, excluding suffix and line ending. CRC16 Modbus is little-endian; CCITT is big-endian, init FFFF; CRC32 is little-endian. Send file sends its original bytes, without composer transformations.\n\n"
            "CAPTURE\nRecord streams lossless JSONL (hex+metadata) before filtering and framing. Raw RX file concatenates received bytes. Export saves the retained rolling window, including filtered rows. Display is bounded to 2000 rows / 8 MiB; the inspector pages through every byte in 4 KiB pages. Under overload, UI drops are reported; record for full capture.\n\n"
            "FRAMING / AUTOMATIC REPLIES\nTCP and serial are streams, not messages. Display by read chunk, delimiter, fixed length or idle gap. Framing never changes forwarding. Echo / composer reply runs once per receive chunk, not per protocol message. Do not enable echo at both ends.\n\n"
            "SHORTCUTS\nCtrl+Enter: send · Ctrl+L: clear · Ctrl+S: export · Ctrl +/-: font · F1: help\n\n"
            "LIVE TERMINAL\nThe Terminal tab interprets ANSI/VT-style color, cursor and screen commands while the traffic table preserves exact bytes. Enable Keyboard for direct input. Enter and Backspace are configurable; Ctrl+Shift+C/V copies/pastes. Pop out opens a larger live screen. One peer is displayed at a time.\n\n"
            "CAPTURE REPLAY\nTools or the traffic context menu can import JSONL/CSV while disconnected. Import sends nothing. Connect, then Replay TX/RX with a speed multiplier to send the captured bytes to the selected target/side. Double-click a row to load exact bytes into the composer.\n\n"
            "LEGACY PAYLOADS\nHercules mode supports #000–#255, $HH, named controls such as <CR> and <STX>, and ## / $$ / << for literal characters. LRC8 appends the negative byte sum. Open Test lab for timed test sequences.\n\n"
            "TEST LAB\nDevice simulator loads a two-direction JSONL/CSV capture or saved model. Select one recorded peer, then expose a TCP socket or Linux virtual serial PTY. Connect the other application to that endpoint; no physical device is opened. Exact requests produce recorded replies and delays. Conversation order preserves stateful responses; Match requests accepts independent commands in any order. Unmatched bytes are ignored and reported. Startup RX chatter is excluded. Dynamic fields must be modeled explicitly.\n\n"
            "TEST SEQUENCES\nAdd, edit, reorder or duplicate up to 1000 steps in Test lab. Each step has payload bytes, a delay after send/reply in milliseconds, repetition count, optional expected reply bytes and a timeout. Cycles 0 runs until stopped. Stop cancels pending waits and future sends. Import/export preserves timing. Timing is best effort, not hard real-time.\n\n"
            "VENDOR FEATURES\nHW-group proprietary UDP discovery, device IP configuration and TEA/I/O extensions are not implemented without verified protocol/SDK information. STM32 programming is intentionally outside this application's scope. See FEATURE_MATRIX.md.\n")

    def demo(self):
        self.vars["mode"].set("TCP Proxy");self._mode_changed()
        self.vars["host"].set("192.168.1.50");self.vars["port"].set("9000")
        self.stat_labels["state"].configure(text="Demo preview")
        messages=[("TX",b"\x02HELLO, TERMINAL\x03"),("RX",b"\x06READY\r\n"),
                  ("TX",bytes.fromhex("02 A4 04 50 43 30 31 B0 06 00 00 00 01 25 00 03")),
                  ("RX",b"\x02APPROVED\x1cREF=001234\x03"),("TX",b"STATUS?\r\n"),("RX",b"ONLINE | USB CDC | 115200 8N1\r\n")]
        for i,(direction,data) in enumerate(messages):self.add_event({"kind":"data","direction":direction,"peer":"#1 127.0.0.1:52184","time":time.time()+i*.16,"data":data})
        self.tx_total=sum(len(d) for dr,d in messages if dr=="TX");self.rx_total=sum(len(d) for dr,d in messages if dr=="RX")
        self.stat_labels["tx"].configure(text=self.format_bytes(self.tx_total));self.stat_labels["rx"].configure(text=self.format_bytes(self.rx_total))
        self.history_label.configure(text=f"{len(self.order)} events · demo")
        self.table.selection_set("3");self.inspect();self.notebook.select(1)
        self.vars["send_mode"].set("Hex");self.payload.delete("1.0","end");self.payload.insert("1.0","02 A4 04 50 43 30 31 B0 06 00 00 00 01 25 00 03")
        self.set_status("DEMO PREVIEW · synthetic sample traffic; no network or hardware connection is open.")

    def close(self):
        self.closing=True
        self.stop_repeat();self.stop_sequence();self.file_cancel.set();self.save_settings()
        self.stop_replay()
        if self.engine:self.engine.stop();self.engine.join(3)
        for timer in self.tk.call("after","info"):
            self.after_cancel(timer)
        self.destroy()

def main():
    import argparse
    parser=argparse.ArgumentParser(description="Probe communications workbench")
    parser.add_argument("--demo",action="store_true",help="Show synthetic traffic without opening a connection")
    parser.add_argument("--version",action="version",version=__version__)
    parser.add_argument("--self-test",action="store_true",help="Test bundled serial, PTY, network and terminal support without a display")
    parser.add_argument("--smoke-test",action="store_true",help="Open the GUI briefly and verify all transport panels")
    args=parser.parse_args()
    if args.self_test:
        from .diagnostics import self_test
        self_test()
        return
    if sys.platform=="win32":
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:pass
    app=Probe(demo=args.demo)
    if args.smoke_test:
        app.save_settings=lambda: None
        def check():
            try:
                for mode in MODES:
                    app.choose_mode(mode)
                    app.update_idletasks()
                app.test_lab()
                for tab in (0, 1):
                    app.testlab_notebook.select(tab)
                    app.update_idletasks()
                if app.terminal.error: raise RuntimeError(app.terminal.error)
            except Exception:
                app.close()
                raise
            app.close()
        app.after(300,check)
        app.report_callback_exception=lambda *error: sys.exit(1)
    app.mainloop()
