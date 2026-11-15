'A snapshot of one message across two probes, using the existing diff view.'
import tkinter as tk
from tkinter import ttk

from ..codec import visible
from ..trace_path import combine, find_matches, flow, message
from .comparison import ComparePane
from .widgets import Actions, entry, modal, table


class TraceWindow(tk.Toplevel,Actions):
    def __init__(self,window,source):
        super().__init__(window);self.window=window;self.app=source
        self.title('Probe · Trace path');self.geometry('1040x650');self.minsize(920,580)
        self.configure(bg=source.colors['panel']);self.transient(window)
        self.bind('<Escape>',lambda _:self.destroy())
        body=ttk.Frame(self,padding=16);body.pack(fill='both',expand=True)
        ttk.Label(body,text='Follow a message',font=(source.ui_font,18,'bold')).pack(anchor='w')
        self.names={f'{p.slot} · {window.names[p]}':p for p in window.probes}
        self.probes=tuple(self.names.values())
        name=next(name for name,p in self.names.items() if p is source)
        self.source=tk.StringVar(self,value=name)
        targets=tuple(n for n in self.names if n!=name)
        self.target=tk.StringVar(self,value=targets[0] if targets else '')
        self.reference=tk.StringVar(self);self.field=tk.StringVar(self);self.all_rows=tk.BooleanVar(self)
        self.feedback=tk.StringVar(self);self.note=tk.StringVar(self)
        if not targets:
            self.geometry('570x245');self.minsize(490,220)
            self.feedback.set('To compare two different probes, first add a tab for the other point in the link.')
            ttk.Label(body,textvariable=self.feedback,wraplength=480).pack(anchor='w',pady=8)
            ttk.Label(body,text='Set up a live connection there or open a saved capture. Then come back to this message.',wraplength=480).pack(anchor='w',pady=(0,12))
            self.new_target_button=ttk.Button(body,text='Add a second probe',style='Accent.TButton',command=self.add_target)
            self.new_target_button.pack(anchor='w')
            self.lift();self.focus_set()
            return
        ttk.Label(body,text=f'From {name}. Choose where to look for the same message. Nothing is sent.',wraplength=970).pack(anchor='w',pady=6)
        controls=ttk.Frame(body);controls.pack(fill='x');controls.columnconfigure((0,1),weight=1)
        self.reference_combo=entry(controls,'Message to follow',self.reference,0,values=('—',),width=42)
        self.reference_combo.bind('<<ComboboxSelected>>',lambda _:self.action(self.match))
        target=entry(controls,'Look in this probe',self.target,0,1,values=targets,width=30)
        target.bind('<<ComboboxSelected>>',lambda _:self.snapshot())
        bar=ttk.Frame(body);bar.pack(fill='x',pady=8)
        options=ttk.Frame(body)
        field=entry(options,'JSON field present in both messages (e.g. data.sessionId)',self.field,0,width=34)
        field.bind('<Return>',lambda _:self.action(self.match))
        ttk.Button(options,text='Find by field',command=lambda:self.action(self.match)).grid(row=0,column=1,sticky='s')
        advanced=tk.BooleanVar(self)
        def show_field():
            if advanced.get():
                options.pack(fill='x',after=bar);field.focus_set()
            else:
                options.pack_forget();self.field.set('');self.action(self.match)
        ttk.Button(bar,text='Refresh traffic',command=self.snapshot).pack(side='left')
        ttk.Checkbutton(bar,text='Match by JSON field',variable=advanced,command=show_field).pack(side='left',padx=8)
        ttk.Checkbutton(bar,text='Browse other traffic',variable=self.all_rows,command=self.render).pack(side='left')
        self.compare_button=ttk.Button(bar,text='Compare messages…',style='Accent.TButton',command=lambda:self.action(self.compare))
        self.compare_button.pack(side='right')
        ttk.Label(body,textvariable=self.note,wraplength=970).pack(anchor='w',pady=4)
        ttk.Label(body,textvariable=self.feedback,wraplength=970).pack(side='bottom',anchor='w',pady=6)
        ttk.Label(body,text='Intervals use recorded timestamps, not device latency. Matching bytes/IDs are evidence, not proof of causality.',wraplength=970).pack(side='bottom',anchor='w')
        self.view=table(body,(('keys','Traffic # / byte span',180),('flow','Flow / peer',155),('size','Bytes',60),('interval','Observed interval',115),('state','Comparison',95),('preview','Payload',200)))
        self.view.configure(selectmode='extended')
        self.view.bind('<<TreeviewSelect>>',lambda _:self.selection_changed())
        self.view.bind('<Double-1>',lambda _:self.action(self.compare))
        self.view.tag_configure('Changed',foreground=source.colors['red'])
        self.snapshot()
        self.deiconify();self.lift();self.focus_set()

    def add_target(self):
        probe=self.window.new_probe()
        if probe:
            probe.set_status('Set up the other point in the link, then follow a message from the first probe.')
            self.destroy()

    def destroy(self):
        if self.window.__dict__.get('trace_window') is self:self.window.trace_window=None
        super().destroy()

    def snapshot(self):
        self.app=self.names[self.source.get()];self.other=self.names[self.target.get()]
        self.references={f"#{key} · {e['direction']} · {e.get('peer','')} · {len(e['data'])} bytes":dict(e)
                         for key,e in self.app.events.items()}
        previous=self.reference.get();selected=self.app.table.selection()
        preferred=next((label for label in self.references if selected and label.startswith('#'+selected[0]+' ·')),None)
        self.reference_combo.configure(values=tuple(self.references) or ('—',))
        self.reference.set(previous if previous in self.references else preferred or next(reversed(self.references),'—'))
        self.rows=tuple((key,dict(event)) for key,event in self.other.events.items())
        self.action(self.match)

    def match(self):
        self.matches=[];self.base=self.references.get(self.reference.get())
        try:
            if self.base is None:raise ValueError('No reference traffic yet. Capture or open a file in the first probe, then refresh.')
            self.matches=find_matches(self.base,self.rows,self.field.get())
        finally:self.render()

    def render(self):
        self.view.delete(*self.view.get_children());self.items={}
        self.feedback.set('')
        base=getattr(self,'base',None)
        if not base:self.note.set('');self.selection_changed();return
        manual=self.all_rows.get()
        items=[message((key,),event) for key,event in self.rows] if manual else self.matches
        for i,event in enumerate(items):
            key=str(i);self.items[key]=event
            known=not manual;state=('Unchanged' if event['data']==base['data'] else 'Changed') if known else 'Select to compare'
            self.view.insert('','end',iid=key,values=(event['span'] or ', '.join('#'+k for k in event['keys']),
                f"{event['direction']} · {event.get('peer','')}"+(f" · {event['client_peer']}" if event.get('client_peer') else ''),len(event['data']),
                f"{(event['time']-base['time'])*1000:+.3f} ms",state,visible(event['data'][:100])),tags=(state,))
        count=len(self.matches)
        if manual:summary='Pick a message, or select consecutive chunks in the same flow.'
        elif not self.rows:summary='This probe has no traffic yet. Capture or open a file there, then refresh.'
        elif not count:summary='No match yet in this snapshot. Try a JSON field or browse other traffic to compare manually.'
        elif count==1:summary='One match found. Compare the two messages to see what changed.'
        else:summary=f'{count}{"+" if count==100 else ""} matches; choose the intended occurrence.'
        self.note.set(summary)
        if not manual and count==1:self.view.selection_set('0')
        self.selection_changed()

    def selection_changed(self):
        self.compare_button.configure(state='normal' if self.view.selection() and getattr(self,'base',None) and self.app is not self.other else 'disabled')

    def compare(self):
        chosen=[self.items[key] for key in self.view.selection()]
        if not chosen:raise ValueError('Select target traffic first.')
        if len(chosen)>1 and self.matches and not self.all_rows.get():raise ValueError('Choose one occurrence, or browse other traffic to combine chunks manually.')
        if len(chosen)>1:
            selected={key for item in chosen for key in item['keys']}
            indices=[i for i,(key,_) in enumerate(self.rows) if key in selected]
            a,b=indices[0],indices[-1]
            same_flow=[row for row in self.rows[a:b+1] if flow(row[1])==flow(chosen[0])]
            if any(key not in selected for key,_ in same_flow):raise ValueError('Select consecutive chunks within the same flow.')
            target=combine([row for row in self.rows if row[0] in selected])
        else:target=chosen[0]
        win=modal(self,'Capture Diff · trace path','1000x740',(920,700))
        pane=ComparePane(win,self.app,a=self.base['data'],a_label=self.source.get()+' · '+self.reference.get(),
            b=target['data'],b_label=self.target.get()+' · '+(target['span'] or ', '.join('#'+k for k in target['keys']))+' · '+target['method'])
        pane.pack(fill='both',expand=True);pane.sources={'A':self.app,'B':self.other}
        pane.picker_state={'A':(self.base['direction'],self.base.get('peer','')),'B':(target['direction'],target.get('peer',''))}
        win.comparison=pane
        return win
