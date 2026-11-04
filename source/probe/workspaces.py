"""One Tk interpreter, independent connection workspaces."""
from pathlib import Path
import sys
import tkinter as tk
from tkinter import ttk, simpledialog
from . import __version__
from .typography import font_roles


class WorkspaceWindow(tk.Tk):
    MAX_PROBES = 8

    def __init__(self, factory, demo=False):
        super().__init__()
        self.factory, self.probes, self.names, self.states = factory, [], {}, {}
        self._closing = False
        self.title(f"Probe {__version__} · Communications workbench")
        self.geometry(f"{min(1360,max(1060,self.winfo_screenwidth()-80))}x{min(900,max(740,self.winfo_screenheight()-80))}")
        self.minsize(1060,740)
        self.fonts = font_roles(self)
        self.style = ttk.Style(self)
        self.style.theme_use('clam')
        root = Path(getattr(sys,'_MEIPASS',Path(__file__).resolve().parent.parent))
        try:
            self.icon_image=tk.PhotoImage(master=self,file=str(root/'assets'/'probe.png'))
            self.iconphoto(True,self.icon_image)
        except tk.TclError:pass
        bar=ttk.Frame(self,padding=(12,6));bar.pack(fill='x')
        self.add_button=ttk.Button(bar,text='+',width=3,command=self.new_probe)
        self.add_button.pack(side='left')
        ttk.Label(bar,text='Add probe · connections keep running in every tab').pack(side='left',padx=8)
        ttk.Button(bar,text='Close probe',command=self.close_probe).pack(side='right')
        ttk.Button(bar,text='Rename…',command=self.rename_probe).pack(side='right',padx=6)
        self.probe_tabs=ttk.Notebook(self);self.probe_tabs.pack(fill='both',expand=True)
        self.probe_tabs.bind('<<NotebookTabChanged>>',self._selected)
        self.probe_tabs.bind('<Double-1>',lambda e:self.rename_probe())
        self.protocol('WM_DELETE_WINDOW',self.close)
        for key,method,args in (('<Control-Return>','send',()),('<Control-l>','clear',()),
                                ('<Control-s>','export',()),('<F1>','help',()),
                                ('<Control-plus>','zoom',(1,)),('<Control-minus>','zoom',(-1,))):
            self.bind(key,lambda e,m=method,a=args:self._invoke(m,*a))
        for key in ('<MouseWheel>','<Button-4>','<Button-5>'):
            self.bind_all(key,self._wheel,add='+')
        self.new_probe(demo=demo)

    @property
    def current_probe(self):
        selected=self.probe_tabs.select()
        return next((p for p in self.probes if str(p)==selected),None)

    def __getattr__(self, name):
        if self.__dict__.get('probes'):
            probe=self.current_probe
            if probe is not None and hasattr(probe,name):return getattr(probe,name)
        return super().__getattr__(name)

    def _invoke(self,method,*args):
        if self.current_probe:getattr(self.current_probe,method)(*args)
        return 'break'

    def _wheel(self,event):
        if self.current_probe:self.current_probe._config_wheel(event)

    def new_probe(self,demo=False):
        if len(self.probes)>=self.MAX_PROBES:return
        slot=next(i for i in range(1,self.MAX_PROBES+1) if all(p.slot!=i for p in self.probes))
        probe=self.factory(self.probe_tabs,slot=slot,demo=demo)
        self.probes.append(probe);self.names[probe]=f'Probe {slot}'
        self.probe_tabs.add(probe,text=self.names[probe])
        self.probe_tabs.select(probe)
        probe.vars['mode'].trace_add('write',lambda *_:self.update_probe_title(probe))
        self.update_probe_title(probe)
        self.add_button.configure(state='disabled' if len(self.probes)==self.MAX_PROBES else 'normal')
        return probe

    def update_probe_title(self,probe,state=None):
        if probe not in self.probes:return
        if state is not None:self.states[probe]=state
        marker=' ●' if self.states.get(probe)=='Connected' else ''
        self.probe_tabs.tab(probe,text=f'{self.names[probe]} · {probe.vars["mode"].get()}{marker}')

    def _selected(self,event=None):
        probe=self.current_probe
        if probe:
            probe.refresh(force=True)
            probe.plot.dirty=True
            probe.terminal.dirty=True

    def rename_probe(self):
        probe=self.current_probe
        if probe is None:return
        name=simpledialog.askstring('Name this probe','Position in your signal path:',initialvalue=self.names[probe],parent=self)
        if name and name.strip():
            self.names[probe]=name.strip()[:40];self.update_probe_title(probe)

    def close_probe(self,probe=None):
        probe=probe or self.current_probe
        if probe is None or not probe.shutdown():return False
        self.probe_tabs.forget(probe);self.probes.remove(probe)
        self.names.pop(probe,None);self.states.pop(probe,None);probe.destroy()
        for variable in probe.vars.values():
            for modes,command in variable.trace_info():variable.trace_remove(modes,command)
        self.add_button.configure(state='normal')
        if not self.probes and not self._closing:self.new_probe()
        return True

    def close(self):
        self._closing=True
        for probe in self.probes:
            if probe.engine:probe.engine.stop()
        for probe in tuple(self.probes):
            if not self.close_probe(probe):self._closing=False;return
        self.unbind_all('<MouseWheel>');self.unbind_all('<Button-4>');self.unbind_all('<Button-5>')
        self.destroy()
