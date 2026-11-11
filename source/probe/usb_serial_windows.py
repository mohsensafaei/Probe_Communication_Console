'Map a COM device node to its exact USBPcap hub and USB address.'
import ctypes as C
import re
import struct
from contextlib import contextmanager
from uuid import UUID

from .hid_capture import windows_sources
from .usb_serial import SerialTarget, serial_endpoints, validate_port

U = C.c_ulong
P = C.c_void_p
INVALID = P(-1).value
CONNECTION = struct.Struct('<I18sBBBHII')
HUB_GUID = 'f18a0e88-c30c-11d0-8815-00a0c906bed8'


def winfn(library, name, result, *args):
    call = getattr(library, name)
    call.restype, call.argtypes = result, args
    return call


def com_nodes(port):
    from serial.tools import list_ports_windows as setup
    for guid in ('4d36e978-e325-11ce-bfc1-08002be10318', '4d36e96d-e325-11ce-bfc1-08002be10318'):
        kind = setup.GUID.from_buffer_copy(UUID(guid).bytes_le)
        devices = setup.SetupDiGetClassDevs(C.byref(kind), None, None, setup.DIGCF_PRESENT)
        if devices in (None, INVALID):continue
        try:
            item = setup.SP_DEVINFO_DATA();item.cbSize = C.sizeof(item)
            index = 0
            while setup.SetupDiEnumDeviceInfo(devices, index, C.byref(item)):
                index += 1
                key = setup.SetupDiOpenDevRegKey(devices,C.byref(item),setup.DICS_FLAG_GLOBAL,0,setup.DIREG_DEV,setup.KEY_READ)
                if key in (None, INVALID):continue
                try:
                    name = C.create_unicode_buffer(32);size = U(C.sizeof(name))
                    if setup.RegQueryValueEx(key,'PortName',None,None,C.byref(name),C.byref(size)) == 0 and name.value.upper()==port:
                        yield item.DevInst
                finally:setup.RegCloseKey(key)
        finally:setup.SetupDiDestroyDeviceInfoList(devices)


class UsbApi:
    def __init__(self):
        from serial.tools.list_ports_windows import GUID
        cfg = C.WinDLL('cfgmgr32', use_last_error=True)
        kernel = C.WinDLL('kernel32', use_last_error=True)
        self.parent = winfn(cfg,'CM_Get_Parent',U,C.POINTER(U),U,U)
        self.instance = winfn(cfg,'CM_Get_Device_IDW',U,U,C.c_wchar_p,U,U)
        self.prop = winfn(cfg,'CM_Get_DevNode_Registry_PropertyW',U,U,U,P,P,C.POINTER(U),U)
        self.hubs = winfn(cfg,'CM_Get_Device_Interface_ListW',U,C.POINTER(GUID),C.c_wchar_p,C.c_wchar_p,U,U)
        self.hub_guid = GUID.from_buffer_copy(UUID(HUB_GUID).bytes_le)
        self.open = winfn(kernel,'CreateFileW',P,C.c_wchar_p,U,U,P,U,U,P)
        self.control = winfn(kernel,'DeviceIoControl',C.c_int,P,U,P,U,P,U,C.POINTER(U),P)
        self.close = winfn(kernel,'CloseHandle',C.c_int,P)

    def chain(self, node):
        for _ in range(32):
            value = C.create_unicode_buffer(1024)
            if self.instance(node,value,len(value),0):break
            yield node, value.value.upper()
            parent = U()
            if self.parent(C.byref(parent),node,0):break
            node = parent.value

    def property(self,node,key):
        value = C.create_unicode_buffer(1024);size = U(C.sizeof(value))
        return value.value if not self.prop(node,key,None,value,C.byref(size),0) else ''

    def hub(self, identity):
        value = C.create_unicode_buffer(8192)
        if self.hubs(C.byref(self.hub_guid),identity,value,len(value),0) or not value.value:
            raise OSError('USB hub interface is unavailable.')
        return value.value

    @contextmanager
    def handle(self, path, access=0, share=0):
        handle = self.open(path,access,share,None,3,0,None)
        if handle in (None, INVALID):raise C.WinError(C.get_last_error())
        try:yield handle
        finally:self.close(handle)

    def ioctl(self, handle, code, request=b'', size=4096):
        buffer = C.create_string_buffer(request, size);written = U()
        if not self.control(handle,code,buffer if request else None,size if request else 0,buffer,size,C.byref(written),None):
            raise C.WinError(C.get_last_error())
        return buffer.raw[:written.value]

    def driver_key(self, handle, index):
        try:raw = self.ioctl(handle,0x220420,struct.pack('<I',index))
        except OSError:return ''
        if len(raw) < 10:return ''
        return raw[8:].decode('utf-16-le',errors='replace').split('\0',1)[0].casefold()


def hub_instance(path):
    return '\\'.join(path.strip('\\?.').split('#')[:3]).upper()


def connected(api, handle, index):
    data = api.ioctl(handle,0x220448,struct.pack('<I',index))
    if len(data) < CONNECTION.size:raise OSError('USB hub returned a short connection record.')
    _, descriptor, configuration, _, is_hub, address, _, status = CONNECTION.unpack_from(data)
    if status != 1 or is_hub or not configuration or not 1<=address<=127:
        raise OSError('USB serial device is not connected and configured.')
    return descriptor, configuration, address


def windows_target(port):
    validate_port(port, True)
    nodes = set(com_nodes(port))
    if len(nodes) != 1:raise OSError('COM port is missing or ambiguous. Refresh ports.')
    api = UsbApi()
    chain = list(api.chain(nodes.pop()))
    root = next((identity for _,identity in chain if identity.startswith('USB\\ROOT_HUB')),None)
    for i,(node,identity) in enumerate(chain[:-1]):
        match = re.fullmatch(r'USB\\VID_([0-9A-F]{4})&PID_([0-9A-F]{4})[^\\]*\\[^\\]+',identity)
        if match and '&MI_' not in identity.split('\\')[1]:break
    else:raise ValueError('This COM port is not backed by a USB device.')
    if not root:raise ValueError('No USB root hub for this COM port.')
    services = {api.property(dev,5).casefold() for dev,_ in chain[:i+1]}
    ids = tuple(int(v,16) for v in match.groups())
    profile = 'CDC ACM' if 'usbser' in services else 'FTDI' if ids == (0x0403,0x6001) and 'ftdibus' in services else None
    if not profile:raise ValueError('Only CDC ACM (usbser) and standard single-port FTDI are supported.')
    interfaces = {int(m[1],16) for _,dev in chain[:i] if (m:=re.search(r'&MI_([0-9A-F]{2})\\',dev))}
    if len(interfaces)>1:raise ValueError('COM port maps to multiple USB interfaces.')
    hub = api.hub(chain[i+1][1]);driver = api.property(node,10).casefold()
    if not driver:raise OSError('The USB device has no driver identity.')
    with api.handle(hub,0x40000000,3) as handle:
        info = api.ioctl(handle,0x220408,b'\0'*4)
        if len(info)<7:raise OSError('USB hub did not report its ports.')
        indices = [p for p in range(1,info[6]+1) if api.driver_key(handle,p)==driver]
        if len(indices)!=1:raise OSError('USB hub port could not be identified unambiguously.')
        index = indices[0]
        original = connected(api,handle,index)
        desc, configuration, address = original
        if struct.unpack_from('<HH',desc,8)!=ids:raise OSError('COM port USB device changed during discovery.')
        for config_index in range(min(desc[17],8)):
            prefix = struct.pack('<IBBHH',index,0x80,6,0x0200|config_index,0)
            head = api.ioctl(handle,0x220410,prefix+b'\x09\x00',21)[12:]
            if len(head)==9 and head[5]==configuration:
                length = int.from_bytes(head[2:4],'little')
                if length < 9:raise ValueError('Invalid USB configuration length.')
                descriptor = api.ioctl(handle,0x220410,prefix+head[2:4],12+length)[12:]
                break
        else:raise OSError('Could not read the active USB configuration.')
    endpoints = serial_endpoints(descriptor,configuration,next(iter(interfaces),None),profile)
    sources = []
    for source in windows_sources():
        try:
            with api.handle(source) as handle:
                link = api.ioctl(handle,0x22200c).decode('utf-16-le',errors='replace').split('\0',1)[0]
            if hub_instance(link)==root:sources.append(source)
        except OSError:continue
    if len(sources)!=1:raise OSError('Cannot match the USB root hub to exactly one USBPcap interface.')

    def attached():
        with api.handle(hub,0x40000000,3) as handle:
            return api.driver_key(handle,index)==driver and connected(api,handle,index)==original
    return SerialTarget(f'{sources[0]}:{address}',profile,endpoints,attached)
