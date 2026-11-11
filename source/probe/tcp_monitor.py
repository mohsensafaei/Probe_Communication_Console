from contextlib import ExitStack

from .pcap import write_header, write_packet
from .pcap_live import LiveCapture, SNAPLEN
from .tcp_stream import TcpStreams


def run_monitor(engine):
    port = int(engine.cfg['tcp_port'])
    streams = TcpStreams(port)
    path = engine.cfg.get('tcp_pcap')
    count = 0
    with ExitStack() as stack:
        capture = LiveCapture(engine.cfg['tcp_source'], port)
        stack.callback(capture.close)
        raw = stack.enter_context(open(path, 'xb')) if path else None
        if raw:write_header(raw, capture.link, SNAPLEN)
        engine._connected(f'TCP monitor · port {port} · TX toward port, RX from port · read-only')

        def publish(rows):
            for row in rows:
                if streams.skipped:row['tcp_unreliable'] = True
                row.pop('kind')
                engine.event('data', **row)

        try:
            while not engine.stopping.is_set():
                packet = capture.read()
                if packet is None:
                    engine.stopping.wait(.01)
                    continue
                count += 1
                if raw:write_packet(raw, packet)
                publish(streams.feed(packet))
        finally:
            publish(streams.finish())
            drops = capture.drops()
            stats = f'{drops[0]} capture / {drops[1]} interface drops reported' if drops is not None else 'drop statistics unavailable'
            saved = ' · Raw PCAP saved' if raw else ''
            engine.event('tcp_summary', message=f'{count} packets · {stats} · {streams.skipped} skipped{saved}')
