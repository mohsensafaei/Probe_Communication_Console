"""A short sequence workflow: choose bytes, set timing, send to a visible endpoint."""
import json
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from .capture import load_capture
from .codec import visible
from .scenario import MAX_DELAY, compile_steps, integer, sequence_from_dict, steps_from_capture


class SequencePane(ttk.Frame):
    REPEATS = ("Run once", "Repeat a set number", "Repeat until stopped")
    ADVANCE = ("After interval", "After a reply")

    def __init__(self, parent, app):
        super().__init__(parent, padding=12)
        self.app = app
        self.feedback = tk.StringVar(value="Choose captured messages, add the composer, or write a new message.")
        self.destination = tk.StringVar()
        self.status = tk.StringVar()
        self.interval = app.vars["sequence_interval"]
        self.individual = tk.BooleanVar(value=app.vars["sequence_timing"].get() == "individual")
        self.advance = app.vars["sequence_advance"]
        if self.advance.get() not in self.ADVANCE:self.advance.set(self.ADVANCE[0])
        self.reply_timeout = app.vars["sequence_reply_timeout"]
        self.editor_wait = tk.BooleanVar(value=False)
        self.repeat_mode = tk.StringVar(value=self.REPEATS[0])
        self.capture_direction = tk.StringVar(value="RX")
        self.fields = {name: tk.StringVar(value=value) for name, value in dict(
            name="New message", send_mode="Hex", encoding="utf-8", ending="None",
            delay_ms="100", repeat="1", expect="", timeout_ms="2000").items()}
        self.editor = None
        self.capture_picker = None
        self.controls = []
        self._traces = []
        self._syncing = False
        self._starting = False
        self._run_destination = ""
        self._monitor_job = None
        if app.vars["sequence_timing"].get() == "auto":
            try:legacy_interval = integer(app.vars["interval"].get(), "Interval (ms)", 0, MAX_DELAY)
            except ValueError:legacy_interval = 100
            self.adopt_timing(legacy_interval)
        self.sync_repeat()

        ttk.Label(self, text="1. Choose messages", font=(app.ui_font, 16, "bold")).pack(anchor="w")
        bar = ttk.Frame(self)
        bar.pack(fill="x", pady=(4, 6))
        self.button(bar, "Choose captured messages…", self.use_capture).pack(side="left", padx=(0, 6))
        self.button(bar, "Add composer", self.add_composer).pack(side="left", padx=(0, 6))
        self.button(bar, "New message…", self.open_editor).pack(side="left")
        self.button(bar, "Save…", self.save_file).pack(side="right")
        self.button(bar, "Load…", self.load_file).pack(side="right", padx=6)

        below = ttk.Frame(self)
        below.pack(side="bottom", fill="x")
        tablebox = ttk.Frame(self)
        tablebox.pack(fill="both", expand=True)
        self.table = ttk.Treeview(tablebox, columns=("name", "bytes", "delay", "options", "preview"),
                                  show="headings", height=5, selectmode="browse")
        for key, title, width in (("name", "Message", 205), ("bytes", "Bytes", 60),
                                  ("delay", "Delay after (ms)", 115), ("options", "Checks / repeats", 120),
                                  ("preview", "Payload preview", 340)):
            self.table.heading(key, text=title)
            self.table.column(key, width=width, minwidth=50, stretch=key in ("name", "preview"))
        self.table.pack(side="left", fill="both", expand=True)
        scrollbar = ttk.Scrollbar(tablebox, command=self.table.yview)
        scrollbar.pack(side="right", fill="y")
        self.table.configure(yscrollcommand=scrollbar.set)
        self.table.bind("<Double-1>", lambda event: self.action(self.edit_selected))
        self.table.bind("<Return>", lambda event: self.action(self.edit_selected))
        bar = ttk.Frame(below)
        bar.pack(fill="x", pady=6)
        self.button(bar, "Edit message…", self.edit_selected).pack(side="left", padx=(0, 6))
        self.button(bar, "Remove", self.remove).pack(side="left", padx=(0, 6))
        self.button(bar, "Move up", lambda: self.move(-1)).pack(side="left", padx=(0, 6))
        self.button(bar, "Move down", lambda: self.move(1)).pack(side="left", padx=(0, 6))
        self.button(bar, "Duplicate", self.duplicate).pack(side="left")

        ttk.Label(below, text="2. Set timing", font=(app.ui_font, 16, "bold")).pack(anchor="w", pady=(4, 2))
        timing = ttk.Frame(below)
        timing.pack(fill="x")
        ttk.Label(timing, text="Send next message").grid(row=0, column=0, sticky="w")
        self.advance_combo = ttk.Combobox(timing, textvariable=self.advance, values=self.ADVANCE, state="readonly", width=19)
        self.advance_combo.grid(row=0, column=1, padx=(6, 18), sticky="w")
        self.controls.append(self.advance_combo)
        self.interval_box = ttk.Frame(timing)
        self.interval_box.grid(row=1, column=0, columnspan=2, sticky="w", pady=(6, 0))
        ttk.Label(self.interval_box, text="Interval between messages").pack(side="left")
        self.interval_entry = ttk.Entry(self.interval_box, textvariable=self.interval, width=8)
        self.interval_entry.pack(side="left", padx=6)
        self.controls.append(self.interval_entry)
        ttk.Label(self.interval_box, text="ms").pack(side="left")
        self.reply_box = ttk.Frame(timing)
        self.reply_box.grid(row=1, column=0, columnspan=2, sticky="w", pady=(6, 0))
        ttk.Label(self.reply_box, text="Reply timeout").pack(side="left")
        self.timeout_entry = ttk.Entry(self.reply_box, textvariable=self.reply_timeout, width=8)
        self.timeout_entry.pack(side="left", padx=6)
        ttk.Label(self.reply_box, text="ms · stop if no reply").pack(side="left")
        self.controls.append(self.timeout_entry)
        self.repeat_combo = ttk.Combobox(timing, textvariable=self.repeat_mode, values=self.REPEATS,
                                         state="readonly", width=23)
        self.repeat_combo.grid(row=0, column=2, sticky="w")
        self.controls.append(self.repeat_combo)
        self.count_box = ttk.Frame(timing)
        self.count_box.grid(row=0, column=3, padx=6)
        self.count_entry = ttk.Entry(self.count_box, textvariable=app.vars["sequence_cycles"], width=6)
        self.count_entry.pack(side="left")
        ttk.Label(self.count_box, text="runs").pack(side="left", padx=4)
        self.controls.append(self.count_entry)
        self.individual_check = ttk.Checkbutton(below, text="Advanced: use individual message delays",
                                                variable=self.individual)
        self.individual_check.pack(anchor="w", pady=(4, 6))
        self.controls.append(self.individual_check)
        self.timing_hint = tk.StringVar()
        self.hint_label = ttk.Label(below, textvariable=self.timing_hint, wraplength=900)
        self.hint_label.pack(anchor="w", pady=(4, 2))

        send = ttk.Frame(below)
        send.pack(fill="x", pady=(6, 4))
        self.run_button = ttk.Button(send, text="Run sequence", style="Accent.TButton", command=lambda: self.action(self.run))
        self.run_button.pack(side="right")
        self.stop_button = ttk.Button(send, text="Stop", command=self.stop)
        self.stop_button.pack(side="right", padx=6)
        ttk.Label(send, text="3. Send messages", font=(app.ui_font, 16, "bold")).pack(side="left")
        ttk.Label(below, textvariable=self.destination, wraplength=900).pack(anchor="w")
        ttk.Label(below, textvariable=self.status, wraplength=900).pack(anchor="w", pady=(4, 2))
        ttk.Label(below, textvariable=self.feedback, wraplength=900).pack(anchor="w")

        for variable, callback in ((self.interval, self.timing_changed), (self.individual, self.timing_changed),
                                   (self.advance, self.timing_changed), (self.reply_timeout, self.timing_changed),
                                   (self.repeat_mode, self.repeat_changed),
                                   (app.vars["sequence_cycles"], self.cycles_changed)):
            token = variable.trace_add("write", callback)
            self._traces.append((variable, token))
        self.bind("<Destroy>", self.destroyed, add="+")
        self.update_timing_controls()
        self.refresh()
        self.monitor()

    def action(self, operation):
        try:
            return operation()
        except (ValueError, KeyError, TypeError, OSError, RuntimeError) as exc:
            self.feedback.set(str(exc))
            if self.editor is not None and self.editor.winfo_exists():
                self.editor_feedback.set(str(exc))

    def button(self, parent, text, callback):
        button = ttk.Button(parent, text=text, command=lambda: self.action(callback))
        self.controls.append(button)
        return button

    def busy(self):
        task = getattr(self.app.engine, "scenario_task", None)
        return self._starting or (task is not None and not task.done())

    def ensure_idle(self):
        if self.busy():raise ValueError("Stop the running sequence before editing its messages or destination.")

    def destination_text(self):
        cfg = self.app.values()
        mode = cfg["mode"]
        proxy = mode in ("Serial Proxy", "Serial ↔ TCP", "TCP Proxy")
        if proxy and cfg["side"] == "App / downstream":
            endpoint = f"application / downstream · {cfg['target']}"
        elif "Serial" in mode:
            endpoint = f"device · {cfg['serial_port'] or 'choose a COM / serial port'}"
        elif mode == "TCP Server":
            endpoint = f"TCP application · {cfg['target']}"
        else:
            endpoint = f"{cfg['host']}:{cfg['port']}"
        if mode == "Device Simulator":
            return "The device simulator replies automatically. Connect a client / serial transport to run a sequence."
        ready = self.app.engine is not None and self.app.engine.ready
        prefix = "Send to" if ready else "Not connected — in the main window, connect to"
        return f"{prefix}: {endpoint} ({mode}). Every message in the table goes here."

    def monitor(self):
        self._monitor_job = None
        if self.app.closing or not self.winfo_exists():return
        ready = self.app.engine is not None and self.app.engine.ready
        if not ready or self.app.sequence_info.get() != "Starting test sequence…":self._starting = False
        busy = self.busy()
        for control in self.controls:
            if isinstance(control, ttk.Combobox):control.configure(state="disabled" if busy else "readonly")
            else:control.configure(state="disabled" if busy else "normal")
        if self.individual.get() or self.reply_mode():self.interval_entry.configure(state="disabled")
        self.run_button.configure(state="normal" if ready and self.app.macros and not busy and self.app.vars["mode"].get() != "Device Simulator" else "disabled")
        self.stop_button.configure(state="normal" if busy else "disabled")
        self.destination.set(self._run_destination if busy else self.destination_text())
        info = self.app.sequence_info.get()
        if info.startswith("Sequence idle.") and ready:
            info = f"Ready · {len(self.app.macros)} messages. Run sends them in table order." if self.app.macros else "Add messages to enable Run sequence."
        self.status.set(info)
        self._monitor_job = self.app.after(150, self.monitor)

    def destroyed(self, event):
        if event.widget is not self:return
        if self._monitor_job is not None:self.app.after_cancel(self._monitor_job)
        for variable, token in self._traces:variable.trace_remove("write", token)
        self._traces.clear()

    def reply_mode(self):
        return self.advance.get() == self.ADVANCE[1]

    def editable_rows(self):
        # Shared reply mode is an execution override. Editing/reordering must not
        # bake it into messages, so switching back restores their interval mode.
        delay = None if self.individual.get() or self.reply_mode() else integer(self.interval.get(), "Interval (ms)", 0, MAX_DELAY)
        rows = [dict(row, **({"delay_ms": delay} if delay is not None else {})) for row in self.app.macros]
        compile_steps(rows, 100)
        return rows

    def effective_rows(self):
        rows = self.editable_rows()
        if self.reply_mode():
            timeout = integer(self.reply_timeout.get(), "Reply timeout (ms)", 1, MAX_DELAY)
            rows = [dict(row, delay_ms=0, wait_for_reply=True, timeout_ms=timeout) for row in rows]
        compile_steps(rows, 100)
        return rows

    def update_timing_controls(self):
        if self.reply_mode():
            self.interval_box.grid_remove();self.reply_box.grid()
            self.individual_check.pack_forget()
            hint = "First message sends immediately. First incoming data from the destination releases the next; no interval delay."
        else:
            self.reply_box.grid_remove();self.interval_box.grid()
            self.individual_check.pack(anchor="w", before=self.hint_label, pady=(4, 6))
            hint = "Messages use the interval shown, or their individual delays."
        self.timing_hint.set(hint)
        self.interval_entry.configure(state="disabled" if self.individual.get() or self.reply_mode() else "normal")

    def adopt_timing(self, default=100):
        self._syncing = True
        try:
            steps = compile_steps(self.app.macros, default) if self.app.macros else ()
            self.app.macros = [dict(row, delay_ms=step.delay_ms) for row, step in zip(self.app.macros, steps)]
            reply_mode = bool(steps) and all(step.wait_for_reply and step.delay_ms == 0 for step in steps) and len({step.timeout_ms for step in steps}) == 1
            self.advance.set(self.ADVANCE[1] if reply_mode else self.ADVANCE[0])
            if reply_mode:
                self.reply_timeout.set(str(steps[0].timeout_ms))
                # The shared control owns this flag; retain per-message checks.
                for row in self.app.macros:row.pop("wait_for_reply", None)
            delays = {step.delay_ms for step in steps}
            self.individual.set(len(delays) > 1)
            if len(delays) == 1 and not reply_mode:self.interval.set(str(next(iter(delays))))
            self.app.vars["sequence_timing"].set("individual" if self.individual.get() else "uniform")
        finally:self._syncing = False

    def timing_changed(self, *_):
        if self._syncing:return
        self.app.vars["sequence_timing"].set("individual" if self.individual.get() else "uniform")
        self.update_timing_controls()
        self.refresh()
        try:
            if self.app.macros:self.effective_rows()
            elif self.reply_mode():integer(self.reply_timeout.get(), "Reply timeout (ms)", 1, MAX_DELAY)
            else:integer(self.interval.get(), "Interval (ms)", 0, MAX_DELAY)
        except ValueError as exc:
            self.feedback.set(str(exc));return
        self.app.save_settings()
        self.feedback.set("Waits for received data from the destination after each send, including the last. Set expected bytes in Edit message for a specific reply." if self.reply_mode()
                          else "Individual delays are shown in the table. Edit a message to change its delay." if self.individual.get()
                          else f"Every message uses {self.interval.get()} ms. This applies immediately to the table, Run and Save.")

    def sync_repeat(self):
        cycles = self.app.vars["sequence_cycles"].get()
        self.repeat_mode.set(self.REPEATS[2] if cycles == "0" else self.REPEATS[0] if cycles == "1" else self.REPEATS[1])

    def repeat_changed(self, *_):
        if self._syncing:return
        self._syncing = True
        try:
            mode = self.repeat_mode.get()
            cycles = self.app.vars["sequence_cycles"]
            if mode == self.REPEATS[0]:cycles.set("1")
            elif mode == self.REPEATS[2]:cycles.set("0")
            elif cycles.get() in ("0", "1"):cycles.set("2")
            if mode == self.REPEATS[1]:self.count_box.grid()
            else:self.count_box.grid_remove()
        finally:self._syncing = False
        self.app.save_settings()

    def cycles_changed(self, *_):
        if self._syncing:return
        # Editing 10 must not hide the entry after its first digit (1), and
        # entering 0 in a finite run must never silently enable an endless run.
        if self.repeat_mode.get() == self.REPEATS[1]:return
        self._syncing = True
        try:self.sync_repeat()
        finally:self._syncing = False
        if self.repeat_mode.get() == self.REPEATS[1]:self.count_box.grid()
        else:self.count_box.grid_remove()

    def run_cycles(self):
        mode = self.repeat_mode.get()
        if mode == self.REPEATS[0]:return 1
        if mode == self.REPEATS[2]:return 0
        return integer(self.app.vars["sequence_cycles"].get(), "Number of runs", 1, 1000000)

    def refresh(self, selected=None):
        previous = self.table.selection()
        self.table.delete(*self.table.get_children())
        try:
            rows = self.effective_rows() if self.app.macros else []
            steps = compile_steps(rows, 100) if rows else ()
        except (ValueError, TypeError):steps = ()
        for index, row in enumerate(self.app.macros):
            if index < len(steps):
                step = steps[index]
                options = ", ".join(x for x in (f"×{step.repeat}" if step.repeat > 1 else "",
                                                "Match reply" if step.expect else "Any reply" if step.wait_for_reply else "") if x) or "—"
                values = (step.name, len(step.payload), step.delay_ms, options, visible(step.payload[:64]))
            else:values = (row.get("name", "Invalid message"), "?", "?", "Check settings", "")
            self.table.insert("", "end", iid=str(index), values=values)
        chosen = str(selected) if selected is not None else previous[0] if previous else None
        if chosen is not None and self.table.exists(chosen):
            self.table.selection_set(chosen);self.table.see(chosen)
        if self.repeat_mode.get() == self.REPEATS[1]:self.count_box.grid()
        else:self.count_box.grid_remove()

    def changed(self, selected=None):
        self.refresh(selected)
        self.app.save_settings()
        self.feedback.set(f"{len(self.app.macros)} messages ready. Run sends all messages in table order.")
        self.monitor_now()

    def selected_index(self):
        if not self.table.selection():raise ValueError("Select a message to edit, remove or move.")
        return int(self.table.selection()[0])

    def append_rows(self, rows, recorded=False):
        self.ensure_idle()
        current = self.editable_rows() if self.app.macros else []
        compile_steps(current + rows, 100)
        self.app.macros = current + rows
        if recorded:
            self.individual.set(True)
        self.changed(len(self.app.macros)-1)

    def add_composer(self):
        data = self.app.payload_bytes()
        delay = 100 if self.reply_mode() else integer(self.interval.get(), "Interval (ms)", 0, MAX_DELAY)
        self.append_rows([dict(name=f"Message {len(self.app.macros)+1}", text=data.hex(" ").upper(), send_mode="Hex", delay_ms=delay)])

    def use_capture(self):
        self.ensure_idle()
        if self.capture_picker is not None and self.capture_picker.winfo_exists():
            self.capture_picker.lift();return self.capture_picker
        self.app.flush_frames()
        self.capture_picker = CapturePicker(self)
        return self.capture_picker

    def edit_selected(self):
        self.open_editor(self.selected_index())

    def open_editor(self, index=None):
        self.ensure_idle()
        if self.editor is not None and self.editor.winfo_exists():self.editor.lift();return self.editor
        self.edit_index = index
        delay = 100 if self.reply_mode() else integer(self.interval.get(), "Interval (ms)", 0, MAX_DELAY)
        row = self.editable_rows()[index] if index is not None else dict(name="New message", text="", send_mode="Hex", delay_ms=delay)
        step = compile_steps([row], 100)[0] if index is not None else None
        self.editor_wait.set(bool(step and step.wait_for_reply))
        self._editor_timeout = str(step.timeout_ms if step else 2000)
        defaults = dict(name=step.name if step else row["name"], send_mode="Hex", encoding="utf-8", ending="None",
                        delay_ms=str(step.delay_ms if step else delay), repeat=str(step.repeat if step else 1),
                        expect=step.expect.hex(" ").upper() if step else "", timeout_ms=self.reply_timeout.get() if self.reply_mode() else self._editor_timeout)
        for key, value in defaults.items():self.fields[key].set(value)
        win = tk.Toplevel(self)
        self.editor = win
        win.title("Probe · Edit message" if index is not None else "Probe · New message")
        win.geometry("760x520");win.minsize(700, 480)
        win.transient(self.winfo_toplevel());win.configure(bg=self.app.colors["panel"])
        body = ttk.Frame(win, padding=16);body.pack(fill="both", expand=True)
        ttk.Label(body, text="Edit message" if index is not None else "New message", font=(self.app.ui_font, 18, "bold")).pack(anchor="w")
        rowbox = ttk.Frame(body);rowbox.pack(fill="x", pady=8);rowbox.columnconfigure(0, weight=1)
        self.field(rowbox, "Message name", self.fields["name"], 0, width=36)
        self.field(rowbox, "Format", self.fields["send_mode"], 1, ["Hex", "Text", "Escaped", "Decimal", "Hercules"], 12)
        ttk.Label(body, text="Payload — saved bytes are sent exactly as shown").pack(anchor="w")
        self.payload = self.app.text_widget(body, height=3, wrap="word");self.payload.pack(fill="both", expand=True, pady=6)
        if step:self.payload.insert("1.0", step.payload.hex(" ").upper())
        advanced = ttk.Frame(body)
        expanded = tk.BooleanVar(value=bool(step and (step.expect or step.wait_for_reply or step.repeat > 1)) or (self.individual.get() and not self.reply_mode()))
        def toggle():
            if expanded.get():advanced.pack(fill="x", after=toggle_button, pady=4)
            else:advanced.pack_forget()
        toggle_button = ttk.Checkbutton(body, text="Advanced: line ending, individual delay, repeat and reply check", variable=expanded, command=toggle)
        toggle_button.pack(anchor="w", pady=4)
        first = ttk.Frame(advanced);first.pack(fill="x", pady=3)
        self.field(first, "Encoding", self.fields["encoding"], 0, ["utf-8", "ascii", "latin-1", "cp1256", "gbk", "utf-16-le"], 12)
        self.field(first, "Line ending", self.fields["ending"], 1, ["None", "CR", "LF", "CRLF"], 10)
        delay_widget = self.field(first, "Delay after (ms)", self.fields["delay_ms"], 2, width=12)
        if not self.individual.get() or self.reply_mode():delay_widget.configure(state="disabled")
        self.field(first, "Send this message", self.fields["repeat"], 3, width=10)
        second = ttk.Frame(advanced);second.pack(fill="x", pady=3);second.columnconfigure(0, weight=1)
        self.field(second, "Expected reply (hex; blank = any in reply mode)", self.fields["expect"], 0, width=46)
        timeout_widget = self.field(second, "Reply timeout (ms)", self.fields["timeout_ms"], 1, width=16)
        wait_check = ttk.Checkbutton(advanced, text="Wait for any reply for this message in interval mode", variable=self.editor_wait)
        wait_check.pack(anchor="w", pady=3)
        if self.reply_mode():
            timeout_widget.configure(state="disabled");wait_check.configure(state="disabled")
        ttk.Label(advanced, text="Reply mode uses the sequence timeout and no delay. In interval mode, reply checks run before the delay.", wraplength=690).pack(anchor="w")
        toggle()
        self.editor_feedback = tk.StringVar(value="Waits for a reply using the sequence timeout. Expected bytes above can require a specific response." if self.reply_mode()
                                            else "Uses the shared interval. Enable individual delays on the sequence page to customize timing." if not self.individual.get() else "")
        ttk.Label(body, textvariable=self.editor_feedback, wraplength=700).pack(anchor="w", pady=6)
        footer = ttk.Frame(body);footer.pack(fill="x", pady=(4, 0))
        ttk.Button(footer, text="Cancel", command=win.destroy).pack(side="right", padx=6)
        ttk.Button(footer, text="Save message", style="Accent.TButton", command=lambda: self.action(self.save_editor)).pack(side="right")
        win.bind("<Escape>", lambda event: win.destroy());win.grab_set()
        return win

    @staticmethod
    def field(parent, label, variable, column, values=None, width=12):
        box = ttk.Frame(parent);box.grid(row=0, column=column, sticky="nsew", padx=(0, 10))
        ttk.Label(box, text=label).pack(anchor="w")
        widget = (ttk.Combobox(box, textvariable=variable, values=values, state="readonly", width=width)
                  if values is not None else ttk.Entry(box, textvariable=variable, width=width))
        widget.pack(fill="x", pady=(3, 0))
        return widget

    def edited(self):
        row = {key: var.get() for key, var in self.fields.items()}
        if not self.individual.get() and not self.reply_mode():row["delay_ms"] = self.interval.get()
        if self.reply_mode():row["timeout_ms"] = self._editor_timeout
        if self.editor_wait.get():row["wait_for_reply"] = True
        row.update(text=self.payload.get("1.0", "end-1c"), checksum="None", prefix="", suffix="")
        compile_steps([row], 100)
        return row

    def save_editor(self):
        if self.edit_index is None:self.add()
        else:self.update_selected(self.edit_index)
        self.editor.destroy()

    def add(self):
        self.append_rows([self.edited()])

    def update_selected(self, index=None):
        self.ensure_idle()
        index = self.selected_index() if index is None else index
        rows = self.editable_rows();rows[index] = self.edited();compile_steps(rows, 100)
        self.app.macros = rows;self.changed(index)

    def duplicate(self):
        self.ensure_idle()
        index = self.selected_index();rows = self.editable_rows()
        rows.insert(index+1, dict(rows[index]));compile_steps(rows, 100)
        self.app.macros = rows;self.changed(index+1)

    def remove(self):
        self.ensure_idle()
        index = self.selected_index();del self.app.macros[index]
        self.changed(min(index, len(self.app.macros)-1))

    def move(self, delta):
        self.ensure_idle()
        index = self.selected_index();other = max(0, min(len(self.app.macros)-1, index+delta))
        self.app.macros[index], self.app.macros[other] = self.app.macros[other], self.app.macros[index]
        self.changed(other)

    def load_file(self):
        self.ensure_idle()
        path = filedialog.askopenfilename(parent=self, filetypes=[("Probe sequence", "*.json")])
        if not path:return
        if Path(path).stat().st_size > 24 * 1024 * 1024:raise ValueError("File is too large (24 MiB maximum).")
        rows, cycles = sequence_from_dict(json.loads(Path(path).read_text(encoding="utf-8-sig")))
        if self.app.macros and not messagebox.askyesno("Replace sequence", "Replace the current sequence with this file?", parent=self):return
        self.app.macros = rows;self.adopt_timing()
        self.update_timing_controls()
        self._syncing = True
        try:
            self.app.vars["sequence_cycles"].set(str(cycles));self.sync_repeat()
        finally:self._syncing = False
        self.app.vars["sequence_loop"].set(False)
        self.changed()
        if self.individual.get():self.feedback.set("Loaded individual delays and reply checks unchanged. Uncheck Advanced to use one shared interval.")

    def save_file(self):
        rows = self.effective_rows();cycles = self.run_cycles()
        path = filedialog.asksaveasfilename(parent=self, defaultextension=".json", filetypes=[("Probe sequence", "*.json")])
        if path:
            # Older releases ignore unknown per-step flags. Version 2 makes
            # them reject a reply-gated file instead of sending without waits.
            version = 2 if any(row.get("wait_for_reply") for row in rows) else 1
            Path(path).write_text(json.dumps(dict(format="probe-sequence", version=version, cycles=cycles, steps=rows), indent=2), encoding="utf-8")
            self.feedback.set("Saved the sequence with the timing, repetitions and reply checks that Run will use.")

    def run(self):
        self.ensure_idle()
        rows = self.effective_rows();cycles = self.run_cycles()
        self.app.vars["sequence_loop"].set(False)
        self._run_destination = self.destination_text()
        if self.app.run_sequence(rows, cycles):
            self._starting = True
            self.feedback.set(f"Sending {len(rows)} messages to the destination above. Stop cancels pending sends.")
        self.monitor_now()

    def monitor_now(self):
        if self._monitor_job is not None:self.app.after_cancel(self._monitor_job)
        self.monitor()

    def stop(self):
        self.app.stop_sequence();self._starting = False
        self.monitor_now()


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
