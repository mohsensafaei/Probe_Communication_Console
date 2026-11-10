import json
from pathlib import Path
import queue
import threading
import tkinter as tk
from tkinter import filedialog, ttk

from ..evidence.case import SETTINGS, build_case, save_case, select_rows, summary
from .widgets import Actions, modal


class CaseDialog(Actions):
    def __init__(self,app,selection):
        self.app=app;self.window=modal(app,'Share diagnostic case','900x720',(760,620))
        self.feedback=tk.StringVar();self.context=tk.StringVar(value='0');self.others=tk.BooleanVar(value=False)
        self.payload=tk.BooleanVar(value=True);self.case=None;self.busy=False
        self.snapshots=[]
        for probe in app.window.probes:
            chosen=selection if probe is app else probe.selected_traffic()
            if not chosen:continue
            config={k:probe.vars[k].get() for k in SETTINGS if k in probe.vars}
            if probe.engine:config.update({k:v for k,v in probe.engine.cfg.items() if k in SETTINGS})
            plugins=[{k:e[k] for k in ('name','enabled','direction','changes') if k in e} for e in probe.plugins.entries]
            stats=probe.queue.stats()
            self.snapshots.append(dict(primary=probe is app,name=app.window.names[probe],
                all_rows=list(probe.events.values()),selected={row['event_id'] for _,row in chosen},config=config,
                settings_session=probe.engine.session if probe.engine else None,fields=json.loads(probe.vars['protocol_fields'].get()),
                plugins=plugins,health=dict(scope='Current display counters since Clear; not full recording history.',
                retained=len(probe.events),evicted=probe.evicted,display_dropped=stats['dropped'],status_dropped=stats['dropped_controls'],
                recording_error=probe.engine.recording_error_message if probe.engine else '')))
        body=ttk.Frame(self.window,padding=16);body.pack(fill='both',expand=True)
        ttk.Label(body,text='Share selected evidence',font=(app.ui_font,18,'bold')).pack(anchor='w')
        ttk.Label(body,text='Creates local files or clipboard text. Nothing is sent, uploaded or executed. Review the preview before sharing.',wraplength=800).pack(anchor='w',pady=5)
        self.problem=self.text(body,'What went wrong?',2)
        self.expected=self.text(body,'Expected behavior',2)
        controls=ttk.Frame(body);controls.pack(fill='x',pady=5)
        ttk.Label(controls,text='Surrounding messages').pack(side='left')
        ttk.Spinbox(controls,from_=0,to=20,width=4,textvariable=self.context).pack(side='left',padx=6)
        ttk.Checkbutton(controls,text='Add selected messages from other probes',variable=self.others).pack(side='left')
        ttk.Checkbutton(body,text='Include payload bytes (turn off to share metadata only)',variable=self.payload).pack(anchor='w')
        self.masks=self.text(body,'Mask literal text everywhere (one value per line; no automatic secret detection)',2)
        footer=ttk.Frame(body);footer.pack(side='bottom',fill='x',pady=6)
        self.preview_button=ttk.Button(footer,text='Preview',command=lambda:self.action(self.preview));self.preview_button.pack(side='left')
        self.copy_button=ttk.Button(footer,text='Copy summary',state='disabled',command=lambda:self.action(self.copy));self.copy_button.pack(side='right')
        self.save_button=ttk.Button(footer,text='Save case…',state='disabled',command=lambda:self.action(self.save));self.save_button.pack(side='right',padx=6)
        ttk.Label(body,textvariable=self.feedback,wraplength=800).pack(side='bottom',anchor='w')
        self.output=app.text_widget(body,height=8,wrap='word');self.output.pack(fill='both',expand=True,pady=6)
        for variable in (self.context,self.others,self.payload):variable.trace_add('write',self.invalidate)
        self.preview()

    def text(self,parent,label,height):
        ttk.Label(parent,text=label).pack(anchor='w',pady=(3,0))
        text=self.app.text_widget(parent,height=height,wrap='word');text.pack(fill='x')
        text.bind('<<Modified>>',lambda e:self.edited(text));return text

    def edited(self,widget):
        if widget.edit_modified():widget.edit_modified(False);self.invalidate()

    def invalidate(self,*args):
        self.case=None;self.revision=getattr(self,'revision',0)+1
        if hasattr(self,'copy_button'):
            self.copy_button.configure(state='disabled');self.save_button.configure(state='disabled')
            self.feedback.set('Preview again after changing the case.')

    def preview(self):
        if self.busy:return
        self.window.update_idletasks();self.invalidate();revision=self.revision
        probes=[]
        for snapshot in self.snapshots:
            if snapshot['primary'] or self.others.get():
                probes.append(dict(snapshot,rows=select_rows(snapshot['all_rows'],snapshot['selected'],int(self.context.get()))))
        args=(probes,self.problem.get('1.0','end-1c'),self.expected.get('1.0','end-1c'),self.masks.get('1.0','end-1c').splitlines(),self.payload.get())
        self.busy=True;self.preview_button.configure(state='disabled');self.feedback.set('Building a read-only snapshot…')
        results=queue.SimpleQueue()
        def work():
            try:results.put((build_case(*args),''))
            except Exception as exc:results.put((None,str(exc)))
        threading.Thread(target=work,daemon=True,name='Probe case preview').start()
        def finish():
            if not self.window.winfo_exists():return
            if results.empty():self.app.after(40,finish);return
            case,error=results.get();self.busy=False;self.preview_button.configure(state='normal')
            if revision!=self.revision:
                self.feedback.set('Options changed. Preview again.');return
            self.case=case
            if error:self.feedback.set(error);return
            self.app.put_text(self.output,summary(case));self.copy_button.configure(state='normal');self.save_button.configure(state='normal')
            self.feedback.set(f"{len(case['events'])} messages / {len(case['probes'])} probes. Preview is abbreviated; ZIP includes all chosen bytes and findings.")
        self.app.after(40,finish)

    def copy(self):
        if self.case is None:raise ValueError('Preview the current case first.')
        self.window.clipboard_clear();self.window.clipboard_append(summary(self.case))
        self.feedback.set('Copied summary. Use Save case for exact bytes and structured findings.')

    def save(self):
        if self.case is None:raise ValueError('Preview the current case first.')
        path=filedialog.asksaveasfilename(parent=self.window,defaultextension='.zip',initialfile='probe-case.zip',filetypes=[('Diagnostic case','*.zip')])
        if path:save_case(Path(path),self.case);self.feedback.set('Saved diagnostic case. Original traffic is unchanged.')
