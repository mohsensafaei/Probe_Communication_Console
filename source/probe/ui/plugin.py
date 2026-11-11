'Plugin controls and results inside the existing workbench.'
import json
import queue
import shutil
import tkinter as tk
from collections import OrderedDict
from itertools import islice
from pathlib import Path
from tkinter import filedialog, simpledialog, ttk
from uuid import uuid4

from ..plugins import PluginWorker, metadata


class Plugins:
    def __init__(self, app):
        self.app = app; self.base = app.settings_path.parent
        self.results = OrderedDict(); self.callbacks = {}; self.inflight = set()
        self.bytes = 0; self.generation = 0; self.serial = 0; self.error = ''
        try:
            self.entries = json.loads(app.vars['plugins'].get())
            if not isinstance(self.entries,list) or not all(isinstance(e,dict) for e in self.entries):raise ValueError
            self.entries=self.entries[:8]
        except (ValueError, TypeError): self.entries = []
        self.worker = None
        try:self.configure(self.entries)
        except (ValueError,OSError,SyntaxError,KeyError) as exc:app.set_status('Plugins unavailable: '+str(exc),True)

    def configure(self, entries):
        resolved = []
        for entry in entries:
            if not entry.get('enabled'): continue
            path = self.base / entry['path']; metadata(path)
            resolved.append(dict(entry, path=str(path)))
        if self.worker: self.worker.close()
        self.entries = entries; self.generation += 1; self.results.clear(); self.callbacks.clear()
        self.completions=queue.Queue(maxsize=64)
        self.inflight.clear(); self.bytes = 0; self.error = ''
        self.worker = PluginWorker(resolved) if resolved else None
        self.app.vars['plugins'].set(json.dumps(entries))
        if self.worker:self.request('ready',{})

    def context(self, event):
        return {k: event[k] for k in ('direction', 'peer', 'client_peer', 'time', 'monotonic_ns', 'session') if k in event} | {
            'workspace': self.app.slot, 'mode': self.app.vars['mode'].get(),
            'peer':event.get('peer',''),'session':event.get('session','offline')}

    def request(self, operation, event, key=None, callback=None, **options):
        if not self.worker: return
        if operation == 'process' and key in self.inflight: return
        if operation=='process' and len(self.inflight)>=16 or callback and len(self.callbacks)>=16:
            self.app.set_status('Plugin analysis / action queue full. Retry after pending work finishes.',True);return
        self.serial += 1; serial = self.serial; generation = self.generation
        if callback: self.callbacks[serial] = callback
        if operation == 'process': self.inflight.add(key)
        manual=bool(options.get('plugin'));context=self.context(event)|{'manual':manual}
        context.setdefault('direction','TX' if operation in ('action','rebuild') else 'RX')
        future = self.worker.submit(operation, event.get('data', b''), context, **options)
        target=self.completions
        def done(f):
            try: value, error = f.result(), ''
            except Exception as exc: value, error = [], str(exc)
            target.put_nowait(dict(generation=generation, serial=serial,
                               operation=operation, key=key, value=value, error=error,manual=manual,
                               direction=event.get('direction', 'RX'), peer=event.get('peer', '')))
        future.add_done_callback(done)

    def poll(self):
        if not self.worker:return
        for _ in range(16):
            try:self.complete(self.completions.get_nowait())
            except queue.Empty:break

    def complete(self, event):
        if event['generation'] != self.generation: return
        key = event['key']
        if event['operation'] == 'process': self.inflight.discard(key)
        error = event['error'] or next((r['error'] for r in event['value'] if 'error' in r), '')
        if error and error != self.error:
            self.error = error; self.app.set_status('Plugins: ' + error, True)
        if not event['error'] and event['operation'] == 'process' and key in self.app.events:
            if event['manual']:
                replaced={r['id'] for r in event['value']}
                event['value']=[r for r in self.results.get(key,([],0))[0] if r['id'] not in replaced]+event['value']
            cost = len(json.dumps(event['value']).encode())
            old = self.results.pop(key, ([], 0)); self.bytes -= old[1]
            self.results[key] = (event['value'], cost); self.bytes += cost
            while self.bytes > 2 * 1024 * 1024 or len(self.results) > 128:
                _, (_, size) = self.results.popitem(last=False); self.bytes -= size
            if not event['manual']:self.app.plot.feed_plugins(event)
        callback = self.callbacks.pop(event['serial'], None)
        if callback: callback(event)
        win = getattr(self.app, 'analysis_window', None)
        if win and win.winfo_exists() and win.event_key == key and event['operation'] == 'process':
            if event['error']:win.plugins.note.set(event['error'])
            else:win.plugins.show(event['value'])

    def analyze(self, key, event):
        if self.worker:
            if len(self.inflight)>=16:
                if self.error!='Plugin analysis queue full.':
                    self.error='Plugin analysis queue full.';self.app.set_status(self.error+' Some rows were not analyzed; original traffic is unchanged.',True)
                return
            self.request('process', event, key)

    def open(self):
        old = getattr(self, 'dialog', None)
        if old and old.winfo_exists(): old.lift(); return old
        self.dialog = PluginManager(self); return self.dialog

    def close(self):
        if self.worker: self.worker.close()


class PluginManager(tk.Toplevel):
    def __init__(self, plugins):
        app = plugins.app
        super().__init__(app); self.plugins = plugins; self.entries = json.loads(json.dumps(plugins.entries))
        self.title('Probe · Plugins'); self.geometry('720x480'); self.minsize(660,450)
        self.transient(app.winfo_toplevel()); self.configure(bg=app.colors['panel'])
        body = ttk.Frame(self, padding=16); body.pack(fill='both', expand=True)
        ttk.Label(body, text='Your Python plugins', font=(app.ui_font,18,'bold')).pack(anchor='w')
        ttk.Label(body, text='Results appear in Analyze and Live plot. Python code runs with your user permissions.\nEnable only code you trust. Disconnect before applying changes.', wraplength=660).pack(anchor='w',pady=8)
        self.view = ttk.Treeview(body, columns=('name','flow','changes'), show='headings', selectmode='browse',height=6)
        for key, title, width in (('name','Plugin',320),('flow','Apply to',85),('changes','Change messages',140)):
            self.view.heading(key,text=title); self.view.column(key,width=width)
        self.view.pack(fill='both',expand=True); self.view.bind('<<TreeviewSelect>>',self.select)
        options = ttk.Frame(body); options.pack(fill='x',pady=8)
        self.enabled=tk.BooleanVar(); self.changes=tk.BooleanVar(); self.direction=tk.StringVar(value='Both')
        ttk.Checkbutton(options,text='Enabled',variable=self.enabled,command=self.edit).pack(side='left')
        combo=ttk.Combobox(options,textvariable=self.direction,values=('Both','RX','TX'),state='readonly',width=6)
        combo.pack(side='left',padx=10); combo.bind('<<ComboboxSelected>>',self.edit)
        ttk.Checkbutton(options,text='Allow message changes',variable=self.changes,command=self.edit).pack(side='left')
        ttk.Button(options,text='Settings…',command=self.settings).pack(side='right')
        self.feedback=tk.StringVar(value='Allow message changes enables transforms and automatic simulator replies. Analysis alone is read-only.')
        ttk.Label(body,textvariable=self.feedback,wraplength=660).pack(anchor='w',pady=6)
        bar=ttk.Frame(body); bar.pack(fill='x')
        add=ttk.Menubutton(bar,text='Add…'); add.pack(side='left'); menu=tk.Menu(add,tearoff=False); add.configure(menu=menu)
        menu.add_command(label='Python file…',command=lambda:self.add(False))
        menu.add_command(label='Plugin folder…',command=lambda:self.add(True))
        ttk.Button(bar,text='Remove',command=self.remove).pack(side='left',padx=6)
        ttk.Button(bar,text='Apply',style='Accent.TButton',command=self.apply).pack(side='right')
        ttk.Button(bar,text='Close',command=self.destroy).pack(side='right',padx=6)
        self.refresh()

    def refresh(self):
        self.view.delete(*self.view.get_children())
        for i,e in enumerate(self.entries):
            self.view.insert('', 'end', iid=str(i), values=(('✓ ' if e.get('enabled') else '○ ')+e['name'],e.get('direction','Both'),'Allowed' if e.get('changes') else 'Read-only'))

    def current(self):
        ids=self.view.selection(); return self.entries[int(ids[0])] if ids else None

    def select(self,event=None):
        e=self.current()
        if e:
            self.enabled.set(e.get('enabled',False)); self.changes.set(e.get('changes',False)); self.direction.set(e.get('direction','Both'))
            self.feedback.set(e['path']+' · '+e.get('description','Select Settings for plugin-specific options.'))

    def edit(self,event=None):
        e=self.current()
        if e:
            key=self.view.selection()[0]; e.update(enabled=self.enabled.get(),changes=self.changes.get(),direction=self.direction.get())
            self.view.item(key,values=(('✓ ' if e['enabled'] else '○ ')+e['name'],e['direction'],'Allowed' if e['changes'] else 'Read-only'))

    def add(self,folder=False):
        try:
            if len(self.entries)>=8: raise ValueError('Use at most eight plugins per probe.')
            chosen=filedialog.askdirectory(parent=self) if folder else filedialog.askopenfilename(parent=self,filetypes=[('Python plugin','*.py')])
            if not chosen:return
            source=Path(chosen); main=source/'main.py' if folder else source; info=metadata(main)
            paths=list(islice(source.rglob('*'),257)) if folder else [main]
            if any(p.is_symlink() for p in paths) or len(paths)>256 or sum(p.stat().st_size for p in paths if p.is_file())>8*1024*1024:
                raise ValueError('Plugin folders are limited to 256 entries / 8 MiB and cannot contain symlinks.')
            identifier=uuid4().hex; target=self.plugins.base/'plugins'/identifier; target.mkdir(parents=True)
            if folder: shutil.copytree(source,target,dirs_exist_ok=True,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
            else: shutil.copy2(main,target/'main.py')
            name=info['name'];suffix=2
            while any(e['name']==name for e in self.entries):name=f"{info['name']} ({suffix})";suffix+=1
            self.entries.append(dict(id=identifier,path=f'plugins/{identifier}/main.py',name=name,
                                     description=str(info.get('description',''))[:300],settings=info.get('settings',{}),
                                     enabled=False,changes=False,direction='Both'))
            self.refresh(); self.view.selection_set(str(len(self.entries)-1))
            self.feedback.set('Added. Enable this plugin, choose its direction, then Apply. No code has run yet.')
        except (ValueError,OSError,SyntaxError) as exc:self.feedback.set(str(exc))

    def remove(self):
        if self.current():self.entries.remove(self.current()); self.refresh()

    def settings(self):
        e=self.current()
        if not e:return
        if not e.get('settings'):self.feedback.set('This plugin has no settings.'); return
        win=tk.Toplevel(self); win.title(e['name']+' · Settings'); win.transient(self)
        body=ttk.Frame(win,padding=16); body.pack(fill='both',expand=True); variables={}
        for row,(key,value) in enumerate(e['settings'].items()):
            ttk.Label(body,text=key).grid(row=row,column=0,sticky='w',padx=(0,12),pady=4)
            v=tk.BooleanVar(value=value) if isinstance(value,bool) else tk.StringVar(value=value if isinstance(value,str) else json.dumps(value)); variables[key]=v
            widget=ttk.Checkbutton(body,variable=v) if isinstance(value,bool) else ttk.Entry(body,textvariable=v,width=38)
            widget.grid(row=row,column=1,sticky='ew')
        feedback=tk.StringVar(); ttk.Label(body,textvariable=feedback,wraplength=480).grid(columnspan=2,sticky='w')
        def save():
            try:e['settings']={k:v.get() if isinstance(e['settings'][k],(str,bool)) else json.loads(v.get()) for k,v in variables.items()}
            except ValueError:feedback.set('Use JSON values for numbers, booleans, lists and objects.');return
            win.destroy()
        ttk.Button(body,text='Save',command=save).grid(columnspan=2,pady=10)

    def apply(self):
        try:
            if self.plugins.app.active:raise ValueError('Disconnect this probe before applying plugins.')
            self.plugins.configure(self.entries); self.plugins.app.save_settings()
            self.plugins.app.set_status('Plugins applied. Analyze messages or choose a plugin value in Live plot.')
            self.destroy()
        except (ValueError,OSError,SyntaxError) as exc:self.feedback.set(str(exc))


class PluginPane(ttk.Frame):
    def __init__(self,parent,app):
        super().__init__(parent,padding=10); self.app=app; self.event={}; self.key=None; self.rows=[]; self.output=None
        self.name=tk.StringVar(); self.note=tk.StringVar(value='Add and enable a Python plugin using Plugins… in Traffic.')
        bar=ttk.Frame(self);bar.pack(fill='x')
        self.combo=ttk.Combobox(bar,textvariable=self.name,state='readonly',width=24);self.combo.pack(side='left')
        self.combo.bind('<<ComboboxSelected>>',lambda e:self.render())
        ttk.Button(bar,text='Run analysis',command=self.run).pack(side='left',padx=6)
        ttk.Button(bar,text='Plugins…',command=app.plugins.open).pack(side='right')
        self.view=ttk.Treeview(self,columns=('name','value','bytes'),show='headings',selectmode='browse')
        for key,title,width in (('name','Field',220),('value','Value (double-click to edit)',350),('bytes','Byte range',120)):
            self.view.heading(key,text=title);self.view.column(key,width=width)
        self.view.pack(fill='both',expand=True,pady=8);self.view.bind('<Double-1>',self.edit)
        self.view.bind('<<TreeviewSelect>>',self.field_selected)
        tools=ttk.Frame(self);tools.pack(fill='x')
        self.rebuild_button=ttk.Button(tools,text='Rebuild',state='disabled',command=self.rebuild);self.rebuild_button.pack(side='left')
        self.action_name=tk.StringVar();self.action_combo=ttk.Combobox(tools,textvariable=self.action_name,state='readonly',width=22)
        self.action_combo.pack(side='left',padx=8)
        self.action_button=ttk.Button(tools,text='Run action',state='disabled',command=self.action);self.action_button.pack(side='left')
        ttk.Button(tools,text='Preview changes',command=self.preview).pack(side='left',padx=6)
        ttk.Button(tools,text='Load output into composer',command=self.load).pack(side='right')
        ttk.Label(self,textvariable=self.note,wraplength=840).pack(fill='x',pady=8)

    def set_event(self,event,key):
        self.event=dict(event or {});self.key=key;self.output=None
        names=[e['name'] for e in self.app.plugins.entries if e.get('enabled')]
        self.combo.configure(values=names)
        if self.name.get() not in names:self.name.set(names[0] if names else '')
        self.show(self.app.plugins.results.get(key,([],0))[0])

    def selected_plugin(self):
        return next((e for e in self.app.plugins.entries if e.get('enabled') and e['name']==self.name.get()),None)

    def show(self,rows):self.rows=rows;self.render()

    def render(self):
        self.view.delete(*self.view.get_children());self.output=None;self.fields=[]
        entry=self.selected_plugin()
        if not entry:self.note.set('Use Preview changes to inspect modified bytes, or add and enable a plugin using Plugins….');return
        try:info=metadata(self.app.plugins.base/entry['path'])
        except (ValueError,OSError,SyntaxError) as exc:self.note.set(str(exc));return
        actions=info.get('actions',[])
        self.action_combo.configure(values=actions);self.action_name.set(actions[0] if actions else '')
        self.rebuild_button.configure(state='normal' if 'rebuild' in info['hooks'] else 'disabled')
        self.action_button.configure(state='normal' if 'action' in info['hooks'] and actions else 'disabled')
        row=next((r for r in self.rows if r['id']==entry['id']),None)
        if not row:self.note.set('Press Run analysis. Live results appear here when available.');return
        if row.get('error'):self.note.set(row['error']);return
        r=row['result'];self.fields=[dict(f) for f in r.get('fields',[])]
        for i,f in enumerate(self.fields):
            span=f"{f['offset']} + {f.get('size',0)}" if 'offset' in f else ''
            self.view.insert('','end',iid=str(i),values=(f['name'],str(f['value'])[:1000],span))
        self.output=bytes.fromhex(r['data_hex']) if 'data_hex' in r else None
        note=' · '.join(str(r[k]) for k in ('label','message') if k in r)
        if 'valid' in r:note+=(' · Valid' if r['valid'] else ' · Invalid')
        self.note.set((note or 'Analysis complete.')+f" · {row.get('elapsed_ns',0)/1e6:.2f} ms. Original traffic is unchanged.")

    def run(self):
        entry=self.selected_plugin()
        if entry:self.app.plugins.request('process',self.event,self.key,plugin=entry['id'])

    def field_selected(self,event=None):
        ids=self.view.selection()
        if ids:
            f=self.fields[int(ids[0])]
            if 'offset' in f:
                data=self.event.get('data',b'');start=f['offset'];size=f.get('size',0)
                self.note.set(f'Bytes {start} + {size}: '+data[start:start+min(size,64)].hex(' ').upper())

    def edit(self,event=None):
        ids=self.view.selection();entry=self.selected_plugin()
        if not ids or not entry:return
        f=self.fields[int(ids[0])]
        if self.rebuild_button.instate(['disabled']):self.note.set('This plugin provides read-only fields.');return
        if not f.get('editable',True):self.note.set('This field is read-only.');return
        initial=f['value'] if isinstance(f['value'],str) else json.dumps(f['value'])
        text=simpledialog.askstring('Edit field',f['name'],initialvalue=initial,parent=self)
        if text is None:return
        try:value=text if isinstance(f['value'],str) else json.loads(text)
        except ValueError:self.note.set('Use a JSON number, boolean, list or object for this field.');return
        f['value']=value;self.output=None;self.view.set(ids[0],'value',str(value));self.note.set('Edited locally. Press Rebuild to preview new bytes; nothing has been sent.')

    def invoke(self,operation,**options):
        entry=self.selected_plugin()
        if not entry:return
        token=(self.key,self.name.get())
        def done(event):
            if not self.winfo_exists() or token!=(self.key,self.name.get()):return
            if event['error']:self.note.set(event['error']);return
            if operation=='rebuild':
                for row in event['value']:
                    if not row.get('result',{}).get('fields'):row['result']['fields']=[dict(f) for f in self.fields]
            self.show(event['value'])
            if self.output is not None:
                before=self.event.get('data',b'');after=self.output
                self.note.set(f'Preview: {len(before)} → {len(after)} bytes · '+('unchanged' if before==after else 'changed')+'. Load output into composer to inspect and send it.')
        self.app.plugins.request(operation,self.event,self.key,callback=done,plugin=entry['id'],**options)

    def rebuild(self):self.invoke('rebuild',fields={f['name']:f['value'] for f in self.fields})
    def action(self):self.invoke('action',action=self.action_name.get())

    def load(self):
        if self.output is None:self.note.set('Run a rebuild or action that returns output bytes first.');return
        self.app.load_payload_bytes(self.output);self.note.set('Output loaded. Press Send in the main window to transmit; enabled transforms still apply.')

    def preview(self):
        if self.output is None and 'original_hex' not in self.event:
            self.note.set('Run a rebuild or action that returns output bytes first.');return
        try:before=bytes.fromhex(self.event['original_hex']) if 'original_hex' in self.event else self.event.get('data',b'')
        except ValueError:self.note.set('Original input metadata is not valid hex.');return
        after=self.output if self.output is not None else self.event.get('data',b'')
        win=self.winfo_toplevel();win.comparison.set_data('A',before,'Original input')
        win.comparison.set_data('B',after,'Plugin output');win.tabs.select(win.comparison)
