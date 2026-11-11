import os
import socket
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from probe.codec import Framer
from probe.diagnostics import session, wait_for
from probe.pcap import Packet, packets
from probe.tcp_stream import decode, open_capture
from test_tcp_capture import wire


class TcpLiveTests(unittest.TestCase):
    def test_engine_monitor_is_read_only_and_saves_reopenable_pcap(self):
        frames = [wire(11, flags=2), wire(21, flags=18, reverse=True),
                  wire(12, b'ping\n'), wire(22, b'pong\n', reverse=True)]
        class Capture:
            link = 101
            def __init__(self, source, port):self.rows = iter(Packet(42.0, self.link, frame) for frame in frames)
            def read(self):return next(self.rows, None)
            def drops(self):return (0, 0)
            def close(self):pass
        with tempfile.TemporaryDirectory() as directory, patch('probe.tcp_monitor.LiveCapture', Capture):
            path = Path(directory) / 'capture.pcap'
            with session('TCP Monitor', tcp_port=9000, tcp_source='fixture', tcp_pcap=path) as (engine, events, _):
                wait_for(lambda:engine.rx == 5 and engine.tx == 5, events)
                with self.assertRaisesRegex(RuntimeError, 'capture-only'):engine.send(b'forbidden')
            self.assertTrue(any(e['kind']=='tcp_summary' for e in events))
            live = [e for e in events if e['kind']=='data']
            self.assertTrue(all('monotonic_ns' not in e for e in live))
            rows, skipped = open_capture(path, Framer)
            self.assertEqual(skipped, 0)
            self.assertEqual([(e['data'],e['time']) for e in rows], [(e['data'],e['time']) for e in live])

    @unittest.skipUnless(os.environ.get('PROBE_LIVE_TCP_TEST')=='1', 'Requires libpcap/Npcap capture privileges')
    def test_native_loopback_capture_and_port_filter(self):
        from probe.pcap_live import interfaces
        device = next(name for label, name in interfaces() if label.startswith('Loopback'))
        with tempfile.TemporaryDirectory() as directory, socket.socket() as server, socket.socket() as ignored:
            path = Path(directory) / 'native.pcap'
            for sock in (server, ignored):sock.bind(('127.0.0.1', 0));sock.listen()
            port = server.getsockname()[1]
            with session('TCP Monitor',tcp_port=port,tcp_source=device,tcp_pcap=path) as (engine,events,_):
                with socket.create_connection(ignored.getsockname(),timeout=3) as unrelated:
                    unrelated.sendall(b'not for this capture')
                with socket.create_connection(server.getsockname(),timeout=3) as client:
                    peer,_ = server.accept()
                    with peer:
                        client.sendall(b'probe request\n');self.assertEqual(peer.recv(64),b'probe request\n')
                        peer.sendall(b'device response\n');self.assertEqual(client.recv(64),b'device response\n')
                        wait_for(lambda:engine.tx==14 and engine.rx==16,events)
            with path.open('rb') as stream:
                segments = [decode(packet) for packet in packets(stream)]
                self.assertTrue(all(s is not None and port in (s.source[1],s.destination[1]) for s in segments))
            rows,_ = open_capture(path,lambda:Framer('Delimiter'))
            self.assertEqual([(r['direction'],r['data']) for r in rows], [('TX',b'probe request\n'),('RX',b'device response\n')])
            self.assertTrue(all(row['tcp_complete'] for row in rows))
