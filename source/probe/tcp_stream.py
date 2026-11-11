'Reassemble observed TCP bytes without filling missing data.'
import ipaddress
import struct
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path

from .pcap import packets
from .evidence.identity import namespace
from .traffic_model import DisplayFraming, retained_size

LINKS = {0, 1, 101, 108, 113, 228, 229, 276}
SYN, FIN, RST, ACK = 2, 1, 4, 16
MOD = 1 << 32


@dataclass(frozen=True, slots=True)
class Segment:
    source: tuple
    destination: tuple
    seq: int
    flags: int
    data: bytes
    length: int


def decode(packet):
    data, link = packet.data, packet.link
    if link not in LINKS:
        raise ValueError('Unsupported capture link type.')
    ip = {0: 4, 1: 14, 101: 0, 108: 4, 113: 16, 228: 0, 229: 0, 276: 20}[link]
    if len(data) <= ip:
        raise ValueError('Truncated link header.')
    if link in (1, 113, 276):
        protocol = int.from_bytes(data[{1: 12, 113: 14, 276: 0}[link]:][:2], 'big')
        while protocol in (0x8100, 0x88a8, 0x9100):
            if len(data) <= ip + 4:
                raise ValueError('Truncated VLAN header.')
            protocol = int.from_bytes(data[ip + 2:ip + 4], 'big'); ip += 4
        if protocol not in (0x0800, 0x86dd):
            return None
    version = data[ip] >> 4
    if version == 4 and len(data) >= ip + 20:
        if data[ip + 9] != 6:
            return None
        if int.from_bytes(data[ip + 6:ip + 8], 'big') & 0x3fff:
            raise ValueError('IPv4 fragments are not reassembled.')
        size = (data[ip] & 15) * 4
        if size < 20:
            raise ValueError('Invalid IPv4 header.')
        tcp, end = ip + size, ip + int.from_bytes(data[ip + 2:ip + 4], 'big')
        src, dst = data[ip + 12:ip + 16], data[ip + 16:ip + 20]
    elif version == 6 and len(data) >= ip + 40:
        tcp, end = ip + 40, ip + 40 + int.from_bytes(data[ip + 4:ip + 6], 'big')
        protocol = data[ip + 6]
        src, dst = data[ip + 8:ip + 24], data[ip + 24:ip + 40]
        for _ in range(12):
            if protocol not in (0, 43, 44, 51, 60):
                break
            if protocol == 44:
                raise ValueError('IPv6 fragments are not reassembled.')
            if tcp + 2 > min(end, len(data)):
                raise ValueError('Truncated IPv6 extension header.')
            size = (data[tcp + 1] + (2 if protocol == 51 else 1)) * (4 if protocol == 51 else 8)
            protocol = data[tcp]; tcp += size
        if protocol != 6:
            return None
    else:
        raise ValueError('Invalid or truncated IP header.')
    if tcp + 20 > min(end, len(data)):
        raise ValueError('Truncated TCP header.')
    sport, dport, seq = struct.unpack_from('!HHI', data, tcp)
    size = (data[tcp + 12] >> 4) * 4
    if size < 20 or tcp + size > min(end, len(data)):
        raise ValueError('Invalid TCP header length.')
    return Segment((src, sport), (dst, dport), seq, data[tcp + 13], data[tcp + size:end], end - tcp - size)


class HalfStream:
    def __init__(self, direction, peer):
        self.direction, self.peer = direction, peer
        self.next = self.end = None
        self.pending = []
        self.epoch = 0
        self.unreliable = True
        self.time = 0.0

    def row(self, data, **extra):
        return dict(kind='data', time=self.time, direction=self.direction, peer=self.peer, data=data,
                    tcp_capture=True, tcp_epoch=self.epoch, tcp_unreliable=self.unreliable, **extra)

    def gap(self, end):
        missing = end - self.next
        yield self.row(b'', tcp_gap=missing, display_partial=True, display_reason=f'TCP capture gap: {missing} bytes')
        self.next = end
        self.epoch += 1
        self.unreliable = True

    def drain(self):
        while self.pending and self.pending[0][0] <= self.next:
            start, data = self.pending.pop(0)
            part = data[self.next - start:]
            if part:
                self.next += len(part)
                yield self.row(part)

    def feed(self, segment, timestamp):
        self.time = timestamp
        syn = bool(segment.flags & SYN)
        seq = (segment.seq + syn) % MOD
        if self.next is None:
            if not (syn or segment.length or segment.flags & FIN):
                return
            self.next = self.end = seq
            self.unreliable = not syn
        start = self.next + (seq - self.next + MOD // 2) % MOD - MOD // 2
        if segment.length or segment.flags & FIN:
            self.end = max(self.end, start + segment.length)
        if segment.data and start + len(segment.data) > self.next:
            self.pending.append((start, segment.data))
            self.pending.sort(key=lambda item: item[0])
            yield from self.drain()
        if len(self.pending) >= 64 or sum(len(data) for _, data in self.pending) > 128 * 1024:
            yield from self.gap(self.pending[0][0])
            yield from self.drain()

    def finish(self):
        while self.pending:
            yield from self.gap(self.pending[0][0])
            yield from self.drain()
        if self.next is not None and self.end > self.next:
            yield from self.gap(self.end)


def endpoint(address):
    ip, port = address
    host = str(ipaddress.ip_address(ip))
    return f'[{host}]:{port}' if len(ip) == 16 else f'{host}:{port}'


class TcpStreams:
    def __init__(self, port=None):
        self.port = port
        self.flows = OrderedDict()
        self.count = self.skipped = 0

    def feed(self, packet):
        try:
            segment = decode(packet)
        except ValueError:
            self.skipped += 1
            return
        if segment is None:
            return
        a, b = segment.source, segment.destination
        if self.port is not None and self.port not in (a[1], b[1]):
            return
        key = (packet.interface, *sorted((a, b)))
        opening = (a, segment.seq) if segment.flags & (SYN | ACK) == SYN else None
        old = self.flows.get(key)
        if old is None or opening and opening != old[0]:
            if old:
                yield from self.close(self.flows.pop(key))
            if len(self.flows) >= 64:
                yield from self.close(self.flows.popitem(last=False)[1])
            client, server = (b, a) if (self.port == a[1] != b[1] or
                                       self.port != b[1] and segment.flags & (SYN | ACK) == (SYN | ACK)) else (a, b)
            self.count += 1
            peer = f'#{self.count} {endpoint(client)} → {endpoint(server)}'
            self.flows[key] = opening, {client: HalfStream('TX', peer), server: HalfStream('RX', peer)}
        self.flows.move_to_end(key)
        yield from self.flows[key][1][a].feed(segment, packet.time)
        if segment.flags & RST:
            yield from self.close(self.flows.pop(key))

    @staticmethod
    def close(flow):
        for half in flow[1].values():
            yield from half.finish()

    def finish(self):
        for flow in self.flows.values():
            yield from self.close(flow)
        self.flows.clear()


def open_capture(path, framer, port=None, max_rows=2000, max_bytes=8*1024*1024):
    if Path(path).stat().st_size > 32 * 1024 * 1024:
        raise ValueError('TCP capture exceeds 32 MiB. Export a smaller filtered capture.')
    streams = TcpStreams(port)
    framing = DisplayFraming(framer)
    session = namespace()
    rows, used, ordinal = [], 0, 0
    def collect(batch):
        nonlocal used
        for row in batch:
            used += retained_size(row)
            if len(rows) >= max_rows or used > max_bytes:
                raise ValueError('TCP capture exceeds the Traffic import limit. Export a smaller filtered capture.')
            rows.append(row)
    def frame(batch):
        nonlocal ordinal
        for row in batch:
            ordinal += 1
            row.update(session=session, event_id=f'{session}:{ordinal}', event_version=1)
            collect(framing.feed(row))
    with open(path, 'rb') as stream:
        for index, packet in enumerate(packets(stream), 1):
            if index > 100_000:
                raise ValueError('TCP capture exceeds 100,000 packets. Export a smaller filtered capture.')
            frame(streams.feed(packet))
    frame(streams.finish())
    collect(framing.flush('capture ended before frame completed'))
    if not rows:
        raise ValueError(f'No TCP payload for this selection ({streams.skipped} unsupported or malformed packets skipped).')
    if streams.skipped:
        for row in rows:
            row.pop('tcp_complete', None)
    return rows, streams.skipped
