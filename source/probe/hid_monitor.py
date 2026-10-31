"""Read-only HID monitoring integrated with Probe's existing event/capture path."""
import contextlib
import ctypes
import os
import re
from .hid_capture import validate_source
from .hid_helper import HelperClient
from .hid_reports import HidTracker


def windows_report_descriptors(vid,pid):
    """Query descriptor metadata only. Never read input or write HID reports.

Windows reconstructs these descriptors from preparsed data. If identical devices
cannot be distinguished, keep raw bytes rather than choosing a different device.
"""
    import hid
    candidates=[d for d in hid.enumerate(vid,pid) if d.get('bus_type',1)==1]
    roots=set();cfg=ctypes.WinDLL('cfgmgr32');ulong=ctypes.c_ulong
    cfg.CM_Locate_DevNodeW.argtypes=[ctypes.POINTER(ulong),ctypes.c_wchar_p,ulong]
    cfg.CM_Get_Parent.argtypes=[ctypes.POINTER(ulong),ulong,ulong]
    cfg.CM_Get_Device_IDW.argtypes=[ulong,ctypes.c_wchar_p,ulong,ulong]
    def physical_id(path):
        text=path.decode('utf-8',errors='replace')
        parts=text.removeprefix('\\\\?\\').split('#')
        if len(parts)<3:return None
        node=ulong()
        if cfg.CM_Locate_DevNodeW(ctypes.byref(node),'\\'.join(parts[:3]),0):return None
        for _ in range(32):
            value=ctypes.create_unicode_buffer(1024)
            if cfg.CM_Get_Device_IDW(node,value,len(value),0):return None
            if value.value.upper().startswith('USB\\VID_'):return value.value.upper()
            parent=ulong()
            if cfg.CM_Get_Parent(ctypes.byref(parent),node,0):return None
            node=parent
        return None
    for candidate in candidates:
        root=physical_id(candidate['path'])
        if root is None:return {}
        roots.add(root)
    if len(roots)!=1:return {}
    result={};ambiguous=set()
    for candidate in candidates:
        interface=candidate.get('interface_number',-1)
        if interface<0:continue
        try:
            device=hid.device()
            try:device.open_path(candidate['path']);descriptor=bytes(device.get_report_descriptor())
            finally:device.close()
            if not descriptor:continue
            if interface in result and result[interface]!=descriptor.hex():ambiguous.add(interface)
            else:result[interface]=descriptor.hex()
        except (OSError,ValueError):continue
    return {i:d for i,d in result.items() if i not in ambiguous}


def run_monitor(engine):
    source=engine.cfg['hid_source'];bus,device=validate_source(source)
    # Existing Linux usbmon permissions are honored; only elevate if necessary.
    elevate=os.name=='nt' or not os.access(f'/dev/usbmon{bus}',os.R_OK)
    tracker=HidTracker();queried=False;client=HelperClient()
    engine.event('info',message='Waiting for HID capture permission… Probe itself stays unelevated.' if elevate else 'Opening HID capture…')
    try:
        for message in client.messages('capture',source,engine.stopping,elevate=elevate):
            kind=message.get('kind')
            if kind=='metadata':tracker=HidTracker(message.get('interfaces'),message.get('descriptors'))
            elif kind=='ready':engine._connected('HID capture active · RX: device → computer · TX: computer → device · read-only')
            elif kind=='warning':engine.event('info',message=message['message'])
            elif kind=='packet':
                packet=message['packet'];packet['payload']=bytes.fromhex(packet['payload'])
                event=tracker.consume(packet)
                if os.name=='nt' and tracker.vid is not None and not queried:
                    queried=True
                    try:
                        for interface,descriptor in windows_report_descriptors(tracker.vid,tracker.pid).items():tracker.set_descriptor(interface,bytes.fromhex(descriptor))
                    except (OSError,ValueError,ImportError):pass
                if event:
                    fields={key:value for key,value in event.items() if key!='kind'}
                    engine.event('data',**fields)
    finally:client.close()
