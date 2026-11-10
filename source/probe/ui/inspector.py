import json
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, ttk

from ..codec import hexdump
from ..protocol import (
    CHECKSUMS,
    FIELD_TYPES,
    custom_fields,
    inspect_payload,
    validate_fields,
)
from .traffic_picker import TrafficPicker
from .widgets import Actions, entry, modal, table


class ProtocolPane(ttk.Frame,Actions):
    MODES=("Auto","Raw Bytes")
    def __init__(self,parent,app,data=b"",label="No message selected"):
        super().__init__(parent,padding=12);self.app=app;self.data=data;self.source=tk.StringVar(value=label)
        self.feedback=tk.StringVar();self.mode=tk.StringVar(value="Auto");self.page=0;self.fields=()
        try:self.definitions=validate_fields(json.loads(app.vars["protocol_fields"].get()))
        except (ValueError,TypeError):self.definitions=[]
        ttk.Label(self,text="Interpret the selected bytes",font=(app.ui_font,16,"bold")).pack(anchor="w")
        ttk.Label(self,textvariable=self.source,wraplength=880).pack(anchor="w",pady=4)
        bar=ttk.Frame(self);bar.pack(fill="x")
        combo=ttk.Combobox(bar,textvariable=self.mode,values=self.MODES,state="readonly",width=17);combo.pack(side="left")
        combo.bind("<<ComboboxSelected>>",lambda e:self.refresh())
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
            mode,self.fields=inspect_payload(self.data,"Raw bytes" if self.mode.get()=="Raw Bytes" else self.mode.get(),self.definitions)
            for i,field in enumerate(self.fields):self.view.insert("","end",iid=str(i),values=(field.name,field.offset,field.size,field.value,field.status),tags=(field.status,))
            note="JSON and ASCII body-length prefixes are detected automatically." if mode=="JSON" else "Raw byte view; no protocol is assumed." if mode=="Raw bytes" else "Select a field to highlight its original bytes."
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
        from ..configuration.documents import describe
        from .importing import ImportPreview
        def apply():
            fields=validate_fields(profile.get('fields'));self.mode.set('Custom fields');self.set_fields(fields)
        self.import_preview=ImportPreview(self,self.app,describe(profile,'protocol'),apply)
        return self.import_preview

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
