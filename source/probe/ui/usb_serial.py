import os
from tkinter import ttk

from ..usb_serial import validate_port


def build_panel(app, field):
    app.usb_serial_ports=getattr(app,'usb_serial_ports',{})
    app.usb_serial_combo=field('USB serial port','usb_serial_device',list(app.usb_serial_ports),True)

    def refresh():
        from serial.tools import list_ports
        try:
            ports={}
            for item in list_ports.comports():
                if item.vid is None:continue
                try:port=validate_port(item.device)
                except ValueError:continue
                ports[f'{port} · {item.description}']=port
            app.usb_serial_ports=ports;app.usb_serial_combo.configure(values=list(ports))
            if app.vars['usb_serial_device'].get() not in ports:app.vars['usb_serial_device'].set('')
            app.set_status('Choose the USB serial port used by your app.' if ports else 'No USB serial ports found.',not ports)
        except (OSError,ValueError) as exc:app.set_status(str(exc),True)

    parent=app.config_frame
    button=ttk.Button(parent,text='Refresh ports',command=refresh)
    button.pack(fill='x',pady=(5,0));app.config_controls.append(button)
    if os.name=='nt':
        from .hid import install_driver
        button=ttk.Button(parent,text='Install USBPcap (offline)…',command=lambda:install_driver(app))
        button.pack(fill='x',pady=(5,0));app.config_controls.append(button)
    app.label(parent,'Read-only. Leave your app connected. Supports CDC ACM and standard single-port FTDI.',9,
              color=app.colors['muted'],wraplength=218,justify='left').pack(anchor='w',pady=7)
