"""Workbench widget construction and styling; callbacks are owned by Probe."""
import tkinter as tk
from tkinter import ttk
from ..engine import MODES
from ..traffic_search import MODES as SEARCH_MODES
from ..terminal_ui import TerminalPane
from ..plot_ui import LivePlotPane
from ..skin import Chassis, MeterStrip, Rail


class WorkbenchLayout:
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
        # Clam's Button.focus element draws a dotted rectangle over the label.
        # Keep normal keyboard traversal and indicate focus with a solid border.
        s.layout("TButton", [("Button.border", {"sticky":"nswe", "border":1, "children":[
            ("Button.padding", {"sticky":"nswe", "children":[("Button.label", {"sticky":"nswe"})]})]})])
        s.map("TButton", background=[("disabled",c["panel"]),("active",c["shine"])],
              foreground=[("disabled",c["muted"])],
              bordercolor=[("!disabled","focus",c["blue"])],
              lightcolor=[("!disabled","focus",c["blue"])], darkcolor=[("!disabled","focus",c["blue"])],
              relief=[("disabled","flat"),("pressed","sunken")])
        s.configure("Accent.TButton", background=c["accent"], foreground="#ffffff" if self.vars["theme"].get()=="Light" else "#153425", font=(self.ui_font,12,"bold"))
        s.map("Accent.TButton", background=[("disabled",c["panel"]),("active",c["accent"])])
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
        s.configure("Treeview.Heading", background=c["metal"], foreground=c["ink"], relief="flat",
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
                          bd=1, relief="raised", **kw)

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
        self.label(brand,"CONNECTIONS",14,True,color=c["ink"]).pack(anchor="w",padx=12,pady=(10,3))
        self.label(brand,"Choose a transport",9,color=c["ink"]).pack(anchor="w",padx=12,pady=(0,10))
        self.nav=[]
        for i,mode in enumerate(MODES):
            button=tk.Button(self.sidebar,text=f"{i+1:02}    {mode}",anchor="w",relief="flat",bd=0,
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
        self._config_wheel = wheel
        self.rail=Rail(self,self);self.rail.pack(side="left",fill="y",padx=(4,0),pady=24)
        self.content=tk.Frame(self,bg=c["bg"]); self.content.pack(side="left",fill="both",expand=True,padx=12,pady=12)
        self.content.columnconfigure(0,weight=1);self.content.rowconfigure(3,weight=1)
        self.chassis=Chassis(self.content,self,bg=c["bg"]);self.chassis.grid(row=0,column=0,sticky="ew",pady=(0,10))
        header=tk.Frame(self.content,bg=c["bg"]); header.grid(row=1,column=0,sticky="ew",pady=(0,10))
        title=tk.Frame(header,bg=c["bg"]); title.pack(side="left")
        self.hero=self.label(title,"Signal workspace",16,True);self.hero.pack(anchor="w")
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

        self.notebook=ttk.Notebook(self.content);self.notebook.grid(row=3,column=0,sticky="nsew")
        traffic=self.bezel(self.notebook);self.traffic_tab=traffic;self.notebook.add(traffic,text="Traffic")
        traffic.columnconfigure(0,weight=1);traffic.rowconfigure(2,weight=1)
        toolbar=self.frame(traffic); toolbar.grid(row=0,column=0,sticky="ew",padx=10,pady=6)
        self.traffic_toolbar=toolbar
        self.label(toolbar,"TRAFFIC",12,True,color=c["blue"]).pack(side="left",padx=(0,14))
        self.combo(toolbar,"direction",["All","RX","TX"],width=4,callback=lambda:self.refresh(force=True)).pack(side="left",padx=(0,6))
        ttk.Button(toolbar,text="Clear",width=5,command=self.clear).pack(side="right",padx=(4,0))
        ttk.Button(toolbar,text="Export",width=6,command=self.export).pack(side="right",padx=(4,0))
        self.pause_button=ttk.Button(toolbar,text="Pause",width=6,command=self.pause); self.pause_button.pack(side="right",padx=(4,0))
        self.record_button=ttk.Button(toolbar,text="● Record",width=10,command=self.record); self.record_button.pack(side="right")
        self.searchbar=ttk.Frame(traffic);self.searchbar.grid(row=1,column=0,sticky="ew",padx=12,pady=(0,6))
        self.searchbar.columnconfigure(1,weight=1)
        self.search_mode_combo=ttk.Combobox(self.searchbar,textvariable=self.vars["search_mode"],values=SEARCH_MODES,state="readonly",width=11)
        self.search_mode_combo.grid(row=0,column=0,padx=(0,8))
        self.search_entry=ttk.Entry(self.searchbar,textvariable=self.vars["search"],width=1)
        self.search_entry.grid(row=0,column=1,sticky="ew")
        self.search_entry.bind("<Return>",lambda e:self.apply_search())
        self.search_entry.bind("<Escape>",lambda e:self.clear_search())
        self.search_button=ttk.Button(self.searchbar,text='Search',width=6,command=self.apply_search)
        self.search_button.grid(row=0,column=2,padx=(6,0))
        ttk.Button(self.searchbar,text="Reset",width=5,command=self.clear_search).grid(row=0,column=3,padx=(6,6))
        self.search_count=ttk.Label(self.searchbar,text="0 / 0",width=12,anchor="e");self.search_count.grid(row=0,column=4)
        ttk.Button(self.searchbar,text="?",width=2,command=self.search_help).grid(row=0,column=5,padx=(6,0))
        for key in ("search","search_mode"):self.vars[key].trace_add("write",self.search_changed)
        tableframe=self.frame(traffic); tableframe.grid(row=2,column=0,sticky="nsew",padx=12)
        self.table=ttk.Treeview(tableframe,columns=("id","time","dir","peer","size","payload"),show="headings",selectmode="extended",height=5)
        for col,title,width,stretch in [("id","#",46,False),("time","TIME",110,False),("dir","FLOW",55,False),
                                        ("peer","PEER",130,False),("size","BYTES",60,False),("payload","PAYLOAD",420,True)]:
            self.table.heading(col,text=title); self.table.column(col,width=width,minwidth=width if not stretch else 140,stretch=stretch)
        self.table.pack(side="left",fill="both",expand=True)
        scroll=ttk.Scrollbar(tableframe,command=self.table.yview); scroll.pack(side="right",fill="y"); self.table.configure(yscrollcommand=scroll.set)
        self.table.tag_configure("RX",foreground=c["accent"]); self.table.tag_configure("TX",foreground=c["blue"])
        self.table.bind("<Double-1>",self.traffic_clicked)
        self.table.bind("<Return>",lambda e:(self.analyze(),"break")[1])
        self.table.bind("<Button-3>",self.traffic_menu)
        self.table.bind("<Shift-F10>",lambda e:self.traffic_menu())
        self.table.bind("<Menu>",lambda e:self.traffic_menu())
        options=self.frame(traffic); options.grid(row=3,column=0,sticky="ew",padx=12,pady=(3,5))
        self.traffic_options=options
        self.history_label=self.label(options,"0 events",9,color=c["muted"],width=18,anchor="w"); self.history_label.pack(side="left")
        self.combo(options,"view",["Text + Hex","Text","Hex","Decimal"],width=11,callback=self.refresh).pack(side="left",padx=8)
        ttk.Label(options,text="Ctrl+click selects more").pack(side="left",padx=4)
        ttk.Button(options,text="Framing",command=self.framing_dialog).pack(side="right",padx=4)
        ttk.Button(options,text="Raw RX file",command=self.raw_record).pack(side="right",padx=4)
        ttk.Checkbutton(options,text="Follow",variable=self.vars["autoscroll"]).pack(side="right")
        self.plot=LivePlotPane(self.notebook,self);self.notebook.add(self.plot,text="Live plot")
        self.terminal=TerminalPane(self.notebook,self);self.notebook.add(self.terminal,text="Terminal")
        self.notebook.bind("<<NotebookTabChanged>>",self._tab_changed)
        self._terminal_target=self.vars["target"].get()
        self.vars["target"].trace_add("write",self.terminal_target_changed)
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
