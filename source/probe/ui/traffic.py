"""Traffic workspace callbacks; transport acquisition stays in Engine.

This mixin uses the widgets/state owned by Probe. Pure serialization lives in
exporting; payload filtering and comparison stay independent of Tk.
"""
import datetime as dt
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from ..codec import visible
from ..traffic_search import TrafficSearch
from ..exporting import write_export


class TrafficWorkspace:
    def search_filter(self):
        key=tuple(self.vars[k].get() for k in ("search","search_mode","search_field","encoding"))
        if getattr(self,"_search_key",None)!=key:
            self._search_key=key;self._search_filter=TrafficSearch(*key[:3],encoding=key[3])
        return self._search_filter

    def matches(self,event):
        return self.vars["direction"].get() in ("All",event["direction"]) and self.search_filter().matches(event)

    def search_counts(self):
        matcher=self.search_filter()
        self.search_count.configure(text="Invalid search" if matcher.error else f"{self._shown_count} / {len(self.order)}",foreground=self.colors["red"] if matcher.error else self.colors["muted"])

    def clear_search(self):
        self.vars["search"].set("");self.vars["search_field"].set("");self.vars["search_mode"].set("Text");self.refresh(force=True)

    def search_help(self):
        messagebox.showinfo("Search traffic", "Text: search decoded payload text or field values (case-insensitive).\nExample: APPROVED, 10000, or a device name.\n\nHex bytes: search an exact contiguous byte sequence.\nExample: A4 FF 00 or A4FF00. Use two digits per byte.\n\nJSON field: enter a path such as data.amount or /data/amount, then a value to find within it. A blank value finds messages containing that field.\n\nSearch checks the whole retained payload, including bytes hidden in the table preview. RX/TX filtering still applies. Reset or Escape clears the search; recorded files remain unchanged.\n\n"+(self.search_filter().error or "Results: shown messages / retained messages. Search also works while paused; new live rows resume after Resume."),parent=self)

    def row_values(self,idx,event,view=None,encoding=None):
        data=event["data"]; view=view if view is not None else self.vars["view"].get()
        text=visible(data[:512],encoding if encoding is not None else self.vars["encoding"].get())
        if event.get("hid"):
            fields=event["hid"].get("fields",[])
            text=event["hid"].get("report_type","HID")+" · "+(" · ".join(f"{f['field']}={f['value']}" for f in fields[:12]) or "Raw report; double-click to Analyze")
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
            if self.table.exists(old):self.table.delete(old);self._shown_count-=1
        if not self.paused and self.matches(event):
            self.table.insert("","end",iid=idx,values=self.row_values(idx,event),tags=(event["direction"],));self._shown_count+=1

    def search_changed(self,*_):
        if self.vars["search_mode"].get()=="JSON field":self.search_fieldbox.grid()
        else:self.search_fieldbox.grid_remove()
        if self.search_job:self.after_cancel(self.search_job)
        self.search_job=self.after(180,lambda:self.refresh(force=True))

    def refresh(self,force=False):
        if self.search_job:self.after_cancel(self.search_job)
        self.search_job=None
        if self.paused and not force:return
        selected=self.table.selection()
        focused=self.table.focus()
        self.table.delete(*self.table.get_children());self._shown_count=0
        matcher=self.search_filter()
        direction=self.vars["direction"].get()
        view,encoding=self.vars["view"].get(),self.vars["encoding"].get()
        for idx in self.order:
            event=self.events[idx]
            if direction in ("All",event["direction"]) and matcher.matches(event):
                self.table.insert("","end",iid=idx,values=self.row_values(idx,event,view,encoding),tags=(event["direction"],));self._shown_count+=1
        remaining=[row for row in selected if self.table.exists(row)]
        if remaining:self.table.selection_set(remaining)
        if focused and self.table.exists(focused):self.table.focus(focused)
        self.search_counts()

    def pause(self):
        self.paused=not self.paused;self.pause_button.configure(text="Resume" if self.paused else "Pause")
        if not self.paused:self.refresh()
        if not self.paused:self.terminal.render(force=True);self.plot.render(force=True)
        self.set_status("Display paused. Transport and recording continue." if self.paused else "Live display resumed.")

    def clear(self):
        self.events.clear();self.order.clear();self.retained_bytes=0;self.evicted=0;self.dropped=0
        self.framers.clear();self.frame_meta.clear();self.plot.clear()
        self.table.delete(*self.table.get_children());self._shown_count=0
        self.search_counts()
        self.set_status("Display cleared. Recorded files and session byte counters continue.")

    def selected(self):
        ids=self.table.selection();return self.events.get(ids[0]) if ids else None

    def selected_traffic(self):
        """Snapshot selected visible messages in capture order, never click order."""
        selected=set(self.table.selection())
        return tuple((key,dict(self.events[key])) for key in self.order if key in selected and key in self.events)

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

    def export(self,rows=None):
        snapshot=tuple(dict(row) for row in rows) if rows is not None else None
        if snapshot is not None and not snapshot:self.set_status("Select traffic messages first.",True);return
        win=self.dialog("Export selected traffic" if snapshot is not None else "Export traffic","470x330")
        self.label(win,"Choose what to save",17,True).pack(anchor="w",padx=20,pady=(20,12))
        scope=f"Only {len(snapshot)} selected message{'s' if len(snapshot)!=1 else ''} will be saved." if snapshot is not None else "All retained messages, including filtered rows."
        self.label(win,scope,10,color=self.colors["blue"],wraplength=420,justify="left").pack(anchor="w",padx=20,pady=(0,6))
        hex_option=tk.BooleanVar(value=True)
        text_option=tk.BooleanVar(value=True)
        ttk.Checkbutton(win,text="Hex",variable=hex_option).pack(anchor="w",padx=20,pady=5)
        ttk.Checkbutton(win,text="Decoded text",variable=text_option).pack(anchor="w",padx=20,pady=5)
        self.label(win,"Decoded text uses the current encoding.\nInclude Hex to preserve exact bytes for replay.",10,
                   color=self.colors["muted"],justify="left").pack(anchor="w",padx=20,pady=12)
        actions=self.frame(win);actions.pack(fill="x",padx=20,pady=10)
        save=ttk.Button(actions,text="Save…",style="Accent.TButton")
        def update(*_):save.configure(state="normal" if hex_option.get() or text_option.get() else "disabled")
        def choose():
            if not (hex_option.get() or text_option.get()):return
            path=filedialog.asksaveasfilename(parent=win,defaultextension=".jsonl",filetypes=[("Session JSON Lines","*.jsonl"),("CSV","*.csv"),("Readable log","*.txt")])
            if not path:return
            try:
                rows=snapshot if snapshot is not None else [self.events[i] for i in self.order]
                encoding=self.vars["encoding"].get()
                with open(path,"w",encoding="utf-8",newline="") as f:
                    write_export(f, rows, Path(path).suffix, hex_option.get(), text_option.get(), encoding)
                win.destroy()
                self.set_status(f"Exported {len(rows)} selected messages." if snapshot is not None else f"Exported {len(rows)} retained events (including rows hidden by the filter).")
            except OSError as exc:messagebox.showerror("Export",str(exc),parent=win)
        save.configure(command=choose);save.pack(side="right")
        ttk.Button(actions,text="Cancel",command=win.destroy).pack(side="right",padx=8)
        hex_option.trace_add("write",update);text_option.trace_add("write",update)
        win.bind("<Escape>",lambda _:win.destroy())
        return win
