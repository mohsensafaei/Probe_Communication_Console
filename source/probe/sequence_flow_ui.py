"""Optional response rules and variables, outside the simple sequence workflow."""
import copy
import json
import tkinter as tk
from tkinter import ttk
from uuid import uuid4

from .analysis_ui import Actions, TrafficPicker, entry, modal, table
from .protocol import CHECKSUMS, inspect_payload
from .sequence_flow import (FORMATS, OPERATORS, SOURCES, compile_flow, display_value,
                            initial_variables, variable_name)

ACTION_LABELS={"Next message":"next","Go to message":"goto","Finish successfully":"stop","Fail test":"fail"}


class VariablesEditor(tk.Toplevel,Actions):
    def __init__(self,pane):
        definitions=json.loads(pane.app.vars["sequence_variables"].get());initial_variables(definitions)
        super().__init__(pane);self.pane=pane;self.app=pane.app;self.title("Probe · Sequence variables")
        self.geometry("780x580");self.minsize(720,540);self.transient(pane.winfo_toplevel());self.configure(bg=self.app.colors["panel"])
        self.feedback=tk.StringVar(value="Initial values reset at the start of each cycle. Reply fields can replace them during that cycle.")
        self.items=definitions
        self.name=tk.StringVar();self.kind=tk.StringVar(value="Text");self.value=tk.StringVar()
        body=ttk.Frame(self,padding=16);body.pack(fill="both",expand=True)
        ttk.Label(body,text="Sequence variables",font=(self.app.ui_font,18,"bold")).pack(anchor="w")
        ttk.Label(body,text="Use ${name} in a payload, ${name:json} for a JSON value, or ${name:hex} for binary bytes.",wraplength=710).pack(anchor="w",pady=6)
        footer=ttk.Frame(body);footer.pack(side="bottom",fill="x",pady=6)
        self.save_button=ttk.Button(footer,text="Save initial values",style="Accent.TButton",command=lambda:self.action(self.save));self.save_button.pack(side="right")
        ttk.Button(footer,text="Close",command=self.destroy).pack(side="right",padx=6)
        ttk.Label(body,textvariable=self.feedback,wraplength=710).pack(side="bottom",anchor="w",pady=4)
        tabs=ttk.Notebook(body);tabs.pack(fill="both",expand=True)
        initial=ttk.Frame(tabs,padding=8);latest=ttk.Frame(tabs,padding=8);tabs.add(initial,text="Initial values");tabs.add(latest,text="Last received values")
        form=ttk.Frame(initial);form.pack(fill="x")
        entry(form,"Name",self.name,0,width=20);entry(form,"Value format",self.kind,0,1,("Text","Hex","JSON"),12)
        entry(form,"Value",self.value,1,width=55)
        ttk.Button(form,text="Add / update",command=lambda:self.action(self.put)).grid(row=1,column=1,sticky="s",pady=4)
        self.view=table(initial,(("name","Name",180),("format","Format",90),("value","Initial value",390)))
        self.view.bind("<<TreeviewSelect>>",lambda e:self.selected())
        ttk.Button(initial,text="Remove selected",command=lambda:self.action(self.remove)).pack(anchor="w")
        ttk.Label(latest,text="Values from the latest run. Click Refresh while a sequence is running.").pack(anchor="w")
        ttk.Button(latest,text="Refresh",command=self.refresh_live).pack(anchor="w",pady=6)
        self.live=table(latest,(("name","Variable",200),("value","Latest value",450)))
        self.refresh();self.refresh_live()
        if pane.busy():self.save_button.configure(state="disabled");tabs.select(latest)
        self.grab_set();self.bind("<Escape>",lambda e:self.destroy())

    def refresh(self):
        self.view.delete(*self.view.get_children())
        for name,item in self.items.items():self.view.insert("","end",iid=name,values=(name,item["format"],item["value"][:150]))

    def refresh_live(self):
        self.live.delete(*self.live.get_children())
        for name,value in getattr(self.app,"sequence_values",{}).items():self.live.insert("","end",values=(name,value))

    def selected(self):
        ids=self.view.selection()
        if ids:
            item=self.items[ids[0]];self.name.set(ids[0]);self.kind.set(item["format"]);self.value.set(item["value"])

    def put(self):
        self.pane.ensure_idle();name=variable_name(self.name.get().strip());item=dict(format=self.kind.get(),value=self.value.get())
        proposed={**self.items,name:item};initial_variables(proposed);self.items=proposed;self.refresh();self.view.selection_set(name)

    def remove(self):
        self.pane.ensure_idle()
        if not self.view.selection():raise ValueError("Select a variable first.")
        del self.items[self.view.selection()[0]];self.refresh()

    def save(self):
        self.pane.ensure_idle();initial_variables(self.items)
        self.app.vars["sequence_variables"].set(json.dumps(self.items));self.app.save_settings()
        self.pane.feedback.set(f"Saved {len(self.items)} initial variables. Use Insert variable in the message editor.");self.destroy()


class ResponseRules(tk.Toplevel,Actions):
    def __init__(self,pane):
        super().__init__(pane.editor);self.pane=pane;self.app=pane.app
        self.title("Probe · Response & next step");self.geometry("880x720");self.minsize(820,680)
        self.configure(bg=self.app.colors["panel"]);self.transient(pane.editor)
        self.feedback=tk.StringVar(value="Saving fields/checking a variable waits for a complete reply field, using the sequence/message timeout.")
        self.items=copy.deepcopy(pane.editor_flow.get("extract",[]))
        self.packet=copy.deepcopy(pane.editor_packet)
        self.name=tk.StringVar(value="sessionId");self.source=tk.StringVar(value="JSON");self.selector=tk.StringVar(value="data.sessionId")
        self.offset=tk.StringVar(value="0");self.length=tk.StringVar(value="1");self.format=tk.StringVar(value="Text")
        self.check=tk.BooleanVar(value=bool(pane.editor_flow.get("condition")))
        condition=pane.editor_flow.get("condition",{})
        self.condition_variable=tk.StringVar(value=condition.get("variable",""));self.operator=tk.StringVar(value=condition.get("operator","equals"));self.expected=tk.StringVar(value=str(condition.get("value","")))
        for row in pane.app.macros:
            if not row.get("step_id"):row["step_id"]=uuid4().hex
        if pane.edit_index is not None:pane.editor_step_id=pane.app.macros[pane.edit_index]["step_id"]
        elif not pane.editor_step_id:pane.editor_step_id=uuid4().hex
        self.destinations={f"{i+1} · {row.get('name','Message')}":row["step_id"] for i,row in enumerate(pane.app.macros)}
        if pane.edit_index is None:self.destinations[f"{len(pane.app.macros)+1} · this new message"]=pane.editor_step_id
        self.routes={}
        body=ttk.Frame(self,padding=16);body.pack(fill="both",expand=True)
        ttk.Label(body,text="Response & next step",font=(self.app.ui_font,18,"bold")).pack(anchor="w")
        ttk.Label(body,text="Optional: save values from this reply, then choose what happens next. Nothing is sent from this dialog.",wraplength=810).pack(anchor="w",pady=4)
        footer=ttk.Frame(body);footer.pack(side="bottom",fill="x",pady=6)
        ttk.Button(footer,text="Save rules",style="Accent.TButton",command=lambda:self.action(self.save)).pack(side="right")
        ttk.Button(footer,text="Cancel",command=self.destroy).pack(side="right",padx=6)
        ttk.Button(footer,text="Clear rules",command=self.clear).pack(side="left")
        ttk.Button(footer,text="Outgoing frame…",command=self.frame_options).pack(side="left",padx=6)
        ttk.Label(body,textvariable=self.feedback,wraplength=810).pack(side="bottom",anchor="w",pady=4)
        self.tabs=ttk.Notebook(body);self.tabs.pack(fill="both",expand=True,pady=6)
        fields_page=ttk.Frame(self.tabs,padding=8);routes_page=ttk.Frame(self.tabs,padding=8)
        self.tabs.add(fields_page,text="Save reply values");self.tabs.add(routes_page,text="Choose next step")
        form=ttk.Frame(fields_page);form.pack(fill="x")
        entry(form,"Save as variable",self.name,0,width=18)
        source_combo=entry(form,"Reply format",self.source,0,1,SOURCES,12)
        ttk.Button(form,text="Pick field from captured reply…",command=self.pick_reply).grid(row=0,column=2,sticky="s",pady=4)
        details=ttk.Frame(fields_page);details.pack(fill="x")
        self.selector_box=ttk.Frame(details);self.selector_box.pack(side="left")
        self.selector_entry=entry(self.selector_box,"JSON path or TLV tag",self.selector,0,width=34)
        self.bytes_box=ttk.Frame(details)
        entry(self.bytes_box,"Byte offset",self.offset,0,width=12);entry(self.bytes_box,"Byte length",self.length,0,1,width=12)
        self.format_box=ttk.Frame(details)
        entry(self.format_box,"Decode value as",self.format,0,values=FORMATS,width=14)
        ttk.Button(details,text="Add / update field",command=lambda:self.action(self.put)).pack(side="right",anchor="s",pady=4)
        def change(*_):
            self.selector_box.pack_forget();self.bytes_box.pack_forget();self.format_box.pack_forget()
            if self.source.get()=="Bytes":self.bytes_box.pack(side="left")
            else:self.selector_box.pack(side="left")
            if self.source.get()!="JSON":self.format_box.pack(side="left")
        source_combo.bind("<<ComboboxSelected>>",change);self.change_source=change;change()
        remove_bar=ttk.Frame(fields_page);remove_bar.pack(side="bottom",fill="x")
        ttk.Button(remove_bar,text="Remove selected field",command=lambda:self.action(self.remove)).pack(anchor="w")
        self.view=table(fields_page,(("name","Variable",150),("source","Reply format",120),("field","Field / bytes",350),("format","Value format",140)),height=3)
        self.view.bind("<<TreeviewSelect>>",lambda e:self.selected())
        ttk.Label(routes_page,text="Choose what happens after this message",font=(self.app.ui_font,15,"bold")).pack(anchor="w",pady=6)
        ttk.Checkbutton(routes_page,text="Use a variable condition",variable=self.check,command=self.toggle_condition).pack(anchor="w",pady=(6,3))
        self.condition_box=ttk.Frame(routes_page)
        self.condition_combo=entry(self.condition_box,"Variable",self.condition_variable,0,values=("sessionId",),width=20)
        entry(self.condition_box,"Comparison",self.operator,0,1,OPERATORS,16);entry(self.condition_box,"Value",self.expected,0,2,width=24)
        self.route_box=ttk.Frame(routes_page);self.route_box.pack(fill="x",pady=10)
        for key,label,default in (("on_true","After reply / condition true","next"),("on_false","If condition is false","fail"),("on_timeout","If reply times out","fail")):
            config=pane.editor_flow.get(key,{"action":default});line=ttk.Frame(self.route_box);line.pack(fill="x",pady=3)
            ttk.Label(line,text=label,width=27).pack(side="left")
            action=tk.StringVar(value=next((name for name,value in ACTION_LABELS.items() if value==config.get("action")),"Next message"))
            target=tk.StringVar(value=next((name for name,value in self.destinations.items() if value==config.get("target")),next(iter(self.destinations),"")))
            combo=ttk.Combobox(line,textvariable=action,values=list(ACTION_LABELS),state="readonly",width=21);combo.pack(side="left",padx=6)
            destination=ttk.Combobox(line,textvariable=target,values=list(self.destinations),state="readonly",width=29);destination.pack(side="left")
            def update(event=None,a=action,w=destination):w.configure(state="readonly" if ACTION_LABELS[a.get()]=="goto" else "disabled")
            combo.bind("<<ComboboxSelected>>",update);update()
            self.routes[key]=(action,target,line)
        ttk.Label(routes_page,text="Go to targets stay attached to their message when you reorder it.\nA missing field/value fails the test. Loops are limited to 10000 message visits per cycle.",wraplength=750).pack(anchor="w",pady=12)
        self.toggle_condition();self.refresh();self.grab_set();self.bind("<Escape>",lambda e:self.destroy())

    def toggle_condition(self):
        if self.check.get():self.condition_box.pack(fill="x",before=self.route_box)
        else:self.condition_box.pack_forget()
        if hasattr(self,"routes") and "on_false" in self.routes:
            line=self.routes["on_false"][2]
            if self.check.get():line.pack(fill="x",pady=3,before=self.routes["on_timeout"][2])
            else:line.pack_forget()

    def refresh(self):
        self.view.delete(*self.view.get_children())
        for i,item in enumerate(self.items):
            field=item.get("selector","") if item["source"]!="Bytes" else f"{item.get('offset',0)}:{int(item.get('offset',0))+int(item.get('length',1))}"
            self.view.insert("","end",iid=str(i),values=(item["name"],item["source"],field,item.get("format","Text")))
        names=set(json.loads(self.app.vars["sequence_variables"].get()))|{item["name"] for item in self.items}
        for row in self.app.macros:names.update(item["name"] for item in row.get("flow",{}).get("extract",[]))
        self.condition_combo.configure(values=sorted(names) or ("sessionId",))

    def selected(self):
        ids=self.view.selection()
        if not ids:return
        item=self.items[int(ids[0])]
        for key in ("name","source","selector","offset","length","format"):
            variable=getattr(self,key);variable.set(str(item.get(key,{"offset":0,"length":1,"format":"Text"}.get(key,""))))
        self.change_source()

    def put(self):
        item=dict(name=self.name.get().strip(),source=self.source.get(),selector=self.selector.get().strip(),offset=self.offset.get(),length=self.length.get(),format=self.format.get())
        compile_flow({"flow":{"extract":[item]}})
        proposed=[dict(row) for row in self.items]
        old=next((i for i,row in enumerate(proposed) if row["name"]==item["name"]),None)
        if old is None:proposed.append(item)
        else:proposed[old]=item
        compile_flow({"flow":{"extract":proposed}});self.items=proposed;self.refresh()
        self.feedback.set(f"Saved field rule '{item['name']}'. Click Save rules, then Save message to apply.")

    def remove(self):
        if not self.view.selection():raise ValueError("Select a reply field first.")
        del self.items[int(self.view.selection()[0])];self.refresh()

    def save(self):
        rule={"extract":self.items}
        if self.check.get():rule["condition"]=dict(variable=self.condition_variable.get(),operator=self.operator.get(),value=self.expected.get())
        for key,(action,target,_) in self.routes.items():
            kind=ACTION_LABELS[action.get()];rule[key]={"action":kind}
            if kind=="goto":rule[key]["target"]=self.destinations[target.get()]
        compile_flow({"flow":rule});self.pane.editor_flow=copy.deepcopy(rule)
        self.pane.editor_packet=copy.deepcopy(self.packet)
        self.pane.editor_feedback.set("Response rules ready. Save message applies them; Cancel discards this message edit.")
        self.destroy()

    def clear(self):self.pane.editor_flow={};self.pane.editor_feedback.set("Rules cleared. Save message to apply.");self.destroy()

    def frame_options(self):
        win=modal(self,"Outgoing frame","660x430",(620,410));body=ttk.Frame(win,padding=16);body.pack(fill="both",expand=True)
        ttk.Label(body,text="Build the frame after variable substitution",font=(self.app.ui_font,16,"bold")).pack(anchor="w")
        ttk.Label(body,text="Checksums cover prefix + payload. ASCII length counts the final body, including checksum, suffix and ending.",wraplength=600).pack(anchor="w",pady=6)
        variables={key:tk.StringVar(value=str(value)) for key,value in self.packet.items()}
        form=ttk.Frame(body);form.pack(fill="x")
        entry(form,"Prefix (hex)",variables["prefix"],0);entry(form,"Suffix (hex)",variables["suffix"],0,1)
        entry(form,"Checksum",variables["checksum"],1,values=("None",)+CHECKSUMS)
        entry(form,"ASCII length digits (0 = none)",variables["length_prefix"],1,1)
        feedback=tk.StringVar();ttk.Label(body,textvariable=feedback,wraplength=600).pack(anchor="w",pady=8)
        def save():
            try:
                from .sequence_flow import send_spec
                proposed={key:variable.get() for key,variable in variables.items()}
                send_spec(dict(text="00",send_mode="Hex",**proposed));self.packet=proposed;win.destroy();self.grab_set()
            except (ValueError,KeyError,TypeError) as exc:feedback.set(str(exc))
        footer=ttk.Frame(body);footer.pack(side="bottom",fill="x")
        ttk.Button(footer,text="Save frame options",style="Accent.TButton",command=save).pack(side="right")
        ttk.Button(footer,text="Cancel",command=win.destroy).pack(side="right",padx=6)
        win.grab_set();return win

    def pick_reply(self):
        return TrafficPicker(self.app,self.reply_chosen,self)

    def reply_chosen(self,data,label):
        mode={"JSON":"JSON","TLV":"TLV (1-byte)","BER-TLV":"BER-TLV","Bytes":"Raw bytes"}[self.source.get()]
        try:_,fields=inspect_payload(data,mode)
        except ValueError as exc:self.feedback.set(str(exc));return
        fields=[field for field in fields if field.selector or mode=="Raw bytes"]
        win=modal(self,"Choose reply field","760x500",(700,460));body=ttk.Frame(win,padding=16);body.pack(fill="both",expand=True)
        ttk.Label(body,text="Choose the value to save",font=(self.app.ui_font,17,"bold")).pack(anchor="w")
        ttk.Label(body,text=label,wraplength=690).pack(anchor="w",pady=4)
        footer=ttk.Frame(body);footer.pack(side="bottom",fill="x")
        view=table(body,(("field","Reply field",300),("value","Current value",350)))
        for i,field in enumerate(fields):view.insert("","end",iid=str(i),values=(field.selector or f"Bytes {field.offset}:{field.offset+field.size}",field.value))
        feedback=tk.StringVar();ttk.Label(footer,textvariable=feedback).pack(side="left")
        def choose():
            if not view.selection():feedback.set("Select a field first.");return
            field=fields[int(view.selection()[0])];self.selector.set(field.selector)
            self.offset.set(str(field.offset));self.length.set(str(max(1,field.size)))
            candidate=field.selector.rsplit("/",1)[-1].split(".")[-1]
            try:self.name.set(variable_name(candidate))
            except ValueError:pass
            win.destroy();self.grab_set();self.feedback.set("Field selected. Choose its variable name, then Add / update field.")
        ttk.Button(footer,text="Use this field",style="Accent.TButton",command=choose).pack(side="right")
        ttk.Button(footer,text="Cancel",command=win.destroy).pack(side="right",padx=6)
        win.grab_set();self.reply_field_window=win;self.reply_field_view=view;self.choose_reply_field=choose
        return win
