"""Live terminal tab. Rendering never changes captured transport bytes."""
import re
import tkinter as tk
from tkinter import ttk
from .terminal import TerminalModel, key_bytes

PALETTE={"black":"#10141d","red":"#ed778a","green":"#49d6b4","brown":"#dfb56c",
 "blue":"#78afff","magenta":"#c7a0fa","cyan":"#71d9e7","white":"#e7edf7",
 "brightblack":"#8798ad","brightred":"#ff9baa","brightgreen":"#81ebc8",
 "brightbrown":"#ffdc8d","brightblue":"#a8ccff","brightmagenta":"#e2c7ff",
 "brightcyan":"#a1f2ff","brightwhite":"#ffffff"}

class TerminalPane(ttk.Frame):
    def __init__(self,parent,app,shared=None):
        super().__init__(parent)
        self.app=app;self.owner=shared.owner if shared else self
        self._peer=None;self.model=shared.model if shared else None;self.error=shared.error if shared else None
        self.keyboard=shared.keyboard if shared else tk.BooleanVar(value=False)
        self.local_echo=shared.local_echo if shared else tk.BooleanVar(value=False)
        self.enter=shared.enter if shared else tk.StringVar(value="CR")
        self.backspace=shared.backspace if shared else tk.StringVar(value="DEL")
        self.tags={};self.dirty=True;self.last_revision=-1
        if not shared:
            try:self.model=TerminalModel(100,24,app.vars["encoding"].get())
            except RuntimeError as exc:self.error=str(exc)
        self.columnconfigure(0,weight=1);self.rowconfigure(1,weight=1)
        controls=ttk.Frame(self);controls.grid(row=0,column=0,columnspan=2,sticky="ew",pady=4)
        bar=ttk.Frame(controls);bar.pack(fill="x")
        actions=ttk.Frame(controls);actions.pack(fill="x",pady=(3,0))
        self.keyboard_check=ttk.Checkbutton(bar,text="Send keyboard",variable=self.keyboard,command=self.keyboard_changed)
        self.keyboard_check.pack(side="left")
        ttk.Checkbutton(bar,text="Local echo",variable=self.local_echo).pack(side="left",padx=4)
        ttk.Label(bar,text="Enter").pack(side="left",padx=(4,0))
        ttk.Combobox(bar,textvariable=self.enter,values=["CR","LF","CRLF"],state="readonly",width=5).pack(side="left",padx=4)
        ttk.Label(bar,text="Backspace").pack(side="left",padx=(4,3))
        ttk.Combobox(bar,textvariable=self.backspace,values=["DEL","BS"],state="readonly",width=4).pack(side="left")
        if not shared:ttk.Button(actions,text="Detach",width=7,command=self.pop_out).pack(side="right",padx=4)
        ttk.Button(actions,text="Paste",width=5,command=self.paste).pack(side="right",padx=4)
        ttk.Button(actions,text="Reset",width=5,command=self.reset).pack(side="right",padx=4)
        ttk.Label(actions,text="Scrollback").pack(side="left",padx=(0,6))
        ttk.Button(actions,text="↑ Older",width=8,command=lambda:self.history(-1)).pack(side="left")
        ttk.Button(actions,text="↓ Newer",width=8,command=lambda:self.history(1)).pack(side="left",padx=4)
        self.text=app.text_widget(self,height=3,wrap="none",takefocus=True)
        self.text.configure(undo=False,bg="#0b101a",fg="#e7edf7")
        self.text.grid(row=1,column=0,sticky="nsew")
        self.text.bind("<KeyPress>",self.key)
        self.text.bind("<Control-Shift-C>",self.copy)
        self.text.bind("<Control-Shift-V>",lambda e:(self.paste(),"break")[1])
        self.text.bind("<Button-1>",lambda e:self.text.focus_set(),add="+")
        scroll=ttk.Scrollbar(self,orient="horizontal",command=self.text.xview)
        scroll.grid(row=2,column=0,sticky="ew");self.text.configure(xscrollcommand=scroll.set)
        vertical=ttk.Scrollbar(self,command=self.text.yview);vertical.grid(row=1,column=1,sticky="ns")
        self.text.configure(yscrollcommand=vertical.set)
        self.hint=ttk.Label(self,wraplength=680,justify="left")
        self.hint.grid(row=3,column=0,columnspan=2,sticky="ew",pady=3)
        self.update_hint()
        self.render(force=True)

    @property
    def peer(self):return self.owner._peer

    @peer.setter
    def peer(self,value):self.owner._peer=value

    def pop_out(self):
        old=self.app.terminal_popup
        if old and old.winfo_exists():old.lift();old.focus_set();return
        win=tk.Toplevel(self.app);win.title("Probe · Live terminal");win.geometry("1080x620")
        win.configure(bg=self.app.colors["panel"])
        pane=TerminalPane(win,self.app,shared=self);pane.pack(fill="both",expand=True,padx=12,pady=12)
        self.app.terminal_popup=win;self.app.terminal_popout_pane=pane
        self.app.notebook.hide(self.app.terminal)
        def dock():
            if win.winfo_exists():win.destroy()
        def restore(event):
            if event.widget is not win:return
            if not getattr(self.app,"closing",False):
                self.app.notebook.add(self.app.terminal,text="Terminal")
                self.app.notebook.select(self.app.terminal)
            self.app.terminal_popup=None;self.app.terminal_popout_pane=None
        ttk.Button(pane,text="Dock in main window",command=dock).grid(row=4,column=0,sticky="e",pady=4)
        win.protocol("WM_DELETE_WINDOW",dock);win.bind("<Escape>",lambda e:dock())
        win.bind("<Destroy>",restore,add="+")

    def reset(self):
        if self.model:self.model.reset(self.app.vars["encoding"].get())
        self.peer=None;self.dirty=True;self.render(force=True)
        self.update_hint()

    def keyboard_changed(self):
        if self.keyboard.get():self.text.focus_set()
        self.update_hint()

    def update_hint(self):
        connected=self.app.engine is not None and self.app.engine.ready
        if self.error:message=self.error
        elif not connected:message="Disconnected · choose a connection and Connect. Received text stays visible; opening Terminal sends nothing."
        elif self.app.vars["mode"].get() in ("TCP Server","TCP Proxy") and not self.app.engine.clients:
            message="Listening · waiting for a TCP client. Previous received text stays visible."
        else:
            source=self.peer or "waiting for RX"
            message=f"RX · {source} · "+("Send keyboard ON · click the screen to type. " if self.keyboard.get() else "View only · enable Send keyboard to type. ")
            message+="Enter/Backspace are configurable · Ctrl+Shift+C/V copy/paste."
            if self.app.paused:message="Display paused · click Resume on Traffic. "+message
        if self.hint.cget("text")!=message:self.hint.configure(text=message)

    def feed(self,event):
        if not self.model or event["direction"]!="RX":return
        target=self.app.vars["target"].get()
        physical=self.app.vars["mode"].get() in ("USB / Serial","Serial Proxy","Serial ↔ TCP")
        if not physical and target!="All clients" and event["peer"]!=target and event.get("client_peer")!=target:return
        if self.peer is None:self.peer=event["peer"]
        if self.peer!=event["peer"]:
            clients=getattr(self.app.engine,"clients",{}) if self.app.engine else {}
            if not physical and target=="All clients" and self.peer not in clients:
                self.reset();self.peer=event["peer"]
            else:return
        replies=self.model.feed(event["data"]);self.dirty=True
        if self.keyboard.get():
            for data in replies:self.send(data)
        self.update_hint()

    def send(self,data):
        if not data:return
        try:
            self.app.send_terminal(data,self.peer)
            if self.local_echo.get() and self.model:self.model.feed(data);self.dirty=True;self.render()
        except Exception as exc:self.app.set_status(str(exc),True)

    def key(self,event):
        if not self.keyboard.get():
            self.app.set_status("Enable Keyboard in the terminal tab to send live keys.");return "break"
        try:
            data=key_bytes(event.keysym,event.char,bool(event.state&4),self.app.vars["encoding"].get(),self.enter.get(),self.backspace.get(),bool(self.model and (1<<5) in self.model.screen.mode))
            if event.state&8 and not event.state&4 and data:data=b"\x1b"+data
            self.send(data)
        except Exception as exc:self.app.set_status(str(exc),True)
        return "break"

    def paste(self):
        if not self.keyboard.get():self.app.set_status("Enable Keyboard before pasting to the device.",True);return
        try:self.send(self.app.clipboard_get().encode(self.app.vars["encoding"].get()))
        except (tk.TclError,UnicodeError) as exc:self.app.set_status(str(exc),True)

    def copy(self,event=None):
        try:
            text=self.text.get("sel.first","sel.last")
            self.app.clipboard_clear();self.app.clipboard_append(text)
        except tk.TclError:pass
        return "break"

    def history(self,direction):
        if self.model:
            (self.model.screen.prev_page if direction<0 else self.model.screen.next_page)()
            self.model.revision+=1
            self.dirty=True;self.render(force=True)

    @staticmethod
    def color(value,default):
        if value=="default":return default
        if value in PALETTE:return PALETTE[value]
        if re.fullmatch(r"[0-9a-fA-F]{6}",value):return "#"+value
        return default

    def tag(self,char):
        key=(char.fg,char.bg,char.bold,char.italics,char.underscore,char.strikethrough,char.reverse)
        if key not in self.tags:
            if len(self.tags)>=512:return "fallback"
            name=f"style{len(self.tags)}";self.tags[key]=name
            fg=self.color(char.fg,"#e7edf7");bg=self.color(char.bg,"#0b101a")
            if char.reverse:fg,bg=bg,fg
            styles=tuple(s for s,on in (("bold",char.bold),("italic",char.italics)) if on)
            self.text.tag_configure(name,foreground=fg,background=bg,font=(self.app.mono,self.app.font_size,*styles),underline=char.underscore,overstrike=char.strikethrough)
        return self.tags.get(key,"fallback")

    def render(self,force=False):
        revision=self.model.revision if self.model else 0
        if not force and (self.app.paused or not self.dirty and revision==self.last_revision):return
        self.last_revision=revision
        self.dirty=False;self.text.configure(state="normal");self.text.delete("1.0","end")
        if self.error:self.text.insert("1.0",self.error)
        elif self.model:
            screen=self.model.screen
            for row in range(screen.lines):
                run="";tag=None
                for col in range(screen.columns):
                    char=screen.buffer[row][col];new_tag=self.tag(char)
                    if new_tag!=tag and run:self.text.insert("end",run,tag);run=""
                    run+=char.data;tag=new_tag
                if run:self.text.insert("end",run,tag)
                if row<screen.lines-1:self.text.insert("end","\n")
            cursor=screen.cursor
            self.text.tag_configure("cursor",background="#49d6b4",foreground="#08251f")
            if not cursor.hidden:self.text.tag_add("cursor",f"{cursor.y+1}.{cursor.x}",f"{cursor.y+1}.{cursor.x+1}")
            self.text.see(f"{cursor.y+1}.{min(cursor.x,screen.columns-1)}")
            screen.dirty.clear()
        self.text.configure(state="disabled")
