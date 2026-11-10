'Traffic workspace callbacks; transport acquisition stays in Engine.'
import datetime as dt
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from ..traffic.capture import load_capture, replay_plan
from ..analysis.codec import visible
from ..traffic.exporting import write_export
from ..traffic.search import MODES, TrafficSearch


class TrafficWorkspace:
    @property
    def events(self):
        return self.history.events

    @property
    def order(self):
        return tuple(self.history.events)

    @property
    def retained_bytes(self):
        return self.history.retained_bytes

    @property
    def evicted(self):
        return self.history.evicted

    def search_filter(self):
        key=(*self._applied_search,self.vars['encoding'].get())
        if getattr(self,"_search_key",None)!=key:
            self._search_key=key;self._search_filter=TrafficSearch(*key)
        return self._search_filter

    def matches(self,event):
        return self.vars["direction"].get() in ("All",event["direction"]) and self.search_filter().matches(event)

    def search_counts(self):
        matcher=self.search_filter()
        error=self._search_error or matcher.error
        self.search_count.configure(text="Invalid search" if error else f"{self._shown_count} / {len(self.events)}",foreground=self.colors["red"] if error else self.colors["muted"])

    def apply_search(self):
        query=tuple(self.vars[k].get() for k in ('search','search_mode'))
        self._search_error=TrafficSearch(*query,encoding=self.vars['encoding'].get()).error
        if self._search_error:self.search_counts();self.set_status(self._search_error,True);return
        self._applied_search=query;self.refresh(force=True)
        self.set_status('Search applied. Edit and press Search / Enter to update; Reset shows all traffic.')

    def clear_search(self):
        self._applied_search=('','Text');self._search_error=''
        self.vars["search"].set("");self.vars["search_mode"].set("Text");self.refresh(force=True)

    def search_help(self):
        messagebox.showinfo("Search traffic", "Press Search or Enter to apply. Changing the search type resets the applied search; typing alone never hides traffic. Invalid input keeps the previous results.\n\nText: search decoded payload text or field values (case-insensitive).\nExample: APPROVED, 10000, or a device name.\n\nHex bytes: search an exact contiguous byte sequence.\nExample: A4 FF 00 or A4FF00. Use two digits per byte.\n\nSearch checks the whole retained payload, including bytes hidden in the table preview. RX/TX filtering still applies. Reset or Escape clears the search; recorded files remain unchanged.\n\n"+(self._search_error or "Results: shown messages / retained messages. Search also works while paused; new live rows resume after Resume."),parent=self)

    def row_values(self,idx,event,view=None,encoding=None):
        data=event["data"]; view=view if view is not None else self.vars["view"].get()
        if view=="Hex":payload=data[:128].hex(" ").upper()
        elif view=="Decimal":payload=" ".join(str(b) for b in data[:128])
        else:
            text=visible(data[:512],encoding if encoding is not None else self.vars["encoding"].get())
            if event.get("hid"):
                fields=event["hid"].get("fields",[])
                text=event["hid"].get("report_type","HID")+" · "+(" · ".join(f"{f['field']}={f['value']}" for f in fields[:12]) or "Raw report; double-click to Analyze")
            payload=f"{text}   ·   {data[:128].hex(' ').upper()}" if view=="Text + Hex" else text
        if len(data)>512:payload+=" …"
        if event.get("display_partial"):payload+=" · [partial: "+event["display_reason"]+"]"
        if "original_hex" in event:payload=("[Blocked] " if event.get('plugin_error') else "[Modified] ")+payload
        return (idx,dt.datetime.fromtimestamp(event["time"]).strftime("%H:%M:%S.%f")[:-3],event["direction"],event["peer"],len(data),payload)

    def add_event(self,event):
        self.add_events((event,))

    def add_events(self,events):
        self.history.max_rows,self.history.max_bytes=self.MAX_ROWS,self.MAX_BYTES
        change=self.history.extend(events)
        if self.plugins.worker:
            for key in change.added:self.plugins.analyze(key,self.events[key])
        removed=tuple(key for key in change.removed if self.table.exists(key))
        if removed:self.table.delete(*removed);self._shown_count-=len(removed)
        if self.paused or not self.winfo_ismapped() or not change.added:return change
        matcher=self.search_filter()
        direction=self.vars["direction"].get()
        view,encoding=self.vars["view"].get(),self.vars["encoding"].get()
        for idx in change.added:
            event=self.events[idx]
            if direction in ("All",event["direction"]) and matcher.matches(event):
                self.table.insert("","end",iid=idx,values=self.row_values(idx,event,view,encoding),tags=(event["direction"],));self._shown_count+=1
        return change

    def search_changed(self,*_):
        mode=self.vars['search_mode'].get();self._search_error=''
        if mode not in MODES:mode='Text';self.vars['search_mode'].set(mode)
        if mode!=self._search_mode:
            filtered=self.search_filter().active
            self._search_mode=mode;self._applied_search=('','Text')
            if filtered:self.refresh(force=True)
            else:self.search_counts()
        else:self.search_counts()

    def refresh(self,force=False):
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
        self.last_capture=[]
        self.history.clear();self.queue.reset_stats();self.dropped=0
        self.plugins.results.clear();self.plugins.bytes=0
        self.display_framing.clear();self.plot.clear()
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


    def traffic_clicked(self,event):
        if getattr(event,"state",0) & 5:return  # Ctrl/Shift extend selection; they never open Analyze.
        row=self.table.identify_row(event.y)
        if row and self.table.identify_region(event.x,event.y) in ("cell","tree"):
            self.table.selection_set(row);self.table.focus(row);self.analyze()
            return "break"


    def traffic_menu(self,event=None):
        if event is not None:
            row=self.table.identify_row(event.y)
            if row:
                if row not in self.table.selection():self.table.selection_set(row)
                self.table.focus(row)
            x,y=event.x_root,event.y_root
        else:
            box=self.table.bbox(self.table.focus()) if self.table.focus() else ()
            x=self.table.winfo_rootx()+20;y=self.table.winfo_rooty()+(box[1]+box[3] if box else 20)
        self.table.focus_set()
        selection=self.selected_traffic()
        old=getattr(self,"_traffic_popup",None)
        if old and old.winfo_exists():old.destroy()
        menu=self.make_traffic_menu(selection);self._traffic_popup=menu
        try:menu.tk_popup(x,y)
        finally:menu.grab_release()
        return "break"


    def make_traffic_menu(self,selection):
        menu=tk.Menu(self,tearoff=False,bg=self.colors["panel"],fg=self.colors["text"],
                     activebackground=self.colors["select"],activeforeground=self.colors["text"],font=(self.ui_font,11))
        count=len(selection);state="normal" if count else "disabled"
        menu.add_command(label="Capture Diff…",state=state,command=lambda:self.compare_selected(selection))
        menu.add_command(label=f"Export selected ({count})…",state=state,
                         command=lambda:self.export(rows=[event for _,event in selection]))
        if count>1:return menu
        menu.add_separator()
        menu.add_command(label="Follow across probes…",state=state,command=lambda:self.window.trace_path(self))
        menu.add_command(label="Analyze message…",state=state,command=self.analyze)
        menu.add_command(label="Protocol Inspector…",state=state,command=lambda:self.analyze("Protocol"))
        menu.add_command(label="Load payload into composer",state=state,command=self.load_selected_payload)
        menu.add_command(label="Copy hex",state=state,command=self.copy_hex)
        menu.add_command(label="Save exact bytes",state=state,command=self.save_bytes)
        menu.add_separator()
        menu.add_command(label="Import capture…",command=self.import_capture)
        menu.add_command(label="Replay captured traffic…",command=self.replay_capture)
        menu.add_command(label="Stop replay",command=self.stop_replay)
        menu.add_command(label="Reset byte counters",command=self.reset_counters)
        return menu


    def compare_selected(self,selection=None):
        selection=self.selected_traffic() if selection is None else selection
        if not selection:self.set_status("Select traffic messages first.",True);return
        if len(selection)==1:return self.analyze("Compare")
        from .analysis import compare_selected
        return compare_selected(self,selection)


    def analyze(self,tab=None):
        from .analysis import open_analysis
        return open_analysis(self,tab)


    def load_selected_payload(self):
        event=self.selected()
        if not event:return
        self.load_payload_bytes(event["data"])


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
            for event in rows:self.add_event(event);self.terminal.feed(event);self.plot.feed(event)
            self.terminal.render(force=True);self.set_status(f"Imported {len(rows)} events. No bytes were sent.")
        except Exception as exc:self.set_status(f"Import failed: {exc}",True)


    def replay_capture(self):
        if not self.engine or not self.engine.ready:self.set_status("Connect before replaying traffic.",True);return
        rows=self.last_capture or [self.events[i] for i in self.order]
        if not rows:self.set_status("Import a capture or collect traffic first.",True);return
        win=self.dialog("Replay captured traffic","440x260")
        self.label(win,"Replay exact bytes",17,True).pack(anchor="w",padx=20,pady=20)
        direction=tk.StringVar(self, value="TX");speed=tk.StringVar(self, value="1.0")
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
