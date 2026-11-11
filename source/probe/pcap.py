'Bounded PCAP / PCAPNG packet reader shared by import and live capture.'
import struct
from dataclasses import dataclass

MAX_PACKET = 1024 * 1024
SECTION = b'\x0a\x0d\x0d\x0a'
MAGIC = {b'\xd4\xc3\xb2\xa1': ('<', 1e6), b'\xa1\xb2\xc3\xd4': ('>', 1e6),
         b'\x4d\x3c\xb2\xa1': ('<', 1e9), b'\xa1\xb2\x3c\x4d': ('>', 1e9)}


@dataclass(frozen=True, slots=True)
class Packet:
    time: float
    link: int
    data: bytes
    interface: tuple = (0, 0)


def read(stream, size, eof=False):
    value = stream.read(size)
    if eof and not value:
        return None
    if len(value) != size:
        raise ValueError('Capture ends inside a packet or block.')
    return value


def packets(stream, raw=None):
    magic = read(stream, 4)
    if magic == SECTION and raw is None:
        yield from pcapng(stream, magic)
        return
    if magic not in MAGIC:
        raise ValueError('Expected a PCAP or PCAPNG capture.')
    endian, scale = MAGIC[magic]
    header = read(stream, 20)
    major, _, _, _, snaplen, link = struct.unpack(endian + 'HHIIII', header)
    if major != 2 or not snaplen:
        raise ValueError('Invalid PCAP header.')
    if raw is not None:
        raw.write(magic + header)
    while (record := read(stream, 16, eof=True)) is not None:
        sec, fraction, size, original = struct.unpack(endian + 'IIII', record)
        if size > min(MAX_PACKET, snaplen, original) or fraction >= scale:
            raise ValueError('Invalid or oversized PCAP packet.')
        data = read(stream, size)
        if raw is not None:
            raw.write(record + data)
        yield Packet(sec + fraction / scale, link & 0xffff, data)


def interface_options(body, endian):
    resolution, offset, pos = 1e6, 0, 8
    while pos + 4 <= len(body):
        kind, size = struct.unpack_from(endian + 'HH', body, pos)
        pos += 4
        end = pos + ((size + 3) & ~3)
        if end > len(body):
            raise ValueError('Invalid PCAPNG interface option.')
        if kind == 0:
            break
        if kind == 9 and size == 1:
            code = body[pos]
            resolution = 2 ** (code & 127) if code & 128 else 10 ** code
        if kind == 14 and size == 8:
            offset = struct.unpack_from(endian + 'q', body, pos)[0]
        pos = end
    return resolution, offset


def pcapng(stream, kind):
    interfaces, section = [], -1
    while kind is not None:
        size = read(stream, 4)
        if kind == SECTION:
            order = read(stream, 4)
            endian = {b'\x4d\x3c\x2b\x1a': '<', b'\x1a\x2b\x3c\x4d': '>'}.get(order)
            if endian is None:
                raise ValueError('Invalid PCAPNG byte order.')
            interfaces, section = [], section + 1
            minimum, consumed = 28, 12
        else:
            minimum, consumed = 12, 8
        length = struct.unpack(endian + 'I', size)[0]
        if not minimum <= length <= 4 * MAX_PACKET or length % 4:
            raise ValueError('Invalid or oversized PCAPNG block.')
        body = read(stream, length - consumed - 4)
        if read(stream, 4) != size:
            raise ValueError('PCAPNG block lengths disagree.')
        block = struct.unpack(endian + 'I', kind)[0]
        if kind == SECTION and struct.unpack_from(endian + 'H', body)[0] != 1:
            raise ValueError('Unsupported PCAPNG major version.')
        if block == 1:
            if len(body) < 8 or len(interfaces) >= 256:
                raise ValueError('Invalid PCAPNG interface or too many interfaces.')
            link, _, snaplen = struct.unpack_from(endian + 'HHI', body)
            interfaces.append((link, snaplen or MAX_PACKET, *interface_options(body, endian)))
        elif block in (2, 3, 6):
            if block == 3:
                if len(body) < 4 or not interfaces:
                    raise ValueError('Invalid PCAPNG simple packet.')
                original = struct.unpack_from(endian + 'I', body)[0]
                index, stamp, size, start = 0, 0, min(original, interfaces[0][1]), 4
            else:
                if len(body) < 20:
                    raise ValueError('Invalid PCAPNG packet header.')
                if block == 2:
                    index, _, hi, lo, size, original = struct.unpack_from(endian + 'HHIIII', body)
                else:
                    index, hi, lo, size, original = struct.unpack_from(endian + 'IIIII', body)
                stamp, start = (hi << 32) | lo, 20
            if index >= len(interfaces):
                raise ValueError('PCAPNG packet refers to an unknown interface.')
            link, snaplen, resolution, offset = interfaces[index]
            if size > min(snaplen, original, MAX_PACKET) or start + ((size + 3) & ~3) > len(body):
                raise ValueError('Invalid or oversized PCAPNG packet.')
            timestamp = stamp / resolution + offset if block != 3 else 0
            if not 0 <= timestamp < 253402300799:
                raise ValueError('PCAPNG packet timestamp is outside the supported range.')
            yield Packet(timestamp, link, body[start:start + size], (section, index))
        kind = read(stream, 4, eof=True)
