'Resolve a single USB serial interface and decode its completed bulk transfers.'
import os
import re
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SerialTarget:
    source: str
    profile: str
    endpoints: dict
    attached: object


def validate_port(port, windows=None):
    windows = os.name == 'nt' if windows is None else windows
    pattern = r'COM[1-9]\d{0,4}' if windows else r'/dev/tty(?:ACM|USB)\d{1,5}'
    if not re.fullmatch(pattern, port):
        raise ValueError('Select a USB COM or tty port from Refresh ports.')
    return port


def serial_endpoints(data, configuration, interface, profile, alternates=None):
    active, current, pos = False, None, 0
    interfaces, links = {}, {}
    while pos + 2 <= len(data):
        size, kind = data[pos:pos+2]
        if size < 2 or pos + size > len(data):raise ValueError('Invalid USB configuration descriptor.')
        desc = data[pos:pos+size]; pos += size
        if kind == 2 and size >= 9:
            total = int.from_bytes(desc[2:4], 'little')
            if total < size or pos - size + total > len(data):raise ValueError('Truncated USB configuration descriptor.')
            active, current = desc[5] == configuration, None
        elif not active:
            continue
        elif kind == 4 and size >= 9:
            number, alternate = desc[2:4]
            current = (number, alternate) if alternates is None or alternates.get(number) == alternate else None
            if current is not None:interfaces[current] = desc[5], desc[6], {}
        elif kind == 0x24 and size >= 5 and current is not None and interfaces[current][:2] == (2, 2):
            if desc[2] == 6 and desc[3] == current[0]:links.setdefault(current[0], set()).update(desc[4:])
        elif kind == 5 and size >= 7 and current is not None and desc[3] & 3 == 2:
            packet_size = int.from_bytes(desc[4:6], 'little') & 0x7ff
            if 8 <= packet_size <= 1024 and desc[2] & 15 and not desc[2] & 0x70:
                interfaces[current][2][desc[2]] = packet_size

    if profile == 'CDC ACM':
        controls = {i for (i,_), (cls,sub,_) in interfaces.items() if (cls,sub) == (2,2)}
        data_interfaces = {i for (i,_), (cls,_,_) in interfaces.items() if cls == 10}
        candidates = set()
        for control in controls:
            related = links.get(control) or (data_interfaces if len(controls)==len(data_interfaces)==1 else set())
            if interface is None or interface == control or interface in related:
                candidates.update({control, *related})
        classes = (2, 10)
    elif profile == 'FTDI':
        candidates = {i for i,_ in interfaces if interface is None or i == interface}
        classes = (255,)
    else:
        raise ValueError('Unsupported USB serial driver.')
    pairs = {tuple(sorted(endpoints.items())) for (number,_), (cls,_,endpoints) in interfaces.items()
             if number in candidates and cls in classes and len(endpoints) == 2
             and sum(bool(ep & 128) for ep in endpoints) == 1}
    if len(pairs) != 1:
        raise ValueError('No unambiguous bulk endpoint pair for this USB serial port.')
    return dict(pairs.pop())


def linux_target(port, root=Path('/sys/class/tty')):
    validate_port(port, False)
    link = root / Path(port).name / 'device'
    try:
        chain = link.resolve(strict=True)
        interface = next(p for p in (chain, *chain.parents) if (p/'bInterfaceNumber').is_file())
        physical = interface.parent
        number = int((interface/'bInterfaceNumber').read_text(), 16)
        driver = (interface/'driver').resolve(strict=True).name
        ids = ((physical/'idVendor').read_text().strip(), (physical/'idProduct').read_text().strip())
        profile = 'CDC ACM' if driver == 'cdc_acm' else 'FTDI' if driver == 'ftdi_sio' and ids == ('0403','6001') else None
        if profile is None:raise ValueError('Only CDC ACM and standard single-port FTDI are supported.')
        def identity():
            return (interface.stat().st_ino, int((physical/'busnum').read_text()),
                    int((physical/'devnum').read_text()), int((physical/'bConfigurationValue').read_text()))
        original = identity()
        _, bus, device, configuration = original
        alternates = {int((p/'bInterfaceNumber').read_text(),16):int((p/'bAlternateSetting').read_text(),16)
                      for p in physical.iterdir() if (p/'bAlternateSetting').is_file()}
        endpoints = serial_endpoints((physical/'descriptors').read_bytes(), configuration, number, profile, alternates)
        return SerialTarget(f'{bus}:{device}', profile, endpoints, lambda: link.resolve(strict=True)==chain and identity()==original)
    except (OSError, StopIteration) as exc:
        raise OSError('USB serial port disappeared or has no supported USB interface.') from exc


class SerialTransfers:
    def __init__(self, profile, endpoints, windows):
        self.profile, self.endpoints, self.windows = profile, endpoints, windows
        self.pending = OrderedDict()
        self.pending_bytes = 0

    @staticmethod
    def payload(packet):
        data = packet['payload']
        if len(data) != packet['length']:
            raise OSError('USB serial transfer data was truncated; capture stopped at the gap.')
        return data

    def consume(self, packet):
        endpoint, stage, identity = packet['endpoint'], packet['stage'], packet['id']
        if packet['transfer'] != 'bulk' or endpoint not in self.endpoints:return None
        incoming = bool(endpoint & 128)
        if incoming:
            if stage != 'complete':return None
            if packet['status']:
                if packet['length']:raise OSError('USB serial read failed with data; capture stopped at the gap.')
                return None
            data = self.payload(packet)
            if self.profile == 'FTDI':
                size = self.endpoints[endpoint]
                if len(data) % size == 1:raise OSError('Truncated FTDI status header.')
                data = b''.join(data[i+2:i+size] for i in range(0,len(data),size))
        elif stage == 'submit':
            data = self.payload(packet)
            if data:
                key = identity, endpoint
                self.pending_bytes += len(data) - len(self.pending.get(key,b''))
                if self.pending_bytes > 4*1024*1024 or len(self.pending)>=128 and key not in self.pending:
                    raise OSError('Too many pending USB serial writes; capture stopped before data could be lost.')
                self.pending[key] = data
            return None
        else:
            data = self.pending.pop((identity,endpoint), b'')
            self.pending_bytes -= len(data)
            if not data:return None
            if stage != 'complete' or packet['status']:
                raise OSError('USB serial write failed; capture stopped at the gap.')
            if not self.windows:
                if packet['length'] > len(data):raise OSError('USB write completion exceeds its captured submission.')
                data = data[:packet['length']]
        return ('RX' if incoming else 'TX', data) if data else None
