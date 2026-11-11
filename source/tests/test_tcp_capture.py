import io
import ipaddress
import struct
import tempfile
import unittest
from pathlib import Path

from probe.capture import load_capture, replay_plan
from probe.codec import Framer
from probe.exporting import write_export
from probe.pcap import packets
from probe.simulation import compile_capture
from probe.tcp_stream import TcpStreams, open_capture
from probe.trace_path import find_matches


def wire(seq, payload=b'', flags=16, reverse=False, ipv6=False, missing=0):
    source = ('::1' if ipv6 else '127.0.0.1', 41234)
    target = ('::2' if ipv6 else '127.0.0.2', 9000)
    a, b = (target, source) if reverse else (source, target)
    addresses = ipaddress.ip_address(a[0]).packed + ipaddress.ip_address(b[0]).packed
    tcp = struct.pack('!HHIIBBHHH', a[1], b[1], seq, 0, 0x50, flags, 65535, 0, 0)
    size = len(tcp) + len(payload) + missing
    ip = (struct.pack('!IHBB', 6 << 28, size, 6, 64) if ipv6 else
          struct.pack('!BBHHHBBH', 0x45, 0, size + 20, 0, 0, 64, 6, 0))
    return ip + addresses + tcp + payload


def pcap(frames, endian='<', link=101):
    out = struct.pack(endian + 'IHHIIII', 0xa1b2c3d4, 2, 4, 0, 0, 262144, link)
    for i, data in enumerate(frames):
        out += struct.pack(endian + 'IIII', 100 + i, 0, len(data), len(data)) + data
    return out


def pcapng(frames, endian='>'):
    def block(kind, data):
        data += b'\0' * (-len(data) % 4)
        size = len(data) + 12
        return struct.pack(endian + 'II', kind, size) + data + struct.pack(endian + 'I', size)
    section = block(0x0a0d0d0a, struct.pack(endian + 'IHHq', 0x1a2b3c4d, 1, 0, -1))
    options = struct.pack(endian + 'HHB', 9, 1, 9) + b'\0'*3
    interface = block(1, struct.pack(endian + 'HHI', 101, 0, 262144) + options)
    records = [block(6, struct.pack(endian + 'IIIII', 0, 0, 1_250_000_000, len(data), len(data)) + data) for data in frames]
    return section + interface + b''.join(records)


class TcpCaptureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'test.pcap'

    def read(self, frames, framing='Delimiter'):
        self.path.write_bytes(pcap(frames))
        rows, skipped = open_capture(self.path, lambda: Framer(framing))
        self.assertEqual(skipped, 0)
        return rows

    def test_pcapng_timestamp_and_truncation(self):
        data = pcapng([wire(5, b'hello', ipv6=True)])
        packet, = packets(io.BytesIO(data))
        self.assertEqual(packet.time, 1.25)
        streams = TcpStreams(9000)
        row, = streams.feed(packet)
        self.assertEqual(row['data'], b'hello')
        self.assertIn('[::1]:41234', row['peer'])
        with self.assertRaises(ValueError):list(packets(io.BytesIO(data[:-1])))

    def test_out_of_order_wrap_retransmission_and_reuse(self):
        rows = self.read([wire(0xfffffffd, flags=2), wire(99, flags=18, reverse=True),
                          wire(0, b'CD\n'), wire(0xfffffffe, b'AB'), wire(0xffffffff, b'BCD\n'),
                          wire(100, b'OK\n', reverse=True)])
        self.assertEqual([(r['direction'],r['data']) for r in rows], [('TX', b'ABCD\n'), ('RX', b'OK\n')])
        self.assertTrue(all(r['tcp_complete'] for r in rows))
        self.assertEqual(replay_plan(rows), [(0, b'ABCD\n')])
        self.assertEqual(compile_capture(rows).exchanges[0].replies[0].data, b'OK\n')

    def test_gap_never_joins_two_application_fragments(self):
        rows = self.read([wire(4, flags=2), wire(5, b'partial'), wire(14, b'tail\n')])
        self.assertEqual([r['data'] for r in rows], [b'partial', b'', b'tail\n'])
        self.assertEqual(rows[1]['tcp_gap'], 2)
        self.assertFalse(any(r.get('tcp_complete') for r in rows))
        self.assertEqual(find_matches({'data': b'partialtail\n'}, list(enumerate(rows))), [])
        with self.assertRaisesRegex(ValueError, 'complete framed TCP'):replay_plan(rows)

    def test_snap_truncation_and_new_connection_isolate_streams(self):
        rows = self.read([wire(9, flags=2), wire(10, b'old', missing=4), wire(30, flags=2), wire(31, b'new\n')])
        self.assertEqual(rows[0]['data'], b'old')
        self.assertEqual(rows[1]['tcp_gap'], 4)
        self.assertEqual(rows[2]['data'], b'new\n')
        self.assertNotEqual(rows[0]['peer'], rows[2]['peer'])

    def test_unframed_and_midstream_cannot_replay_after_export(self):
        rows = self.read([wire(12, b'midstream\n')])
        self.assertTrue(rows[0]['tcp_unreliable'])
        for suffix in ('.jsonl', '.csv'):
            path = self.path.with_suffix(suffix)
            with path.open('w', encoding='utf-8', newline='') as out:write_export(out, rows, suffix)
            imported = load_capture(path)
            self.assertEqual(imported[0]['time'], rows[0]['time'])
            with self.assertRaisesRegex(ValueError, 'complete framed TCP'):replay_plan(imported)

    def test_pcap_recording_copies_exact_packet_bytes(self):
        data = pcap([wire(1, b'hello')], endian='>')
        out = io.BytesIO()
        self.assertEqual(len(list(packets(io.BytesIO(data), out))), 1)
        self.assertEqual(out.getvalue(), data)
