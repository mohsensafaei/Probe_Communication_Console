"""Tk desktop UI. Standard-library widgets, no browser or Qt runtime."""
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
from .codec import encode, hexdump, Framer
from .engine import Engine, MODES
from .event_buffer import DisplayEventBuffer
from .traffic_model import TrafficHistory, DisplayFraming
from .ui.traffic import TrafficWorkspace
from .ui.layout import WorkbenchLayout
from .capture import load_capture, replay_plan
from .serial_endpoints import VirtualPair, simulator_transports
from .typography import load_fonts, font_roles
from .skin import Chassis, MeterStrip, Rail

# Probe instrument palette: blue enamel, satin edges and mint readouts.
DARK = dict(bg="#111b29", panel="#203149", input="#111f32", border="#526b84",
            text="#eef5ff", muted="#b3c6d9", accent="#a9e6bd", blue="#8bcfff",
            red="#ff9ea5", select="#365471", metal="#b6c5d4", shine="#e5edf5",
            ink="#203247", lcd="#101f2c")
LIGHT = dict(bg="#ccd7e2", panel="#edf2f7", input="#ffffff", border="#8198ae",
             text="#193049", muted="#48637b", accent="#246945", blue="#1a6197",
             red="#b42b43", select="#c9ddeb", metal="#bdcddd", shine="#f7faff",
             ink="#203247", lcd="#e0ede7")

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

class ProbeWorkspace(WorkbenchLayout, TrafficWorkspace, tk.Frame):
    MAX_ROWS = 2000
    MAX_BYTES = 8 * 1024 * 1024

    def __init__(self, master, slot=1, demo=False):
        super().__init__(master)
        self.window = master.winfo_toplevel()
        self.slot = slot
        self._jobs = set()
        self.colors = dict(DARK)
        self.ui_font, self.display_font, self.mono = self.window.fonts
        self.font_size = 11
        self.configure(bg=self.colors["bg"])
        self.option_add("*Font", (self.ui_font, 12))
        self.style = self.window.style
        self.settings_path = data_directory() / ("settings.json" if slot == 1 else f"settings-probe-{slot}.json")
        self.profiles = {}; self.macros = []
        self.history = TrafficHistory(self.MAX_ROWS, self.MAX_BYTES)
        self._shown_count=0
        self.queue = DisplayEventBuffer()
        self.dropped = 0; self.pressed = False
        self.engine = None; self.active = False; self.paused = False
        self.repeat_job = None; self.sequence_job = None
        self.replay_job=None
        self.last_capture=[]
        self.simulator_model = None
        self.simulator_endpoint = ""
        self.simulator_info = tk.StringVar(self, value="Simulator stopped. Build or load a device model to start.")
        self.sequence_info = tk.StringVar(self, value="Sequence idle. Connect a transport, add steps, then Run sequence.")
        self.sequence_values = {}
        self.terminal_popup=None
        self.terminal_popout_pane=None
        self.file_cancel = threading.Event()
        self.started = 0; self.rx_total = self.tx_total = 0
        self.display_framing = DisplayFraming(self.new_framer)
        self.record_path = None; self.raw_path = None
        self.search_job = None
        self.last_error = ""
        self.manual_disconnect=False
        self.closing=False
        self.vars = {}
        defaults = dict(mode="TCP Client", host="127.0.0.1", port="9000", bind="127.0.0.1",
                        listen_port="9001", serial_port="", baud="115200", bits="8", parity="N",
                        stopbits="1", flow="None", app_port="Auto PTY" if os.name != "nt" else "COM20",
                        app_peer_port="COM21", simulator_port="COM20", simulator_peer_port="COM21",
                        send_mode="Text", encoding="utf-8", ending="None", checksum="None",
                        prefix="", suffix="", interval="1000", framing="Chunks", delimiter="0A",
                        frame_size="16", gap="50", view="Text + Hex", search="", search_mode="Text", search_field="", direction="All",
                        target="All clients", side="Device / upstream", profile="Default", auto="Off",
                        theme="Probe Dark", sequence_cycles="1", sequence_interval="100", sequence_timing="auto",
                        sequence_advance="After interval", sequence_reply_timeout="2000", sequence_variables="{}",
                        hid_device="", plot_mode="Auto", plot_config="{}", protocol_fields="[]", simulator_transport="TCP socket",
                        simulator_matching="Conversation order", simulator_timing="1")
        for k,v in defaults.items(): self.vars[k] = tk.StringVar(self, value=v)
        self.vars["dtr"] = tk.BooleanVar(self, value=False); self.vars["rts"] = tk.BooleanVar(self, value=False)
        self.vars["autoscroll"] = tk.BooleanVar(self, value=True)
        self.vars["repeat"] = tk.BooleanVar(self, value=False)
        self.vars["reconnect"] = tk.BooleanVar(self, value=False)
        self.vars["sequence_loop"] = tk.BooleanVar(self, value=False)
        self.vars["simulator_repeat"] = tk.BooleanVar(self, value=True)
        self._load_settings()
        if self.vars["simulator_transport"].get() not in simulator_transports():
            self.vars["simulator_transport"].set("TCP socket")
        if os.name == "nt" and self.vars["app_port"].get() == "Auto PTY":
            self.vars["app_port"].set("COM20")
        if self.vars["theme"].get() in ("Midnight","Probe II"): self.vars["theme"].set("Probe Dark")
        if self.vars["theme"].get() == "Light": self.colors = dict(LIGHT)
        if self.window.probes:
            self.vars["theme"].set(self.window.probes[0].vars["theme"].get())
            self.colors = dict(self.window.probes[0].colors)
        else:
            self._style()
        self._build()
        self.compact=False
        self.bind("<Configure>",self.resized,add="+")
        self._mode_changed()
        self.after(40, self.poll)
        if demo: self.after(150, self.demo)

    def after(self, ms, func=None, *args):
        if func is None:return super().after(ms)
        def run():
            self._jobs.discard(job)
            if not self.closing:func(*args)
        job = super().after(ms, run)
        self._jobs.add(job)
        return job

    def after_cancel(self, job):
        self._jobs.discard(job)
        return super().after_cancel(job)



    def _mode_changed(self):
        mode=self.vars["mode"].get(); c=self.colors
        for button,m in zip(self.nav,MODES):
            button.configure(bg=c["select"] if m==mode else c["input"],fg=c["accent"] if m==mode else c["muted"],
                             relief="flat")
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
        if mode == "HID Monitor":
            from .hid_ui import build_panel
            build_panel(self,field)
        if mode == "Device Simulator":
            field("Expose device as", "simulator_transport", simulator_transports(), True)
            if os.name == "nt":
                field("Probe-side virtual COM", "simulator_port")
                field("Application-side partner COM", "simulator_peer_port")
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
            field("Application-side partner port", "app_peer_port")
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
        if mode == "HID Monitor":
            self.connection_button.configure(text="Start capture")
            self.composer.grid_remove()
        else:self.composer.grid()
        self.terminal.update_hint()
        self.side_combo.configure(state="readonly" if mode in ("TCP Proxy","Serial Proxy","Serial ↔ TCP") else "disabled")
        self.vars["side"].set("Device / upstream")

    def _tab_changed(self,event=None):
        if not hasattr(self,"composer") or event is not None and event.widget is not self.notebook:return
        # Keep target and injection-side selectors reachable on every page.
        self.plot.render(force=True);self.terminal.render(force=True)
        self.terminal.update_hint()
        if self.notebook.select()==str(self.terminal) and self.terminal.keyboard.get():self.terminal.text.focus_set()

    def traffic_clicked(self,event):
        if getattr(event,"state",0) & 5:return  # Ctrl/Shift extend selection; they never open Analyze.
        row=self.table.identify_row(event.y)
        if row and self.table.identify_region(event.x,event.y) in ("cell","tree"):
            self.table.selection_set(row);self.table.focus(row);self.analyze()
            return "break"

    def terminal_target_changed(self,*_):
        target=self.vars["target"].get()
        if target!=self._terminal_target and self.active:self.terminal.reset()
        self._terminal_target=target

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
        if mode in ("TCP Server","TCP Proxy","UDP","Serial ↔ TCP") or (mode == "Device Simulator" and cfg["simulator_transport"] == "TCP socket"):
            p=int(cfg["listen_port"])
            if not 0<=p<=65535: raise ValueError("Listen port must be 0–65535.")
        if mode == "Device Simulator":
            from .simulation import RequestMatcher
            if not self.simulator_model: raise ValueError("Open Test lab and load a capture or build a device model first.")
            RequestMatcher(self.simulator_model, cfg["simulator_matching"] == "Conversation order", cfg["simulator_repeat"])
            scale=float(cfg["simulator_timing"])
            if not math.isfinite(scale) or not 0 <= scale <= 10: raise ValueError("Reply timing multiplier must be 0–10.")
            if cfg["simulator_transport"] not in simulator_transports():
                raise ValueError("Choose a supported simulator transport for this operating system.")
            if cfg["simulator_transport"] == "Virtual COM pair":
                VirtualPair(cfg["simulator_port"], cfg["simulator_peer_port"]).validate()
        if mode == "Serial Proxy" and cfg["app_port"] != "Auto PTY":
            VirtualPair(cfg["app_port"], cfg["app_peer_port"]).validate(cfg["serial_port"])
        if "Serial" in mode:
            if not cfg["serial_port"]: raise ValueError("Choose or enter a physical serial port.")
            if int(cfg["baud"])<1: raise ValueError("Baud must be positive.")
        if mode == "HID Monitor":
            source=getattr(self,"hid_devices",{}).get(cfg["hid_device"])
            if not source:raise ValueError("Refresh devices, then choose a USB device before starting HID capture.")
            cfg["hid_source"]=source
            from .hid_capture import validate_source
            validate_source(source)
        self.new_framer()

    def new_framer(self):
        from .codec import parse_hex
        return Framer(self.vars["framing"].get(),parse_hex(self.vars["delimiter"].get()),
                      int(self.vars["frame_size"].get()),max(1,int(self.vars["gap"].get()))/1000)

    def emit(self,event):
        self.queue.put_nowait(event)

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
            if cfg["mode"]!="HID Monitor":self.apply_auto()
            if self.record_path:self.engine.record(self.record_path)
            if self.raw_path:self.engine.record(self.raw_path,raw=True)
            self.active=True
            self._lock_config(True)
            self.connection_button.configure(text="Stop capture" if cfg["mode"]=="HID Monitor" else "Disconnect")
            self.stat_labels["state"].configure(text="Connecting…")
            self.engine.start(cfg)
        except Exception as exc:
            if self.engine and (not self.engine.thread or not self.engine.thread.is_alive()):self.engine.stop();self.engine.join()
            self.active=False;self._lock_config(False);self.set_status(str(exc),True)

    def _lock_config(self,locked):
        for w in self.config_controls:
            if locked: w.configure(state="disabled")
            elif isinstance(w,ttk.Combobox): w.configure(state="normal")
            else: w.configure(state="normal")
        if self.vars["mode"].get()=="HID Monitor" and hasattr(self,"hid_combo"):
            self.hid_combo.configure(state="disabled" if locked else "readonly")
        for b in self.nav: b.configure(state="disabled" if locked else "normal")

    def set_status(self,message,error=False):
        if hasattr(self,"status"): self.status.configure(text=message,fg=self.colors["red"] if error else self.colors["muted"])

    def poll(self):
        changed=False
        deadline=time.perf_counter()+.008
        for _ in range(180):
            if time.perf_counter()>=deadline:break
            try: event=self.queue.get_nowait()
            except queue.Empty: break
            kind=event["kind"]
            if kind=="data":
                if event.get("_display_gap"):
                    # Never join bytes across a known display loss. The recorder
                    # receives the original stream before the display queue.
                    self.flush_frames("display data lost")
                    self.terminal.reset();self.plot.clear()
                    event={key:value for key,value in event.items() if key!="_display_gap"}
                self.terminal.feed(event)
                direction=event["direction"]
                if direction=="TX": self.tx_total+=len(event["data"])
                else:
                    self.rx_total+=len(event["data"]); self.plot.feed(event)
                ready=self.display_framing.feed(event)
                change=self.add_events(ready)
                changed=changed or bool(change.added)
            elif kind=="state":
                state=event["state"]; self.stat_labels["state"].configure(text=state)
                self.window.update_probe_title(self, state)
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
                    self.connection_button.configure(text="Start capture" if self.vars["mode"].get()=="HID Monitor" else "Connect",state="normal")
                    self.stop_repeat(); self.stop_sequence();self.stop_replay()
                    self.target_combo.configure(values=["All clients"]); self.vars["target"].set("All clients")
                    self.pressed=False;self.file_button.configure(text="Send file")
                    self.set_status(self.last_error or "Disconnected. Recordings closed; paths stay armed for your next connection.",bool(self.last_error))
                    mode=self.vars["mode"].get()
                    if self.vars["reconnect"].get() and not self.manual_disconnect and mode in ("TCP Client","USB / Serial"):
                        def retry(m=mode):
                            if not self.closing and not self.active and self.vars["reconnect"].get() and not self.manual_disconnect and self.vars["mode"].get()==m:self.toggle()
                        self.after(1500,retry)
            elif kind=="hid_devices":
                from .hid_ui import devices_received
                devices_received(self,event)
            elif kind=="peers":
                peers=["All clients"]+event["peers"];self.target_combo.configure(values=peers)
                if self.vars["target"].get() not in peers:
                    self._terminal_target="All clients";self.vars["target"].set("All clients")
            elif kind=="lines" and hasattr(self,"line_label"):
                self.line_label.configure(text="   ".join(f"{k} {'●' if event[k] else '○'}" for k in ("CTS","DSR","DCD","RI")))
            elif kind in ("error","info"):
                if kind=="error":self.last_error=event.get("message","")
                self.set_status(event.get("message",""),kind=="error")
            elif kind=="recording_error":
                self.record_path=self.raw_path=None;self.record_button.configure(text="● Record")
                self.set_status(event["message"],True)
            elif kind=="file_done":self.pressed=False;self.file_button.configure(text="Send file")
            elif kind == "scenario":
                self.sequence_info.set(event["message"])
                if "variables" in event:self.sequence_values=event["variables"]
                self.set_status(event["message"], event["state"] == "failed")
            elif kind == "simulator":
                self.simulator_info.set(self.simulator_endpoint + " · " + event["message"])
                self.set_status(event["message"], event["state"] == "unmatched")
        now=time.monotonic()
        # A UI backlog is not a wire idle gap: queued timestamps must be consumed
        # before using the wall clock to flush an incomplete display frame.
        if self.queue.empty():
            ready=self.display_framing.tick()
            self.add_events(ready);changed=changed or bool(ready)
        self.stat_labels["tx"].configure(text=self.format_bytes(self.engine.tx if self.engine else self.tx_total))
        self.stat_labels["rx"].configure(text=self.format_bytes(self.engine.rx if self.engine else self.rx_total))
        if self.active:
            sec=int(now-self.started);self.stat_labels["uptime"].configure(text=f"{sec//60:02}:{sec%60:02}")
        stats=self.queue.stats();self.dropped=stats["dropped"]
        suffix=f" · {self.dropped} display drops" if self.dropped else f" · {self.evicted} evicted" if self.evicted else ""
        if stats["dropped_controls"]:suffix+=f" · {stats['dropped_controls']} status drops"
        self.history_label.configure(text=f"{len(self.events)} events"+suffix)
        self.search_counts()
        if changed and self.vars["autoscroll"].get() and not self.paused:
            items=self.table.get_children()
            if items: self.table.see(items[-1])
        visible = self.winfo_ismapped()
        if visible and self.notebook.select()==str(self.plot):self.plot.render()
        self.terminal.update_hint()
        if visible and self.notebook.select()==str(self.terminal):self.terminal.render()
        if self.terminal_popup and self.terminal_popup.winfo_exists():self.terminal_popout_pane.update_hint();self.terminal_popout_pane.render()
        self.after(5 if not self.queue.empty() else 40,self.poll)

    @staticmethod
    def format_bytes(n):
        if n<1024:return f"{n:,} B"
        if n<1048576:return f"{n/1024:.1f} KiB"
        return f"{n/1048576:.1f} MiB"

    def flush_frames(self,reason="session ended"):
        self.add_events(self.display_framing.flush(reason))


    @staticmethod
    def put_text(widget,text):
        widget.configure(state="normal");widget.delete("1.0","end");widget.insert("1.0",text);widget.configure(state="disabled")


    def send_terminal(self,data,peer=None):
        if not self.engine or not self.engine.ready:raise RuntimeError("Connect before sending terminal keys.")
        target=self.vars["target"].get()
        if self.vars["mode"].get() in ("TCP Server","TCP Proxy") and target=="All clients":
            if peer not in self.engine.clients and len(self.engine.clients)==1:peer=next(iter(self.engine.clients))
            if peer not in self.engine.clients:raise ValueError("Select a connected peer for the terminal.")
            target=peer
        self.engine.send(data,target,self.vars["side"].get())

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
        from .analysis_ui import compare_selected
        return compare_selected(self,selection)

    def analyze(self,tab=None):
        from .analysis_ui import open_analysis
        return open_analysis(self,tab)

    def load_selected_payload(self):
        event=self.selected()
        if not event:return
        self.load_payload_bytes(event["data"])

    def load_payload_bytes(self,data):
        self.vars["send_mode"].set("Hex");self.vars["ending"].set("None")
        for key in ("prefix","suffix"):self.vars[key].set("")
        self.vars["checksum"].set("None")
        self.payload.delete("1.0","end");self.payload.insert("1.0",data.hex(" ").upper());self.preview()
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

    def encoding_changed(self):self.preview();self.refresh();self.terminal.reset()

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


    def dialog(self,title,size="610x470"):
        win=tk.Toplevel(self);win.title(title);win.geometry(size);win.configure(bg=self.colors["panel"])
        win.transient(self.winfo_toplevel());win.grab_set();return win

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

    def run_sequence(self, rows=None, cycles=None, variables=None):
        from .scenario import compile_steps, integer
        from .sequence_flow import initial_variables
        self.stop_sequence(); self.stop_repeat(); self.stop_replay()
        try:
            if not self.engine or not self.engine.ready:
                raise ValueError("Connect before running a test sequence.")
            steps = compile_steps(self.macros, int(self.vars["interval"].get())) if rows is None else compile_steps(rows, 100)
            if cycles is None:
                cycles = 0 if self.vars["sequence_loop"].get() else integer(self.vars["sequence_cycles"].get(), "Cycles", 0, 1000000)
            if variables is None:variables=initial_variables(json.loads(self.vars["sequence_variables"].get()))
            self.sequence_values={}
            self.engine.start_scenario(steps, cycles, self.vars["target"].get(), self.vars["side"].get(), variables)
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
        self.payload.configure(font=(self.mono,self.font_size))
        analysis=getattr(self,"analysis_window",None)
        if analysis is not None and analysis.winfo_exists():
            for widget in (analysis.payload.decoded,analysis.payload.hextext,analysis.protocol.hex,analysis.comparison.detail):widget.configure(font=(self.mono,self.font_size))
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
            "GET STARTED\nChoose a mode, enter its endpoint, then Connect. Type a payload and press Ctrl+Enter. Double-click a traffic row (or select it and press Enter) to open Analyze for decoded text, hex/ASCII, every byte, protocol fields and comparison. One reusable window keeps all message views together.\n\n"
            "TCP CLIENT / SERVER\nClient connects to a device. Server accepts up to 16 clients. Choose a client or All clients before sending. Bind to 0.0.0.0 to accept LAN connections.\n\n"
            "TCP PROXY\nSet Listen to 127.0.0.1:9001 and Upstream to the real server. Point the other app to 127.0.0.1:9001. TX = app to upstream; RX = upstream to app. Each client has its own upstream connection. Binary bytes and half-close are preserved. TLS traffic remains encrypted.\n\n"
            "USB / SERIAL\nSupports COM / tty serial devices, including USB CDC and USB-to-UART adapters. Refresh lists ports. Set baud, bits, parity, stop and flow. DTR/RTS start OFF. Use loop:// for a hardware-free check; rfc2217://host:port for remote serial. Use HID Monitor for read-only USB HID capture; arbitrary USB bulk terminals are not supported.\n\n"
            "SERIAL PROXY\nLinux: select Auto PTY; copy the created /dev/pts/N into your other app. Windows: install a virtual COM pair; Probe opens one end, the app opens its partner. Probe also opens the physical device. The bridge forwards bytes, not virtual-port baud changes or modem lines. Configure the physical port here.\n\n"
            "SERIAL ↔ TCP\nOne TCP app at a time talks to the physical serial device. This is a raw-byte bridge, not an RFC2217 server.\n\n"
            "PAYLOADS\nText, hex, escaped text (\\r, \\n, \\xHH), decimal bytes, encoding and line ending. Tools adds prefix, checksum and suffix. Checksum covers prefix+payload, excluding suffix and line ending. CRC16 Modbus is little-endian; CCITT is big-endian, init FFFF; CRC32 is little-endian. Send file sends its original bytes, without composer transformations.\n\n"
            "CAPTURE\nRecord streams lossless JSONL (hex+metadata) before filtering and framing. Raw RX file concatenates received bytes. Toolbar Export saves the retained rolling window, including filtered rows. Ctrl+click selects multiple messages; right-click → Export selected saves only those messages. The Hex / Decoded text choices still apply. Display is bounded to 2000 rows / 8 MiB; the inspector pages through every byte in 4 KiB pages. Under overload, UI drops are reported; record for full capture.\n\n"
            "FRAMING / AUTOMATIC REPLIES\nTCP and serial are streams, not messages. Display by read chunk, delimiter, fixed length or idle gap. Framing never changes forwarding. Echo / composer reply runs once per receive chunk, not per protocol message. Do not enable echo at both ends.\n\n"
            "SHORTCUTS\nCtrl+Enter: send · Ctrl+L: clear · Ctrl+S: export · Ctrl +/-: font · F1: help\n\n"
            "LIVE TERMINAL\nThe Terminal tab interprets ANSI/VT-style color, cursor and screen commands while the traffic table preserves exact bytes. Enable Send keyboard for direct input. Traffic, Live plot and Terminal are main workspace pages; the composer target and injection side stay visible. Enter and Backspace are configurable; Ctrl+Shift+C/V copies/pastes. Detach moves Terminal into its own window; Dock or closing that window returns it to the main workspace. One peer is displayed at a time.\n\n"
            "CAPTURE REPLAY\nTools or the traffic context menu can import JSONL/CSV while disconnected. Import sends nothing. Connect, then Replay TX/RX with a speed multiplier to send the captured bytes to the selected target/side. Double-click a row to inspect it. Use Load into composer in Analyze to explicitly load exact bytes, then Send to transmit.\n\n"
            "ANALYZE TRAFFIC\nDouble-click a traffic row to open Analyze. Decoded text, Hex + ASCII and Every byte are included there. Protocol Inspector offers Auto (JSON detection) or Raw Bytes; selecting a field highlights its bytes. Copy field path supplies a sequence selector. Analyze remembers the page you last used for that message. Right-click selected rows → Capture Diff compares the exact two selected messages; for a larger selection, choose A/B from that selection. Capture Diff also compares messages or combined same-peer/direction capture chunks, highlights changed/added/removed ranges and can ignore JSON values or byte ranges. Save comparison retains all original bytes. These tools send nothing.\n\n"
            "LIVE PLOT\nOpen the Live plot workspace page. Receive LF/CRLF-terminated RX numbers or CSV, up to four channels: 1,2 followed by LF, then 3,4 followed by LF. Choose the RX peer or automatic selection. Auto accepts numeric lines. Custom extracts a JSON field, text column, named value or fixed binary value; configure message boundaries and the RX parameter. TX-only data is not plotted. Separate peer buffers and the last 300 samples keep plotting bounded.\n\n"
            "DYNAMIC SEQUENCES\nEdit message > Response & next step: Save reply values picks JSON/TLV/byte fields and names variables; Choose next step adds conditions and next/goto/finish/fail/timeout actions. Save rules, then Save message. Insert variable adds ${name}, ${name:json} (a JSON value without surrounding quotes) or ${name:hex}. Variables defines initial values and shows latest reply values. Outgoing frame can rebuild length/checksum after substitution. Missing values stop before sending. Version 3 exports retain rules; legacy files still load.\n\n"
            "LEGACY PAYLOADS\nHercules mode supports #000–#255, $HH, named controls such as <CR> and <STX>, and ## / $$ / << for literal characters. LRC8 appends the negative byte sum. Open Test lab for timed test sequences.\n\n"
            "TEST LAB\nDevice simulator loads a two-direction JSONL/CSV capture or saved model. Select one recorded peer, then expose a TCP socket, Windows virtual COM pair or Linux virtual serial PTY. Connect the other application to that endpoint; no physical device is opened. Exact requests produce recorded replies and delays. Conversation order preserves stateful responses; Match requests accepts independent commands in any order. Unmatched bytes are ignored and reported. Startup RX chatter is excluded. Dynamic fields must be modeled explicitly.\n\n"
            "TEST SEQUENCES\nChoose messages, then Send next message: After interval or After a reply. Reply mode sends the first immediately and waits after every send, including the last, with no interval delay. Set Reply timeout; missing replies stop the run. Any nonempty incoming chunk from the destination counts, including unsolicited data. Edit message > Advanced > Expected reply can require specific hex bytes across chunks. Interval mode retains shared/individual delays and optional reply checks. Run once, Repeat a set number or Repeat until stopped. Stop cancels waits and pending sends. Save/Load preserves the effective behavior. Timing is best effort, not hard real-time.\n\n"
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
        self.table.selection_set("3")
        self.vars["send_mode"].set("Hex");self.payload.delete("1.0","end");self.payload.insert("1.0","02 A4 04 50 43 30 31 B0 06 00 00 00 01 25 00 03")
        self.set_status("DEMO PREVIEW · synthetic sample traffic; no network or hardware connection is open.")

    def shutdown(self):
        if self.closing:return True
        self.closing=True
        if hasattr(self,"hid_discovery_stop"):self.hid_discovery_stop.set()
        self.stop_repeat();self.stop_sequence();self.file_cancel.set();self.save_settings()
        self.stop_replay()
        if self.engine:
            self.set_status("Closing session and flushing queued capture data…");self.update_idletasks()
            self.engine.stop();self.engine.join(20)
            if self.engine.thread and self.engine.thread.is_alive():
                self.closing=False;self.set_status("Capture/session shutdown is still pending. Please retry closing after it finishes.",True);return False
            if self.engine.recording_error_message:messagebox.showerror("Recording incomplete",self.engine.recording_error_message,parent=self)
        for timer in tuple(self._jobs):self.after_cancel(timer)
        return True

    def close(self):
        return self.window.close_probe(self)


from .workspaces import WorkspaceWindow


class Probe(WorkspaceWindow):
    def __init__(self, demo=False):
        load_fonts()
        super().__init__(ProbeWorkspace, demo)


def main():
    import argparse
    parser=argparse.ArgumentParser(description="Probe communications workbench")
    parser.add_argument("--demo",action="store_true",help="Show synthetic traffic without opening a connection")
    parser.add_argument("--version",action="version",version=__version__)
    parser.add_argument("--self-test",action="store_true",help="Test bundled serial, PTY, network and terminal support without a display")
    parser.add_argument("--smoke-test",action="store_true",help="Open the GUI briefly and verify all transport panels")
    parser.add_argument("--diagnostic-report",type=Path,help="Write self-test/smoke-test results as JSON (also works in windowed Windows builds)")
    parser.add_argument("--hid-helper",action="store_true",help=argparse.SUPPRESS)
    parser.add_argument("--hid-port",type=int,default=0,help=argparse.SUPPRESS)
    parser.add_argument("--hid-token",default="",help=argparse.SUPPRESS)
    parser.add_argument("--hid-action",choices=("list","capture","check"),default="capture",help=argparse.SUPPRESS)
    parser.add_argument("--hid-source",default="",help=argparse.SUPPRESS)
    args=parser.parse_args()
    if args.hid_helper:
        from .hid_helper import helper_main
        helper_main(args.hid_port,args.hid_token,args.hid_action,args.hid_source)
        return
    def report(success, error=""):
        if args.diagnostic_report:
            args.diagnostic_report.write_text(json.dumps(dict(success=success, version=__version__,
                platform=sys.platform, check="self-test" if args.self_test else "smoke-test", error=error)), encoding="utf-8")
    if args.self_test:
        from .diagnostics import self_test
        try:
            self_test()
        except Exception as exc:
            report(False, str(exc))
            print(f"Self-test failed: {exc}", file=sys.stderr)
            raise SystemExit(1)
        report(True)
        return
    if args.diagnostic_report and not args.smoke_test:
        parser.error("--diagnostic-report requires --self-test or --smoke-test")
    if sys.platform=="win32":
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:pass
    try:
        app=Probe(demo=args.demo)
    except Exception as exc:
        if not args.smoke_test: raise
        report(False, str(exc))
        raise SystemExit(1)
    if args.smoke_test:
        app.current_probe.save_settings=lambda: None
        def check():
            try:
                for mode in MODES:
                    app.choose_mode(mode)
                    app.update_idletasks()
                app.test_lab()
                for tab in (0, 1):
                    app.testlab_notebook.select(tab)
                    app.update_idletasks()
                for page in (app.traffic_tab,app.plot,app.terminal):
                    app.notebook.select(page);app.update_idletasks()
                    if app.notebook.select()!=str(page):raise RuntimeError("Main workspace tab is not selectable.")
                app.plot.feed(dict(direction="RX",peer="smoke",data=b"1,2\n3,4\n"));app.plot.render(force=True)
                if not app.plot.canvas.find_withtag("curve"):raise RuntimeError("Live plot failed in bundle.")
                app.terminal.feed(dict(direction="RX",peer="smoke",data=b"READY\r\n"));app.terminal.render(force=True)
                if "READY" not in "".join(app.terminal.model.screen.display):raise RuntimeError("Terminal failed in bundle.")
                app.notebook.select(app.traffic_tab)
                for payload in (b'{"sessionId":"1"}',b'{"sessionId":"123"}'):
                    app.add_event(dict(kind="data",direction="RX",peer="smoke",time=time.time(),data=payload))
                app.table.selection_set(app.order[-1])
                analysis=app.analyze()
                app.update_idletasks()
                if not any(field.selector=="/sessionId" for field in analysis.protocol.fields):raise RuntimeError("Protocol Inspector failed in bundle.")
                if not analysis.comparison.differences:raise RuntimeError("Capture Diff failed in bundle.")
                if "123" not in analysis.payload.decoded.get("1.0","end"):raise RuntimeError("Analyze decoded text failed in bundle.")
                if not analysis.payload.byte_table.get_children():raise RuntimeError("Analyze byte views failed in bundle.")
                analysis.destroy()
                app.table.selection_set(app.order[-2:])
                comparison=app.compare_selected()
                if comparison.comparison.a!=app.events[app.order[-2]]["data"] or comparison.comparison.b!=app.events[app.order[-1]]["data"]:
                    raise RuntimeError("Selected-message Capture Diff failed in bundle.")
                if len(app.table.selection())!=2:raise RuntimeError("Traffic multi-selection changed during comparison.")
                comparison.destroy()
                simulator=app.simulator_panel
                rule=simulator.edit_rule(True)
                rule.vars["match_mode"].set("Fields");rule.update_match()
                rule.vars["fault"].set("Split");rule.update_fault()
                rule.notebook.select(1);app.update_idletasks();rule.destroy()
                framing=simulator.edit_framing();app.update_idletasks();framing.destroy()
                pane=app.sequence_panel
                app.current_probe.macros=[dict(name="Smoke template",text="${sid}",flow=dict(extract=[dict(name="sid",source="JSON",selector="sessionId")]))]
                pane.refresh();pane.open_editor(0)
                rules=pane.response_rules();rules.tabs.select(1);app.update_idletasks();rules.destroy();pane.editor.destroy()
                variables=pane.variables_dialog();app.update_idletasks();variables.destroy()
                if app.terminal.error: raise RuntimeError(app.terminal.error)
                from .diagnostics import wait_for
                primary=app.current_probe
                secondary=app.new_probe();secondary.save_settings=lambda:None
                for probe in (primary,secondary):
                    probe.choose_mode("USB / Serial");probe.vars["serial_port"].set("loop://");probe.toggle()
                wait_for(lambda:all(p.engine.ready for p in (primary,secondary)))
                primary.engine.send(b"PRIMARY");secondary.engine.send(b"SECONDARY")
                wait_for(lambda:primary.engine.rx==7 and secondary.engine.rx==9)
                app.update()
                app.close_probe(secondary)
                if not primary.engine.ready:raise RuntimeError("Closing one probe stopped another connection.")

            except Exception as exc:
                report(False, str(exc))
                app.close()
                raise SystemExit(1)
            report(True)
            app.close()
        app.after(300,check)
        app.report_callback_exception=lambda *error: sys.exit(1)
    app.mainloop()
