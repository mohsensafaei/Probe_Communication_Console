import os

from .hid_helper import HelperClient
from .usb_serial import SerialTransfers, linux_target


def run_monitor(engine):
    port = engine.cfg['usb_serial_port']
    windows = os.name == 'nt'
    elevate = windows or not os.access('/dev/usbmon'+linux_target(port).source.split(':')[0],os.R_OK)
    engine.event('info',message='Waiting for USB serial capture permission…' if elevate else 'Opening USB serial capture…')
    client = HelperClient(); tracker = None
    try:
        for message in client.messages('serial',port,engine.stopping,elevate=elevate):
            kind = message['kind']
            if kind == 'serial_metadata':
                tracker = SerialTransfers(message['profile'],{int(ep):size for ep,size in message['endpoints'].items()},windows)
            elif kind == 'ready' and tracker:
                engine._connected(f'{port} · {tracker.profile} · USB serial capture · read-only')
            elif kind == 'warning':
                raise OSError(message['message']+' Capture stopped at the gap.')
            elif kind == 'packet' and tracker:
                packet=message['packet'];packet['payload']=bytes.fromhex(packet['payload'])
                event=tracker.consume(packet)
                if event:
                    direction,data=event
                    engine.event('data',time=packet['time'],direction=direction,peer=port,data=data,usb_serial=True,
                                 usb_endpoint=packet['endpoint'],usb_profile=tracker.profile)
    finally:client.close()
