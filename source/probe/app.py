import asyncio

'Tk desktop UI. Standard-library widgets, no browser or Qt runtime.'
import json
import os
import queue
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox

from .codec import encode
from .engine import MODES, Engine
from .transports import MONITOR_MODES
from .event_buffer import DisplayEventBuffer
from .serial_endpoints import simulator_transports
from .settings import (
    BOOL_DEFAULTS,
    DEFAULTS,
    data_directory,
    read_settings,
    write_settings,
)
from .traffic_model import DisplayFraming, TrafficHistory
from .transports.config import display_framer
from .transports.config import validate as validate_config
from .ui.layout import WorkbenchLayout
from .ui.traffic import TrafficWorkspace
from .ui.typography import load_fonts

# Probe instrument palette: blue enamel, satin edges and mint readouts.
DARK = dict(bg="#111b29", panel="#203149", input="#111f32", border="#526b84",
            text="#eef5ff", muted="#b3c6d9", accent="#a9e6bd", blue="#8bcfff",
            red="#ff9ea5", select="#365471", metal="#b6c5d4", shine="#e5edf5",
            ink="#203247", lcd="#101f2c")
LIGHT = dict(bg="#ccd7e2", panel="#edf2f7", input="#ffffff", border="#8198ae",
             text="#193049", muted="#48637b", accent="#246945", blue="#1a6197",
             red="#b42b43", select="#c9ddeb", metal="#bdcddd", shine="#f7faff",
             ink="#203247", lcd="#e0ede7")


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
        self._applied_search = ('','Text')
        self._search_mode = 'Text'
        self._search_error = ''
        self.last_error = ""
        self.manual_disconnect=False
        self.closing=False
        self.vars = {}
        for k,v in DEFAULTS.items(): self.vars[k] = tk.StringVar(self, value=v)
        for key,value in BOOL_DEFAULTS.items():self.vars[key]=tk.BooleanVar(self,value=value)
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
        from .ui.plugin import Plugins
        self.plugins=Plugins(self)
        self.compact=False
        self.bind("<Configure>",self.resized,add="+")
        self.bind("<Map>",lambda event:self.refresh(),add="+")
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


    def _tab_changed(self,event=None):
        if not hasattr(self,"composer") or event is not None and event.widget is not self.notebook:return
        # Keep target and injection-side selectors reachable on every page.
        self.plot.render(force=True);self.terminal.render(force=True)
        self.terminal.update_hint()
        if self.notebook.select()==str(self.terminal) and self.terminal.keyboard.get():self.terminal.text.focus_set()


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
        validate_config(cfg,self.simulator_model,getattr(self,"hid_devices",{}),getattr(self,'tcp_devices',{}))

    def new_framer(self):
        return display_framer(self.values())

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
            if self.plugins.worker is None and any(e.get('enabled') and e.get('changes') for e in self.plugins.entries):
                raise ValueError('A message-changing plugin is unavailable. Fix or disable it in Plugins before connecting.')
            if cfg["mode"] == "Device Simulator": cfg["simulator_model"] = self.simulator_model
            if cfg['mode'] == 'TCP Monitor':cfg['tcp_pcap'] = getattr(self,'tcp_pcap',None)
            if self.engine and self.engine.thread and self.engine.thread.is_alive():
                raise RuntimeError("Previous session is still stopping.")
            self.flush_frames(); self.started=time.monotonic()
            self.last_error=""
            self.tcp_summary='';self.tcp_display_gap=0
            self.manual_disconnect=False
            self.engine=Engine(self.emit)
            self.engine.plugins=self.plugins.worker
            self.engine.workspace=self.slot
            self.terminal.reset()
            if cfg["mode"] not in MONITOR_MODES:self.apply_auto()
            if self.record_path:self.engine.record(self.record_path)
            if self.raw_path:self.engine.record(self.raw_path,raw=True)
            self.active=True
            self._lock_config(True)
            self.connection_button.configure(text="Stop capture" if cfg["mode"] in MONITOR_MODES else "Disconnect")
            self.stat_labels["state"].configure(text="Connecting…")
            self.engine.start(cfg)
        except Exception as exc:
            if self.engine and (not self.engine.thread or not self.engine.thread.is_alive()):self.engine.stop();self.engine.join()
            self.active=False;self._lock_config(False);self.set_status(str(exc),True)


    def set_status(self,message,error=False):
        if hasattr(self,"status"): self.status.configure(text=message,fg=self.colors["red"] if error else self.colors["muted"])

    def poll(self):
        self.plugins.poll()
        changed=False
        deadline=time.perf_counter()+.008
        for _ in range(180):
            if time.perf_counter()>=deadline:break
            try: event=self.queue.get_nowait()
            except queue.Empty: break
            kind=event["kind"]
            if kind=="data":
                if event.get("_display_gap"):
                    self.flush_frames("display data lost")
                    self.terminal.reset();self.plot.clear()
                    event={key:value for key,value in event.items() if key!="_display_gap"}
                if event.get('tcp_capture') and getattr(self,'tcp_display_gap',0):
                    event=dict(event,tcp_unreliable=True,session=f"{event['session']}:display-{self.tcp_display_gap}")
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
                    self.connection_button.configure(text="Start capture" if self.vars["mode"].get() in MONITOR_MODES else "Connect",state="normal")
                    self.stop_repeat(); self.stop_sequence();self.stop_replay()
                    self.target_combo.configure(values=["All clients"]); self.vars["target"].set("All clients")
                    self.pressed=False;self.file_button.configure(text="Send file")
                    self.set_status(self.last_error or getattr(self,'tcp_summary','') or "Disconnected. Recordings closed; paths stay armed for your next connection.",bool(self.last_error))
                    mode=self.vars["mode"].get()
                    if self.vars["reconnect"].get() and not self.manual_disconnect and mode in ("TCP Client","USB / Serial"):
                        def retry(m=mode):
                            if not self.closing and not self.active and self.vars["reconnect"].get() and not self.manual_disconnect and self.vars["mode"].get()==m:self.toggle()
                        self.after(1500,retry)
            elif kind=="hid_devices":
                from .ui.hid import devices_received
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
            elif kind == 'tcp_summary':
                self.tcp_summary=event['message'];self.set_status(self.tcp_summary)
                self.tcp_pcap=None
                if hasattr(self,'tcp_save'):self.tcp_save.configure(text='Save raw PCAP…')
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
                self.set_status(event["message"], event["state"] in ("unmatched", "error"))
        now=time.monotonic()
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
        if self.active and self.vars['mode'].get()=='TCP Monitor':self.tcp_display_gap+=1
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


    def load_payload_bytes(self,data):
        self.vars["send_mode"].set("Hex");self.vars["ending"].set("None")
        for key in ("prefix","suffix"):self.vars[key].set("")
        self.vars["checksum"].set("None")
        self.payload.delete("1.0","end");self.payload.insert("1.0",data.hex(" ").upper());self.preview()
        self.set_status("Exact captured payload loaded; press Send to transmit it.")


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
                        data=await asyncio.to_thread(f.read,4096)
                        if not data:break
                        if not await engine._send(data,target,side):raise IOError("Transport rejected the file chunk.")
                        total+=len(data)
                        await asyncio.sleep(.01)
                engine.event("info",message=f"File {'cancelled' if self.file_cancel.is_set() else 'sent'}: {total:,} bytes.")
            except Exception as exc:engine.event("error",message=f"File send: {exc}")
            finally:engine.emit({"kind":"file_done","time":time.time()})
        engine.schedule(transfer())


    def apply_auto(self):
        if not self.engine:return
        mode=self.vars["auto"].get()
        self.engine.echo=mode=="Echo received bytes"
        self.engine.auto_reply=self.payload_bytes() if mode=="Reply with composer" else None


    def test_lab(self, tab=0):
        from .ui.testlab import open_lab
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
            config=read_settings(self.settings_path)
            self.profiles=config.get("profiles",{});self.macros=config.get("macros",[])[:1000]
            for k,v in config.get("last",{}).items():
                if k in self.vars and k not in ("repeat","search","target","auto"):self.vars[k].set(v)
            if self.vars["mode"].get() not in MODES:self.vars["mode"].set("TCP Client")
            if self.vars['search_mode'].get() not in ('Text','Hex bytes'):self.vars['search_mode'].set('Text')
        except (OSError,ValueError,TypeError):pass

    def save_settings(self):
        try:
            write_settings(self.settings_path,self.values(),self.profiles,self.macros)
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
        previous=self.values()
        for k,v in profile.items():
            if k in self.vars and k not in ("repeat","target","auto","theme"):self.vars[k].set(v)
        try:
            from .plot_extract import validate
            config=json.loads(self.vars['plot_config'].get())
            config=validate(config) if config else None
            self.plugins.configure(json.loads(self.vars['plugins'].get()))
        except (ValueError,TypeError,OSError,SyntaxError,KeyError) as exc:
            for key,value in previous.items():
                if key in self.vars:self.vars[key].set(value)
            self.set_status('Profile not loaded: '+str(exc),True);return
        self.plot.config=config
        self.plot.mode.set('Custom' if config and self.vars['plot_mode'].get()=='Custom' else 'Auto')
        self.plot.clear();self.plot.describe()
        self.payload.delete("1.0","end");self.payload.insert("1.0",profile.get("payload",""));self._mode_changed();self.preview()


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
        self.plugins.close()
        for timer in tuple(self._jobs):self.after_cancel(timer)
        return True

    def close(self):
        return self.window.close_probe(self)


from .ui.workspaces import WorkspaceWindow


class Probe(WorkspaceWindow):
    def __init__(self, demo=False):
        load_fonts()
        super().__init__(ProbeWorkspace, demo)
