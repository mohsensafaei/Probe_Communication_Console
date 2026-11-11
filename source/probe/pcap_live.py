'Read-only bindings to system libpcap or the separately installed Npcap driver.'
import ctypes as C
import ctypes.util
import os
from functools import lru_cache
from pathlib import Path

from .pcap import Packet
from .tcp_stream import LINKS

SNAPLEN = 262144
P = C.c_void_p
S = C.c_char_p
I = C.c_int
U = C.c_uint


class Interface(C.Structure):
    pass


InterfacePtr = C.POINTER(Interface)
Interface._fields_ = [('next', InterfacePtr), ('name', S), ('description', S), ('addresses', P), ('flags', U)]


class Header(C.Structure):
    _fields_ = [('sec', C.c_long), ('usec', C.c_long), ('captured', U), ('length', U)]


class Filter(C.Structure):
    _fields_ = [('length', U), ('instructions', P)]


@lru_cache(maxsize=1)
def library():
    try:
        if os.name == 'nt':
            system = C.create_unicode_buffer(32768)
            if not 0 < C.windll.kernel32.GetSystemDirectoryW(system, len(system)) < len(system):
                raise OSError('Windows system directory unavailable.')
            lib = C.CDLL(str(Path(system.value) / 'Npcap' / 'wpcap.dll'), winmode=0x900)
        else:
            lib = C.CDLL(ctypes.util.find_library('pcap') or 'libpcap.so.0.8')
        signatures = {
            'findalldevs': (I, C.POINTER(InterfacePtr), S), 'freealldevs': (None, InterfacePtr),
            'open_live': (P, S, I, I, I, S), 'close': (None, P), 'geterr': (S, P),
            'datalink': (I, P), 'setnonblock': (I, P, I, S),
            'compile': (I, P, C.POINTER(Filter), S, I, U), 'setfilter': (I, P, C.POINTER(Filter)),
            'freecode': (None, C.POINTER(Filter)), 'next_ex': (I, P, C.POINTER(C.POINTER(Header)), C.POINTER(P)),
            'stats': (I, P, C.POINTER(U)),
        }
        for name, (result, *args) in signatures.items():
            call = getattr(lib, 'pcap_' + name)
            call.restype, call.argtypes = result, args
        return lib
    except (OSError, AttributeError) as exc:
        dependency = 'Npcap' if os.name == 'nt' else 'libpcap'
        raise OSError(f'Live capture needs {dependency}. Install it separately; Open Capture works without it.') from exc


def interfaces():
    lib = library()
    first = InterfacePtr(); error = C.create_string_buffer(256)
    if lib.pcap_findalldevs(C.byref(first), error) != 0:
        raise OSError(error.value.decode(errors='replace'))
    result = []
    try:
        current = first
        while current and len(result) < 256:
            node = current.contents
            if node.name:
                name = os.fsdecode(node.name)
                label = 'Loopback' if node.flags & 1 else (node.description or node.name).decode(errors='replace')
                result.append((f'{label} ({name})' if label != name else name, name))
            current = node.next
        return result
    finally:
        if first:lib.pcap_freealldevs(first)


class LiveCapture:
    def __init__(self, device, port):
        if not 1 <= port <= 65535:
            raise ValueError('Capture TCP port must be 1–65535.')
        self.lib = lib = library()
        error = C.create_string_buffer(256)
        self.handle = lib.pcap_open_live(os.fsencode(device), SNAPLEN, 0, 25, error)
        if not self.handle:
            raise OSError((error.value.decode(errors='replace') or 'Capture interface unavailable.') +
                          ' Check Npcap/libpcap capture permissions.')
        try:
            self.link = lib.pcap_datalink(self.handle)
            if self.link == 12 and os.name != 'nt':self.link = 101  # DLT_RAW → LINKTYPE_RAW
            if self.link not in LINKS:
                raise OSError('This capture interface does not expose a supported IP link type.')
            rule = Filter()
            if lib.pcap_compile(self.handle, C.byref(rule), f'tcp port {port}'.encode(), 1, 0xffffffff) != 0:
                raise OSError(self.error())
            try:
                if lib.pcap_setfilter(self.handle, C.byref(rule)) != 0:
                    raise OSError(self.error())
            finally:lib.pcap_freecode(C.byref(rule))
            if lib.pcap_setnonblock(self.handle, 1, error) != 0:
                raise OSError(error.value.decode(errors='replace') or self.error())
            self.header = C.POINTER(Header)()
            self.data = P()
        except BaseException:
            self.close()
            raise

    def error(self):
        return (self.lib.pcap_geterr(self.handle) or b'Packet capture failed.').decode(errors='replace')

    def read(self):
        status = self.lib.pcap_next_ex(self.handle, C.byref(self.header), C.byref(self.data))
        if status == 0:return None
        if status != 1:raise OSError(self.error())
        h = self.header.contents
        if h.captured > min(h.length, SNAPLEN):raise OSError('Invalid packet length from capture driver.')
        return Packet(h.sec + h.usec / 1e6, self.link, C.string_at(self.data, h.captured), wire_size=h.length)

    def drops(self):
        counts = (U * 16)()
        if self.lib.pcap_stats(self.handle, counts) == 0:
            return counts[1], counts[2]
        return None

    def close(self):
        self.lib.pcap_close(self.handle)
