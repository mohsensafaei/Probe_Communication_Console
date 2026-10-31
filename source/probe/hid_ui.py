"""HID device selection and report inspection; all capture work is off Tk."""
import os
from pathlib import Path
import threading
import tkinter as tk
from tkinter import ttk,filedialog,messagebox
from .hid_capture import bundled_installer,usbpcap_command
from .hid_helper import discover_devices,launch_helper
from .hid_reports import MAX_DESCRIPTOR,ReportDescriptor


def build_panel(app,field):
    app.hid_devices={}
    app.hid_combo=field('USB device','hid_device',[],True)
    app.hid_combo.set('Refresh devices to choose…')
    row=app.frame(app.config_frame);row.pack(fill='x',pady=6)
    refresh=ttk.Button(row,text='Refresh devices',command=lambda:refresh_devices(app))
    refresh.pack(fill='x');app.config_controls.append(refresh)
    if os.name=='nt':
        button=ttk.Button(row,text='Install USBPcap (offline)…',command=lambda:install_driver(app))
        button.pack(fill='x',pady=(5,0));app.config_controls.append(button)
    app.label(app.config_frame,'Capture only — no commands are sent.\nRX: device → computer\nTX: computer → device',9,
              color=app.colors['muted'],wraplength=210,justify='left').pack(anchor='w',pady=6)
    hint=('Administrator permission is requested only for HID capture or driver setup. Installation may require a Windows restart.' if os.name=='nt' else
          'Uses the kernel’s usbmon. Capture requests permission only if your account needs it. No download or permanent permission change.')
    app.label(app.config_frame,hint,9,color=app.colors['muted'],wraplength=210,justify='left').pack(anchor='w',pady=6)
    app.label(app.config_frame,'Reports appear in Traffic. Double-click one for HID fields and exact bytes. USB HID only; Bluetooth/I²C HID are not captured.',9,
              color=app.colors['muted'],wraplength=210,justify='left').pack(anchor='w',pady=6)


def refresh_devices(app):
    if getattr(app,'hid_refreshing',False):return
    app.hid_refreshing=True;app.set_status('Finding USB devices…')
    stop=threading.Event();app.hid_discovery_stop=stop
    def work():
        try:app.emit(dict(kind='hid_devices',devices=discover_devices(allow_elevation=True,stop=stop)))
        except (OSError,ValueError) as exc:app.emit(dict(kind='hid_devices',error=str(exc)))
    threading.Thread(target=work,name='Probe HID discovery',daemon=True).start()


def devices_received(app,event):
    app.hid_refreshing=False
    if event.get('error'):app.set_status(event['error'],True);return
    if app.vars['mode'].get()!='HID Monitor' or app.active:return
    previous=app.vars['hid_device'].get();app.hid_devices={}
    for device in event['devices']:
        label=f"{device['name']} [{device['source']}]"
        app.hid_devices[label]=device['source']
    app.hid_combo.configure(values=list(app.hid_devices))
    app.vars['hid_device'].set(previous if previous in app.hid_devices else next(iter(app.hid_devices),'No USB HID devices found'))
    app.set_status(f"{len(app.hid_devices)} USB devices available. Choose a device, then Start capture. Only its HID interfaces are displayed." if app.hid_devices else 'No USB HID devices found. Connect a USB device and Refresh devices.')


def install_driver(app):
    if os.name!='nt':return
    if usbpcap_command():messagebox.showinfo('USBPcap','USBPcap is already installed. If devices are missing, restart Windows and Refresh devices.',parent=app);return
    try:
        path=bundled_installer()
        # The original signed installer presents its own license/setup pages.
        # No silent install, online bootstrap, or automatic restart.
        process=launch_helper([str(path)],True)
        if hasattr(process,'close'):process.close()
        app.set_status('USBPcap setup opened from the bundled installer. After installation, restart Windows, then Refresh devices.')
    except OSError as exc:app.set_status(str(exc),True)


class HidReportPane(ttk.Frame):
    def __init__(self,parent,app):
        super().__init__(parent,padding=12);self.app=app;self.data=b'';self.metadata={}
        self.caption=tk.StringVar();self.note=tk.StringVar();self.descriptor=b''
        ttk.Label(self,text='HID report',font=(app.ui_font,16,'bold')).pack(anchor='w')
        ttk.Label(self,textvariable=self.caption,wraplength=850).pack(anchor='w',pady=5)
        bar=ttk.Frame(self);bar.pack(fill='x',pady=4)
        ttk.Button(bar,text='Load report descriptor…',command=self.load_descriptor).pack(side='left')
        ttk.Button(bar,text='Save report descriptor…',command=self.save_descriptor).pack(side='left',padx=6)
        ttk.Label(self,textvariable=self.note,wraplength=850).pack(side='bottom',anchor='w',pady=6)
        box=ttk.Frame(self);box.pack(fill='both',expand=True)
        self.view=ttk.Treeview(box,columns=('field','value','bits','mode'),show='headings',selectmode='browse')
        for key,label,width in [('field','Field',260),('value','Value',300),('bits','Bit range',100),('mode','Meaning',110)]:
            self.view.heading(key,text=label);self.view.column(key,width=width,minwidth=70)
        self.view.pack(side='left',fill='both',expand=True)
        scroll=ttk.Scrollbar(box,command=self.view.yview);scroll.pack(side='right',fill='y');self.view.configure(yscrollcommand=scroll.set)

    def set_event(self,event):
        self.data=event['data'];self.metadata=dict(event.get('hid',{}))
        self.descriptor=bytes.fromhex(self.metadata.get('descriptor',''))
        m=self.metadata;self.caption.set(f"{m.get('report_type','Report')} · interface {m.get('interface','?')} · endpoint 0x{m.get('endpoint',0):02X} · {len(self.data)} bytes")
        self.render(m.get('fields',[]),m.get('note','No descriptor available.'))

    def render(self,fields,note):
        self.view.delete(*self.view.get_children())
        for i,field in enumerate(fields):
            self.view.insert('','end',iid=str(i),values=(field['field'],field['value'],f"{field['bit']}–{field['bit']+field['bits']-1}",'Relative' if field.get('relative') else 'Absolute / state'))
        if self.metadata.get('truncated'):note='USB capture was truncated. '+note
        self.note.set(note+' Original report bytes are available in Hex + ASCII and Every Byte.')

    def load_descriptor(self):
        path=filedialog.askopenfilename(parent=self,filetypes=[('HID report descriptor','*.bin *.hex'),('All files','*')])
        if not path:return
        try:
            file=Path(path)
            if file.stat().st_size>MAX_DESCRIPTOR*3:raise ValueError('Choose a descriptor of at most 16 KiB.')
            data=bytes.fromhex(file.read_text()) if file.suffix.lower()=='.hex' else file.read_bytes()
            descriptor=ReportDescriptor(data);fields,note=descriptor.decode(self.data,self.metadata.get('report_type','Input'))
            self.descriptor=data;self.render(fields,note+' Loaded for this inspection only.')
        except (OSError,ValueError) as exc:self.note.set(str(exc))

    def save_descriptor(self):
        if not self.descriptor:self.note.set('No descriptor available. Load one first.');return
        path=filedialog.asksaveasfilename(parent=self,defaultextension='.bin',filetypes=[('HID report descriptor','*.bin')])
        if path:
            try:Path(path).write_bytes(self.descriptor);self.note.set('Saved report descriptor. Captured report bytes were unchanged.')
            except OSError as exc:self.note.set(str(exc))
