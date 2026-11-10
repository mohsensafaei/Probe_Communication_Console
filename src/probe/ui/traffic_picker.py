import tkinter as tk
from pathlib import Path
from tkinter import filedialog, ttk

from ..traffic.capture import load_capture
from ..analysis.codec import visible
from .widgets import Actions, entry, table


class TrafficPicker(tk.Toplevel,Actions):
    """One-direction, one-peer selection, with optional chunk concatenation."""
    def __init__(self,app,callback,parent=None,many=True,direction="RX",peer=""):
        super().__init__(parent or app);self.app=app;self.callback=callback;self.many=many
        self.title("Probe · Choose traffic");self.geometry("850x560");self.minsize(760,500)
        self.configure(bg=app.colors["panel"]);self.transient((parent or app).winfo_toplevel())
        self.feedback=tk.StringVar();self.direction=tk.StringVar(value=direction);self.peer=tk.StringVar(value=peer)
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
