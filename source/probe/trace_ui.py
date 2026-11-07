"""A snapshot of one message across two probes, using the existing diff view."""
import tkinter as tk
from tkinter import ttk
from .analysis_ui import Actions, ComparePane, entry, modal, table
from .codec import visible
from .trace_path import combine, find_matches, flow, message


class TraceWindow(tk.Toplevel,Actions):
    def __init__(self,window,source):
        super().__init__(window);self.window=window;self.app=source
        self.title('Probe · Trace path');self.geometry('1040x650');self.minsize(920,580)
        self.configure(bg=source.colors['panel']);self.transient(window)
        self.bind('<Escape>',lambda _:self.destroy())
        body=ttk.Frame(self,padding=16);body.pack(fill='both',expand=True)
        ttk.Label(body,text='Follow a message across two probes',font=(source.ui_font,18,'bold')).pack(anchor='w')
        ttk.Label(body,text='Choose a reference, then a target probe. Nothing is sent. Refresh takes a new snapshot.').pack(anchor='w',pady=6)
        controls=ttk.Frame(body);controls.pack(fill='x');controls.columnconfigure((0,1),weight=1)
        self.names={f'{p.slot} · {window.names[p]}':p for p in window.probes}
        self.probes=tuple(self.names.values())
        name=next(name for name,p in self.names.items() if p is source)
        self.source=tk.StringVar(self,value=name)
        self.target=tk.StringVar(self,value=next((n for n in self.names if n!=name),name))
        self.reference=tk.StringVar(self);self.field=tk.StringVar(self);self.all_rows=tk.BooleanVar(self)
        self.feedback=tk.StringVar(self);self.note=tk.StringVar(self)
        a=entry(controls,'1. Reference probe',self.source,0,values=tuple(self.names),width=35)
        b=entry(controls,'2. Target probe',self.target,0,1,values=tuple(self.names),width=35)
        a.bind('<<ComboboxSelected>>',lambda _:self.snapshot());b.bind('<<ComboboxSelected>>',lambda _:self.snapshot())
        self.reference_combo=entry(controls,'Reference message',self.reference,1,values=('—',),width=45)
        self.reference_combo.bind('<<ComboboxSelected>>',lambda _:self.action(self.match))
        field=entry(controls,'Optional JSON identifier · e.g. sessionId or data.sessionId',self.field,1,1,width=35)
        field.bind('<Return>',lambda _:self.action(self.match))
        bar=ttk.Frame(body);bar.pack(fill='x',pady=8)
        ttk.Button(bar,text='Find matches',command=lambda:self.action(self.match),style='Accent.TButton').pack(side='left')
        ttk.Button(bar,text='Refresh traffic',command=self.snapshot).pack(side='left',padx=6)
        ttk.Checkbutton(bar,text='Show all target traffic / select manually',variable=self.all_rows,command=self.render).pack(side='left',padx=6)
        self.compare_button=ttk.Button(bar,text='Compare selected…',command=lambda:self.action(self.compare))
        self.compare_button.pack(side='right')
        ttk.Label(body,textvariable=self.note,wraplength=970).pack(anchor='w',pady=4)
        ttk.Label(body,textvariable=self.feedback,wraplength=970).pack(side='bottom',anchor='w',pady=6)
        ttk.Label(body,text='Intervals use recorded timestamps, not device latency. Matching bytes/IDs are evidence, not proof of causality.',wraplength=970).pack(side='bottom',anchor='w')
        self.view=table(body,(('keys','Traffic # / byte span',210),('flow','Flow / peer',170),('size','Bytes',60),('interval','Observed interval',115),('state','Comparison',95),('method','Matched by',170),('preview','Payload',200)))
        self.view.configure(selectmode='extended')
        self.view.bind('<<TreeviewSelect>>',lambda _:self.selection_changed())
        self.view.bind('<Double-1>',lambda _:self.action(self.compare))
        self.view.tag_configure('Changed',foreground=source.colors['red'])
        self.snapshot()

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
        self.matches=[];self.base=self.references.get(self.reference.get());self.render()
        if self.app is self.other:raise ValueError('Choose two different probes. Add another probe with + first.')
        if self.base is None:raise ValueError('No reference traffic yet. Capture or import traffic, then Refresh.')
        self.matches=find_matches(self.base,self.rows,self.field.get());self.render()

    def render(self):
        self.view.delete(*self.view.get_children());self.items={}
        self.feedback.set('')
        base=getattr(self,'base',None)
        if not base:self.selection_changed();return
        manual=self.all_rows.get() or not self.matches
        items=[message((key,),event) for key,event in self.rows] if manual else self.matches
        for i,event in enumerate(items):
            key=str(i);self.items[key]=event
            known=not manual;state=('Unchanged' if event['data']==base['data'] else 'Changed') if known else 'Select to compare'
            self.view.insert('','end',iid=key,values=(event['span'] or ', '.join('#'+k for k in event['keys']),
                f"{event['direction']} · {event.get('peer','')}"+(f" · {event['client_peer']}" if event.get('client_peer') else ''),len(event['data']),
                f"{(event['time']-base['time'])*1000:+.3f} ms",state,event['method'],visible(event['data'][:100])),tags=(state,))
        count=len(self.matches)
        summary='No match yet in retained traffic; select manually below.' if not count else 'One match found.' if count==1 else f'{count}{"+" if count==100 else ""} matches; choose the intended occurrence.'
        self.note.set(summary+' Use framing for JSON split across chunks. Refresh includes new traffic.')
        if not manual and count==1:self.view.selection_set('0')
        self.selection_changed()

    def selection_changed(self):
        self.compare_button.configure(state='normal' if self.view.selection() and getattr(self,'base',None) and self.app is not self.other else 'disabled')

    def compare(self):
        chosen=[self.items[key] for key in self.view.selection()]
        if not chosen:raise ValueError('Select target traffic first.')
        if len(chosen)>1 and self.matches and not self.all_rows.get():raise ValueError('Choose one occurrence, or Show all target traffic to combine chunks manually.')
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
