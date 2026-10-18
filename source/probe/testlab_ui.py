"""Hardware test lab: recorded device responses and editable timed sequences."""
import json
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from .capture import load_capture
from .codec import parse_hex
from .sequence_ui import SequencePane
from .serial_endpoints import simulator_transports
from .simulation import (DeviceModel, Exchange, Reply, capture_peers, compile_capture,
                         model_from_dict, model_to_dict)


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
        self.feedback = tk.StringVar(value="Record both directions with the real device, then load the capture here.")
        self.rows = []
        self.peer = tk.StringVar()
        self.request_direction = tk.StringVar(value="TX")
        self.request = tk.StringVar()
        self.reply = tk.StringVar()
        self.delay = tk.StringVar(value="0")
        ttk.Label(self, text="1. Build a device model", font=(app.ui_font, 16, "bold")).pack(anchor="w")
        self.buttons(self, [("Load capture…", self.load_capture_file), ("Use traffic history", self.use_history),
                            ("Load model…", self.load_model), ("Save model…", self.save_model), ("Demo model", self.demo)])
        source = ttk.Frame(self)
        source.pack(fill="x", pady=4)
        self.peer_combo = self.field(source, "Recorded peer", self.peer, 0, [], 30)
        self.field(source, "Request direction", self.request_direction, 1, ["TX", "RX"], 7)
        ttk.Button(source, text="Build from selected peer", command=lambda: self.action(self.build)).grid(row=0, column=2, sticky="s")
        tablebox = ttk.Frame(self)
        tablebox.pack(fill="both", expand=True, pady=6)
        self.table = ttk.Treeview(tablebox, columns=("request", "reply", "delay"), show="headings", height=2, selectmode="browse")
        for name, title, width in (("request", "Expected request (hex)", 280), ("reply", "Recorded reply (hex)", 380), ("delay", "Reply delay / chunks", 160)):
            self.table.heading(name, text=title)
            self.table.column(name, width=width)
        self.table.pack(side="left", fill="both", expand=True)
        scrollbar = ttk.Scrollbar(tablebox, command=self.table.yview)
        scrollbar.pack(side="right", fill="y")
        self.table.configure(yscrollcommand=scrollbar.set)
        self.table.bind("<<TreeviewSelect>>", lambda event: self.action(self.select))
        edit = ttk.Frame(self)
        edit.pack(fill="x")
        edit.columnconfigure(0, weight=1)
        edit.columnconfigure(1, weight=1)
        self.field(edit, "Request bytes (hex)", self.request, 0, width=32)
        self.field(edit, "Reply bytes (hex)", self.reply, 1, width=32)
        self.field(edit, "Reply delay (ms)", self.delay, 2, width=12)
        self.buttons(self, [("Add exchange", self.add), ("Update selected", self.update_selected),
                            ("Remove", self.remove), ("↑", lambda: self.move(-1)), ("↓", lambda: self.move(1))])
        ttk.Label(self, text="2. Expose the simulated device", font=(app.ui_font, 16, "bold")).pack(anchor="w", pady=(8, 4))
        settings = ttk.Frame(self)
        settings.pack(fill="x")
        self.field(settings, "Application connects to", app.vars["simulator_transport"], 0,
                   simulator_transports(), 22)
        self.field(settings, "Listen address", app.vars["bind"], 1, width=15)
        self.field(settings, "TCP port (0 = auto)", app.vars["listen_port"], 2, width=16)
        self.field(settings, "Matching", app.vars["simulator_matching"], 3,
                   ["Conversation order", "Match requests"], 22)
        if "Virtual COM pair" in simulator_transports():
            pair = ttk.Frame(self)
            pair.pack(fill="x", pady=4)
            self.field(pair, "Probe-side virtual COM", app.vars["simulator_port"], 0, width=16)
            self.field(pair, "App-side partner COM", app.vars["simulator_peer_port"], 1, width=16)
            ttk.Label(pair, text="Install a COM pair first.\nApp opens its partner.").grid(row=0, column=2, padx=8, sticky="s")
            ttk.Button(pair, text="COM settings…", command=lambda: self.action(self.com_settings)).grid(row=0, column=3, sticky="s")
        row = ttk.Frame(self)
        row.pack(fill="x", pady=8)
        ttk.Label(row, text="Reply timing × (0 = immediate)").pack(side="left")
        ttk.Entry(row, textvariable=app.vars["simulator_timing"], width=5).pack(side="left", padx=6)
        ttk.Checkbutton(row, text="Repeat conversation", variable=app.vars["simulator_repeat"]).pack(side="left", padx=8)
        ttk.Button(row, text="Start simulator", style="Accent.TButton", command=lambda: self.action(self.start)).pack(side="right")
        ttk.Button(row, text="Stop", command=self.stop).pack(side="right", padx=6)
        ttk.Button(row, text="Reset matching", command=self.reset).pack(side="right")
        ttk.Label(self, textvariable=app.simulator_info, wraplength=950).pack(anchor="w", pady=2)
        ttk.Label(self, textvariable=self.feedback, wraplength=950).pack(anchor="w", pady=2)
        ttk.Label(self, text="Exact recorded bytes are matched across stream reads. Unmatched bytes are ignored and reported. Startup RX is excluded.", wraplength=950).pack(anchor="w")
        self.refresh()

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
        if model:
            for index, item in enumerate(model.exchanges):
                reply = b"".join(r.data for r in item.replies)
                self.table.insert("", "end", iid=str(index), values=(item.request[:36].hex(" ").upper(), reply[:48].hex(" ").upper(),
                                  f"{sum(r.delay_ms for r in item.replies):g} ms / {len(item.replies)}"))

    def capture_rows(self, rows):
        self.ensure_editable()
        self.rows = rows
        peers = capture_peers(rows)
        self.peer_combo.configure(values=peers)
        self.peer.set(peers[0] if len(peers) == 1 else "")
        if len(peers) == 1:
            self.build()
        else:
            self.feedback.set("Choose one recorded peer, then Build from selected peer.")

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
        self.install(compile_capture(self.rows, self.peer.get(), self.request_direction.get()))

    def load_model(self):
        path = filedialog.askopenfilename(parent=self, filetypes=[("Probe device model", "*.json")])
        if path:
            self.install(model_from_dict(read_json(path)))

    def save_model(self):
        if not self.app.simulator_model:
            raise ValueError("Load a capture or add an exchange first.")
        path = filedialog.asksaveasfilename(parent=self, defaultextension=".json", filetypes=[("Probe device model", "*.json")])
        if path:
            Path(path).write_text(json.dumps(model_to_dict(self.app.simulator_model), indent=2), encoding="utf-8")
            self.feedback.set("Device model saved. Load it later without the original hardware.")

    def demo(self):
        self.install(DeviceModel((Exchange(b"PING\r\n", (Reply(b"PONG\r\n", 10),)),
                                  Exchange(b"BUY:1000\r\n", (Reply(b"APPROVED\r\n", 25),)))))

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
        self.install(model_from_dict(model_to_dict(DeviceModel(tuple(items)))))

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
        self.feedback.set("Starting simulated device…")

    def stop(self):
        if self.app.active and self.app.vars["mode"].get() == "Device Simulator":
            self.app.toggle()

    def reset(self):
        if self.app.engine and self.app.engine.ready and self.app.vars["mode"].get() == "Device Simulator":
            self.app.engine.reset_simulator()
