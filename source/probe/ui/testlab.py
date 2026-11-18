'Hardware test lab: recorded device responses and editable timed sequences.'
import json
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, ttk

from ..capture import load_capture
from ..codec import parse_hex
from ..serial_endpoints import simulator_transports
from ..simulation import (
    DeviceModel,
    Exchange,
    Reply,
    capture_peers,
    compile_capture,
    model_from_dict,
    model_to_dict,
)
from .sequence import SequencePane


def read_json(path):
    if Path(path).stat().st_size > 24 * 1024 * 1024:
        raise ValueError("File is too large (24 MiB maximum).")
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def open_lab(app, tab=0):
    existing = getattr(app, "testlab_window", None)
    if existing and existing.winfo_exists():
        existing.lift()
        app.testlab_notebook.select(tab)
        return existing
    win = tk.Toplevel(app)
    win.title("Probe · Hardware test lab")
    win.geometry("1040x720")
    win.minsize(980, 680)
    win.configure(bg=app.colors["panel"])
    head = ttk.Frame(win, padding=(16, 12))
    head.pack(fill="x")
    ttk.Label(head, text="Hardware test lab", font=(app.ui_font, 20, "bold")).pack(anchor="w")
    ttk.Label(head, text="Replace an unavailable device, or build a repeatable timing test.").pack(anchor="w")
    notebook = ttk.Notebook(win)
    notebook.pack(fill="both", expand=True, padx=16, pady=(0, 16))
    simulator = SimulatorPane(notebook, app)
    sequence = SequencePane(notebook, app)
    notebook.add(simulator, text="Device simulator")
    notebook.add(sequence, text="Test sequences")
    notebook.select(tab)
    app.testlab_window = win
    app.testlab_notebook = notebook
    app.simulator_panel = simulator
    app.sequence_panel = sequence
    return win


class Pane(ttk.Frame):
    def action(self, operation):
        try:
            operation()
        except (ValueError, KeyError, TypeError, OSError, RuntimeError) as exc:
            self.feedback.set(str(exc))

    def buttons(self, parent, items):
        bar = ttk.Frame(parent)
        bar.pack(fill="x", pady=4)
        for text, callback in items:
            ttk.Button(bar, text=text, command=lambda fn=callback: self.action(fn)).pack(side="left", padx=(0, 6))
        return bar

    def field(self, parent, label, variable, column, values=None, width=12):
        box = ttk.Frame(parent)
        box.grid(row=0, column=column, sticky="nsew", padx=(0, 10))
        ttk.Label(box, text=label).pack(anchor="w")
        widget = (ttk.Combobox(box, textvariable=variable, values=values, state="readonly", width=width)
                  if values is not None else ttk.Entry(box, textvariable=variable, width=width))
        widget.pack(fill="x", pady=(3, 0))
        return widget


class SimulatorPane(Pane):
    def __init__(self, parent, app):
        super().__init__(parent, padding=12)
        self.app = app
        self.feedback = tk.StringVar(value="New here? Try the example, then start the simulator.")
        self.rows = []
        self.peer = tk.StringVar()
        self.request_direction = tk.StringVar(value="TX")
        self.request = tk.StringVar()
        self.reply = tk.StringVar()
        self.delay = tk.StringVar(value="0")
        ttk.Label(self, text="1. Choose what the device should reply", font=(app.ui_font, 16, "bold")).pack(anchor="w")
        self.buttons(self, [("Try example", self.demo), ("Use recent traffic", self.use_history),
                            ("Open a recording…", self.load_capture_file), ("Open a saved model…", self.load_model)])
        source = self.capture_source = ttk.Frame(self)
        self.peer_combo = self.field(source, "Device in the recording", self.peer, 0, [], 30)
        self.field(source, "Requests in the recording", self.request_direction, 1, ["TX", "RX"], 8)
        ttk.Button(source, text="Use these messages", command=lambda: self.action(self.build)).grid(row=0, column=2, sticky="s")
        footer = ttk.Frame(self)
        footer.pack(side="bottom", fill="x")
        tablebox = ttk.Frame(self)
        tablebox.pack(fill="both", expand=True, pady=6)
        self.table = ttk.Treeview(tablebox, columns=("request", "reply", "delay"), show="headings", height=2, selectmode="browse")
        for name, title, width in (("request", "Request rule", 280), ("reply", "Recorded reply (hex)", 380), ("delay", "Timing / fault", 160)):
            self.table.heading(name, text=title)
            self.table.column(name, width=width)
        scrollbar = ttk.Scrollbar(tablebox, command=self.table.yview)
        scrollbar.pack(side="right", fill="y")
        self.table.pack(side="left", fill="both", expand=True)
        self.table.configure(yscrollcommand=scrollbar.set)
        self.table.bind("<<TreeviewSelect>>", lambda event: self.action(self.select))
        self.table.bind("<Double-1>", lambda event: self.action(self.edit_rule))
        self.rule_bar=self.buttons(self, [("Write a reply…", lambda: self.edit_rule(True)), ("Edit rule…", self.edit_rule),
                            ("Remove", self.remove), ("↑", lambda: self.move(-1)), ("↓", lambda: self.move(1)),
                            ("Save model…", self.save_model)])
        ttk.Label(self, textvariable=self.feedback, wraplength=900).pack(anchor="w", pady=(0,6))

        ttk.Label(footer, text="2. Choose how your app will connect", font=(app.ui_font, 16, "bold")).pack(anchor="w", pady=(6,4))
        settings = ttk.Frame(footer)
        settings.pack(fill="x")
        transport = app.vars["simulator_transport"]
        self.field(settings, "Connect via", transport, 0, simulator_transports(), 22)
        self.tcp_fields=(
            self.field(settings, "Listen address", app.vars["bind"], 1, width=18).master,
            self.field(settings, "TCP port (0 = auto)", app.vars["listen_port"], 2, width=16).master,
        )
        self.pair_settings = None
        if "Virtual COM pair" in simulator_transports():
            self.pair_settings = pair = ttk.Frame(footer)
            self.field(pair, "Probe-side virtual COM", app.vars["simulator_port"], 0, width=16)
            self.field(pair, "App-side partner COM", app.vars["simulator_peer_port"], 1, width=16)
            ttk.Label(pair, text="Install a COM pair first.\nYour app opens the partner port.").grid(row=0, column=2, padx=8, sticky="s")
            ttk.Button(pair, text="COM settings…", command=lambda: self.action(self.com_settings)).grid(row=0, column=3, sticky="s")
        self.transport_hint=tk.StringVar(self)
        self.endpoint_hint=ttk.Label(footer,textvariable=self.transport_hint,wraplength=900)
        self.endpoint_hint.pack(anchor="w",pady=4)

        row = ttk.Frame(footer)
        row.pack(fill="x", pady=6)
        advanced = ttk.Frame(footer)
        show_advanced=tk.BooleanVar(self)
        ttk.Checkbutton(row,text="Advanced options",variable=show_advanced,
                        command=lambda:advanced.pack(fill="x",before=row,pady=4) if show_advanced.get() else advanced.pack_forget()).pack(side="left")
        self.field(advanced, "Matching", app.vars["simulator_matching"], 0, ["Conversation order", "Match requests"], 21)
        self.field(advanced, "Reply timing ×", app.vars["simulator_timing"], 1, width=6)
        ttk.Checkbutton(advanced, text="Repeat conversation", variable=app.vars["simulator_repeat"]).grid(row=0,column=2,sticky="s",padx=(0,8))
        ttk.Button(advanced,text="Request framing…",command=lambda:self.action(self.edit_framing)).grid(row=0,column=3,sticky="s",padx=(0,6))
        ttk.Button(advanced,text="Reset matching",command=self.reset).grid(row=0,column=4,sticky="s")
        self.framing_info = tk.StringVar()
        ttk.Label(advanced,textvariable=self.framing_info,wraplength=900).grid(row=1,columnspan=5,sticky="w",pady=(4,0))
        self.start_button=ttk.Button(row,text="Start simulator",style="Accent.TButton",
                                     command=lambda:self.action(self.stop if self.running() else self.start))
        self.start_button.pack(side="right")
        self.copy_button=ttk.Button(row,text="Copy address",command=self.copy_address)
        ttk.Label(footer, textvariable=app.simulator_info, wraplength=900).pack(anchor="w", pady=2)
        self.example_hint=ttk.Label(footer,text="Send PING + CRLF   ·   Expected reply: PONG + CRLF")
        traces=[(var,var.trace_add("write",lambda *_, fn=fn:fn())) for var,fn in
                ((transport,self.show_transport),(app.simulator_info,self.update_actions))]
        self.bind("<Destroy>",lambda e:[v.trace_remove("write",t) for v,t in traces] if e.widget is self else None,add="+")
        self.show_transport()
        self.refresh()

    def show_transport(self):
        mode=self.app.vars["simulator_transport"].get()
        tcp=mode=="TCP socket"
        for field in self.tcp_fields:
            if tcp:field.grid()
            else:field.grid_remove()
        if self.pair_settings:
            if mode=="Virtual COM pair":self.pair_settings.pack(fill="x",before=self.endpoint_hint)
            else:self.pair_settings.pack_forget()
        self.transport_hint.set("Use the address shown below after starting." if tcp else
                                "Use the virtual port shown below after starting.")
        self.copy_button.configure(text="Copy address" if tcp else "Copy port")

    def running(self):
        return self.app.active and self.app.vars["mode"].get()=="Device Simulator"

    def update_actions(self):
        running=self.running()
        states=(running,bool(self.app.simulator_model),bool(self.app.simulator_address))
        if states==getattr(self,"action_states",None):return
        self.action_states=states
        self.start_button.configure(text="Stop simulator" if running else "Start simulator",
                                    style="TButton" if running else "Accent.TButton")
        self.start_button.state(("!disabled" if running or self.app.simulator_model else "disabled",))
        if self.app.simulator_address:self.copy_button.pack(side="right",padx=(0,6))
        else:self.copy_button.pack_forget()

    def copy_address(self):
        if self.app.simulator_address:
            self.clipboard_clear()
            self.clipboard_append(self.app.simulator_address)
            self.feedback.set("Address copied. Use it in the app you want to test.")

    def edit_rule(self, new=False):
        self.ensure_editable()
        from .simulator import RuleEditor
        self.rule_editor = RuleEditor(self, None if new else self.selected_index())
        return self.rule_editor

    def edit_framing(self):
        self.ensure_editable()
        from .simulator import FrameEditor
        self.frame_editor = FrameEditor(self)
        return self.frame_editor

    def com_settings(self):
        if self.app.active:
            raise ValueError("Disconnect before changing COM line settings.")
        win = self.app.dialog("Virtual COM line settings", "460x440")
        for label, key, values in (("Baud rate", "baud", None), ("Data bits", "bits", ["5", "6", "7", "8"]),
                                   ("Parity", "parity", ["N", "E", "O", "M", "S"]),
                                   ("Stop bits", "stopbits", ["1", "1.5", "2"]),
                                   ("Flow control", "flow", ["None", "RTS/CTS", "XON/XOFF", "DSR/DTR"])):
            row = ttk.Frame(win)
            row.pack(fill="x", padx=16, pady=6)
            self.field(row, label, self.app.vars[key], 0, values, 26)
        ttk.Label(win, text="Shared with the main window's serial settings.\nMatch the application's settings for the virtual COM pair.").pack(padx=16, pady=8)

    def ensure_editable(self):
        if self.app.active and self.app.vars["mode"].get() == "Device Simulator":
            raise ValueError("Stop the simulator before editing its model.")

    def install(self, model):
        self.ensure_editable()
        self.app.simulator_model = model
        self.refresh()
        self.feedback.set(f"Model ready: {len(model.exchanges)} exchanges · {model.ignored_startup_bytes} startup RX bytes excluded.")

    def refresh(self):
        self.table.delete(*self.table.get_children())
        model = self.app.simulator_model
        if model is not None and model is getattr(self.app,'simulator_example',None):self.example_hint.pack(anchor='w')
        else:self.example_hint.pack_forget()
        framing = model.framing if model else getattr(self, "pending_framing", None)
        self.framing_info.set("Request framing: " + (framing.mode if framing else "Exact stream · legacy byte matching"))
        self.update_actions()
        for button in self.rule_bar.winfo_children()[1:]:
            if model:button.pack(side="left",padx=(0,6))
            else:button.pack_forget()
        if model:
            for index, item in enumerate(model.exchanges):
                reply = b"".join(r.data for r in item.replies)
                self.table.insert("", "end", iid=str(index), values=((item.name+" · " if item.name else "") + (" AND ".join(f"{c.source} {c.selector or c.offset} {c.operator} {c.value}" for c in item.match) if item.match else item.request[:36].hex(" ").upper()), reply[:48].hex(" ").upper(),
                                  item.fault.kind + (f" / N={item.fault.nth}" if item.fault.trigger!="Every match" else "") if item.fault else f"{sum(r.delay_ms for r in item.replies):g} ms / {len(item.replies)}"))

    def capture_rows(self, rows):
        self.ensure_editable()
        self.rows = rows
        peers = capture_peers(rows)
        self.peer_combo.configure(values=peers)
        self.peer.set(peers[0] if len(peers) == 1 else "")
        if peers:self.capture_source.pack(fill="x",before=self.table.master,pady=4)
        else:self.capture_source.pack_forget()
        if len(peers) == 1:
            self.build()
        else:
            self.feedback.set("Choose the device in the recording, then Use these messages." if peers else
                              "No messages in this recording. Choose a capture with requests and replies.")

    def load_capture_file(self):
        path = filedialog.askopenfilename(parent=self, filetypes=[("Probe captures", "*.jsonl *.csv")])
        if path:
            self.capture_rows(load_capture(path))

    def use_history(self):
        self.app.flush_frames()
        self.capture_rows([self.app.events[i] for i in self.app.order])

    def build(self):
        if not self.peer.get():
            raise ValueError("Select one recorded peer first.")
        model=compile_capture(self.rows,self.peer.get(),self.request_direction.get())
        self.install(model)
        count=len(model.exchanges);rules='rule' if count==1 else 'rules'
        self.feedback.set(f"{count} request/reply {rules} from {self.peer.get()}.")

    def load_model(self):
        path = filedialog.askopenfilename(parent=self, filetypes=[("Probe device model", "*.json")])
        if path:
            from ..configuration.documents import describe
            from .importing import ImportPreview
            document=read_json(path)
            def apply():
                self.install(model_from_dict(document))
                self.capture_source.pack_forget()
            self.import_preview=ImportPreview(self,self.app,describe(document,'simulator')+'\n\nReplaces the model; start the simulator separately.',apply)
            return self.import_preview

    def save_model(self):
        if not self.app.simulator_model:
            raise ValueError("Load a capture or add an exchange first.")
        path = filedialog.asksaveasfilename(parent=self, defaultextension=".json", filetypes=[("Probe device model", "*.json")])
        if path:
            Path(path).write_text(json.dumps(model_to_dict(self.app.simulator_model), indent=2), encoding="utf-8")
            self.feedback.set("Device model saved. Load it later without the original hardware.")

    def demo(self):
        self.ensure_editable()
        self.app.simulator_example=DeviceModel((Exchange(b"PING\r\n", (Reply(b"PONG\r\n", 10),)),
                                                Exchange(b"BUY:1000\r\n", (Reply(b"APPROVED\r\n", 25),))))
        self.install(self.app.simulator_example)
        self.capture_source.pack_forget()
        self.feedback.set("Example ready. Start the simulator, then connect your app to the address below.")

    def selected_index(self):
        selected = self.table.selection()
        if not selected:
            raise ValueError("Select an exchange first.")
        return int(selected[0])

    def select(self, event=None):
        if not self.table.selection():
            return
        item = self.app.simulator_model.exchanges[self.selected_index()]
        self.request.set(item.request.hex(" ").upper())
        self.reply.set(b"".join(r.data for r in item.replies).hex(" ").upper())
        self.delay.set(f"{sum(r.delay_ms for r in item.replies):g}")

    def edited(self):
        request, reply = parse_hex(self.request.get()), parse_hex(self.reply.get())
        if not request or not reply:
            raise ValueError("Enter request and reply bytes in hex.")
        try: delay = float(self.delay.get())
        except ValueError: raise ValueError("Reply delay must be 0–3600000 ms.") from None
        if not 0 <= delay <= 3600000: raise ValueError("Reply delay must be 0–3600000 ms.")
        return Exchange(request, (Reply(reply, delay),))

    def replace(self, items):
        if not items:
            self.ensure_editable()
            self.app.simulator_model = None
            self.refresh()
            self.feedback.set("No exchanges. Load a capture or add the first request/reply pair.")
            return
        self.install(model_from_dict(model_to_dict(DeviceModel(tuple(items), framing=self.app.simulator_model.framing if self.app.simulator_model else None))))

    def add(self):
        items = list(self.app.simulator_model.exchanges) if self.app.simulator_model else []
        items.append(self.edited())
        self.replace(items)

    def update_selected(self):
        index = self.selected_index()
        items = list(self.app.simulator_model.exchanges)
        items[index] = self.edited()
        self.replace(items)
        self.feedback.set("Exchange updated; edited reply uses one chunk with the chosen delay.")

    def remove(self):
        index = self.selected_index()
        items = list(self.app.simulator_model.exchanges)
        del items[index]
        self.replace(items)

    def move(self, delta):
        index = self.selected_index()
        items = list(self.app.simulator_model.exchanges)
        other = max(0, min(len(items)-1, index+delta))
        items[index], items[other] = items[other], items[index]
        self.replace(items)
        self.table.selection_set(str(other))

    def start(self):
        if self.app.active:
            raise ValueError("Disconnect the current session before starting the simulator.")
        if not self.app.simulator_model:
            raise ValueError("Load a capture or create a device model first.")
        self.app.choose_mode("Device Simulator")
        self.app.toggle()
        if not self.app.active:
            raise ValueError(self.app.status.cget("text"))
        self.app.simulator_info.set("Starting simulated device…")

    def stop(self):
        if self.running():
            self.app.toggle()

    def reset(self):
        if self.app.engine and self.app.engine.ready and self.app.vars["mode"].get() == "Device Simulator":
            self.app.engine.reset_simulator()
