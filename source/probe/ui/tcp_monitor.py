from pathlib import Path
from tkinter import filedialog, ttk


def build_panel(app, field):
    app.tcp_devices = getattr(app, 'tcp_devices', {})
    app.tcp_combo = field('Capture interface', 'tcp_device', list(app.tcp_devices), True)
    field('TCP port (required)', 'tcp_port')
    parent = app.config_frame

    def refresh():
        try:
            from ..pcap_live import interfaces
            app.tcp_devices = dict(interfaces())
            app.tcp_combo.configure(values=list(app.tcp_devices))
            if app.vars['tcp_device'].get() not in app.tcp_devices:
                app.vars['tcp_device'].set(next((name for name in app.tcp_devices if name.startswith('Loopback')), ''))
            app.set_status('Choose an interface and port, then Start capture.' if app.tcp_devices else 'No capture interface found.', not app.tcp_devices)
        except OSError as exc:app.set_status(str(exc),True)

    def open_file():
        path = filedialog.askopenfilename(parent=app, filetypes=[('TCP packet capture','*.pcap *.pcapng')])
        if path:app.import_capture(path)

    def raw_path():
        if getattr(app,'tcp_pcap',None):
            app.tcp_pcap=None;app.tcp_save.configure(text='Save raw PCAP…');return
        path = filedialog.asksaveasfilename(parent=app, defaultextension='.pcap', filetypes=[('PCAP','*.pcap')])
        if not path:return
        if Path(path).exists():app.set_status('Choose a new PCAP file name; existing files are preserved.',True);return
        app.tcp_pcap=path;app.tcp_save.configure(text='Clear PCAP path')
        app.set_status('Raw packet recording armed for the next capture.')

    for label, callback in (('Refresh interfaces', refresh), ('Open Capture…', open_file),
                            ('Clear PCAP path' if getattr(app,'tcp_pcap',None) else 'Save raw PCAP…', raw_path)):
        button = ttk.Button(parent,text=label,command=callback)
        button.pack(fill='x',pady=(5,0));app.config_controls.append(button)
        if callback is raw_path:app.tcp_save=button
    app.label(parent,'Read-only. TX goes toward the selected port. Open Capture needs no driver.',9,
              color=app.colors['muted'],wraplength=218,justify='left').pack(anchor='w',pady=7)
