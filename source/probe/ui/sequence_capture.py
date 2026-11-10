import tkinter as tk
from tkinter import filedialog, ttk

from ..capture import load_capture
from ..codec import visible
from ..scenario import MAX_DELAY, integer, steps_from_capture


class CapturePicker(tk.Toplevel):
    """Filter a snapshot and explicitly select the original RX or TX bytes."""
    def __init__(self, pane):
        super().__init__(pane)
        self.pane = pane
        self.title("Probe · Choose captured messages");self.geometry("900x560");self.minsize(800, 500)
        self.transient(pane.winfo_toplevel());self.configure(bg=pane.app.colors["panel"])
        body = ttk.Frame(self, padding=16);body.pack(fill="both", expand=True)
        ttk.Label(body, text="Choose captured messages", font=(pane.app.ui_font, 18, "bold")).pack(anchor="w")
        ttk.Label(body, text="RX = received by Probe. TX = sent by Probe. Both can be replayed; neither changes the send destination.", wraplength=850).pack(anchor="w", pady=4)
        self.sources = {"Traffic history": [pane.app.events[i] for i in pane.app.order],
                        "Imported capture": list(pane.app.last_capture or [])}
        self.source = tk.StringVar(value="Traffic history" if self.sources["Traffic history"] or not self.sources["Imported capture"] else "Imported capture")
        self.peer = tk.StringVar(value="All peers")
        self.recorded = tk.BooleanVar(value=False)
        self.feedback = tk.StringVar()
        controls = ttk.Frame(body);controls.pack(fill="x", pady=6)
        self.source_combo = pane.field(controls, "Source", self.source, 0, list(self.sources), 21)
        direction = pane.field(controls, "Original direction", pane.capture_direction, 1, ["RX", "TX"], 10)
        self.peer_combo = pane.field(controls, "Recorded peer", self.peer, 2, ["All peers"], 25)
        ttk.Button(controls, text="Load capture…", command=lambda: self.action(self.load_file)).grid(row=0, column=3, sticky="s")
        for widget in (self.source_combo, direction, self.peer_combo):widget.bind("<<ComboboxSelected>>", lambda event: self.refresh())
        below = ttk.Frame(body);below.pack(side="bottom", fill="x")
        box = ttk.Frame(body);box.pack(fill="both", expand=True, pady=4)
        self.table = ttk.Treeview(box, columns=("direction", "peer", "bytes", "preview"), show="headings", selectmode="extended", height=6)
        for key, title, width in (("direction", "Source", 65), ("peer", "Peer", 180), ("bytes", "Bytes", 65), ("preview", "Payload preview", 490)):
            self.table.heading(key, text=title);self.table.column(key, width=width, minwidth=50, stretch=key in ("peer", "preview"))
        self.table.pack(side="left", fill="both", expand=True)
        scroll = ttk.Scrollbar(box, command=self.table.yview);scroll.pack(side="right", fill="y");self.table.configure(yscrollcommand=scroll.set)
        self.table.bind("<<TreeviewSelect>>", lambda event: self.selection_changed())
        row = ttk.Frame(below);row.pack(fill="x", pady=4)
        ttk.Button(row, text="Select all", command=lambda: self.table.selection_set(self.table.get_children())).pack(side="left", padx=(0, 6))
        ttk.Button(row, text="Clear selection", command=lambda: self.table.selection_remove(self.table.selection())).pack(side="left")
        ttk.Checkbutton(row, text="Keep recorded intervals (advanced)", variable=self.recorded).pack(side="right")
        ttk.Label(below, text="The selected bytes will be sent again, in recorded order, to the sequence's destination.", wraplength=750).pack(anchor="w", pady=4)
        self.destination = ttk.Label(below, text=pane.destination_text(), wraplength=750);self.destination.pack(anchor="w")
        ttk.Label(below, text="A capture row may be a stream chunk, not a complete protocol message.").pack(anchor="w", pady=4)
        footer = ttk.Frame(below);footer.pack(fill="x", pady=6)
        self.add_button = ttk.Button(footer, text="Add messages", style="Accent.TButton", command=lambda: self.action(self.add_selected))
        self.add_button.pack(side="right")
        ttk.Button(footer, text="Cancel", command=self.destroy).pack(side="right", padx=6)
        ttk.Label(footer, textvariable=self.feedback).pack(side="left")
        self.refresh();self.grab_set();self.bind("<Escape>", lambda event: self.destroy())

    def action(self, operation):
        try:operation()
        except (ValueError, KeyError, TypeError, OSError, RuntimeError) as exc:self.feedback.set(str(exc))

    def load_file(self):
        path = filedialog.askopenfilename(parent=self, filetypes=[("Probe capture", "*.jsonl *.csv")])
        if path:
            self.sources["Loaded file"] = load_capture(path)
            self.source_combo.configure(values=list(self.sources))
            self.source.set("Loaded file");self.peer.set("All peers");self.refresh()

    def refresh(self):
        rows = self.sources[self.source.get()]
        peers = ["All peers"] + sorted({str(row.get("peer", "")) for row in rows})
        self.peer_combo.configure(values=peers)
        if self.peer.get() not in peers:self.peer.set("All peers")
        self.rows = [row for row in rows if row["direction"] == self.pane.capture_direction.get()
                     and (self.peer.get() == "All peers" or str(row.get("peer", "")) == self.peer.get())]
        self.table.delete(*self.table.get_children())
        for index, row in enumerate(self.rows):
            self.table.insert("", "end", iid=str(index), values=(row["direction"], row.get("peer", ""), len(row["data"]), visible(row["data"][:80])))
        self.table.selection_set(self.table.get_children())
        self.selection_changed()

    def selection_changed(self):
        count = len(self.table.selection())
        self.add_button.configure(text=f"Add {count} messages", state="normal" if count else "disabled")
        self.feedback.set(f"{count} selected · {len(self.rows)} {self.pane.capture_direction.get()} records" if self.rows
                          else f"No {self.pane.capture_direction.get()} records. Load a capture or choose the other direction.")

    def add_selected(self):
        selected = set(self.table.selection())
        rows = [row for index, row in enumerate(self.rows) if str(index) in selected]
        delay = 100 if self.pane.reply_mode() else integer(self.pane.interval.get(), "Interval (ms)", 0, MAX_DELAY)
        steps = steps_from_capture(rows, delay, self.recorded.get())
        self.pane.append_rows(steps, self.recorded.get())
        self.destroy()
