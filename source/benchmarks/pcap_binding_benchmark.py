"""Compare Probe's bindings and PyPI libpcap against one native library."""

import argparse
import ctypes as C
import ctypes.util
import hashlib
import importlib.metadata as metadata
import json
import os
from pathlib import Path
import platform
import random
import socket
import statistics
import struct
import sys
import tempfile
import threading
import time
from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from probe import pcap_live
from probe.pcap import Packet, packets, write_header, write_packet
from probe.tcp_stream import TcpStreams, decode

PORT = 42420
FUNCTIONS = ("open_offline", "open_live", "close", "geterr", "datalink", "compile", "setfilter",
             "freecode", "next_ex", "setnonblock", "stats", "lib_version", "findalldevs", "freealldevs")
EXTRA = ("create", "activate", "set_buffer_size", "set_immediate_mode", "set_tstamp_precision",
         "open_offline_with_tstamp_precision", "dispatch", "breakloop")


def backends(path):
    system_lookup = ctypes.util.find_library
    with patch.object(ctypes.util, "find_library", side_effect=lambda name: path if name == "pcap" and path else system_lookup(name)):
        native = pcap_live.library()
    for name, result, args in (
        ("open_offline", C.c_void_p, (C.c_char_p, C.c_char_p)),
        ("lib_version", C.c_char_p, ()),
    ):
        fn = getattr(native, "pcap_" + name)
        fn.restype, fn.argtypes = result, args
    library = str(native._name)
    with patch.object(ctypes.util, "find_library", side_effect=lambda name: library if name.replace("\\", "/") in ("pcap", "npcap/wpcap") else system_lookup(name)):
        import libpcap

    def package_header(h):
        stamp = h.ts
        return stamp.tv_sec, stamp.tv_usec, h.caplen, h.len

    native_api = SimpleNamespace(**{name: getattr(native, "pcap_" + name) for name in FUNCTIONS},
                                 program=pcap_live.Filter, stat=C.c_uint * 16,
                                 header_values=lambda h: (h.sec, h.usec, h.captured, h.length),
                                 drop_values=lambda s: (s[1], s[2]))
    package_api = SimpleNamespace(**{name: getattr(libpcap, name) for name in FUNCTIONS},
                                  program=libpcap.bpf_program, stat=libpcap.stat,
                                  header_values=package_header,
                                  drop_values=lambda s: (s.ps_drop, s.ps_ifdrop))
    extended = getattr(native, "pcap_open_offline_with_tstamp_precision", None)
    if extended is not None:
        extended.restype, extended.argtypes = C.c_void_p, (C.c_char_p, C.c_uint, C.c_char_p)
    native_api.open_with_precision = extended
    package_api.open_with_precision = getattr(libpcap, "open_offline_with_tstamp_precision", None)
    assert native_api.lib_version() == package_api.lib_version(), "Different native versions"
    footprint = metadata.distribution("libpcap")
    details = dict(native_library=library, native_version=native_api.lib_version().decode(),
                   pypi_version=footprint.version, pypi_direct_dependencies=footprint.requires,
                   pypi_installed_bytes=sum(footprint.locate_file(f).stat().st_size for f in footprint.files
                                            if footprint.locate_file(f).is_file()),
                   extra_apis={n: dict(native_symbol=hasattr(native, "pcap_" + n),
                                       pypi_binding=hasattr(libpcap, n)) for n in EXTRA})
    return {"direct": native_api, "pypi": package_api}, details


class Reader:
    def __init__(self, stack, api, *, path=None, device=None, port=PORT, rules=None):
        self.api = api
        error = C.create_string_buffer(256)
        if path is None:
            self.handle = api.open_live(os.fsencode(device), pcap_live.SNAPLEN, 0, 25, error)
        else:
            self.handle = api.open_offline(os.fsencode(path), error)
        if not self.handle:
            raise OSError(error.value.decode(errors="replace"))
        stack.callback(api.close, self.handle)
        self.link = api.datalink(self.handle)
        if self.link == 12 and os.name != "nt":
            self.link = 101
        rule = api.program()
        self.check(api.compile(self.handle, C.byref(rule), rules or f"tcp port {port}".encode(), 1, 0xffffffff))
        try:
            self.check(api.setfilter(self.handle, C.byref(rule)))
        finally:
            api.freecode(C.byref(rule))
        if path is None and api.setnonblock(self.handle, 1, error) != 0:
            raise OSError(error.value.decode(errors="replace"))
        self.header = api.next_ex.argtypes[1]._type_()
        self.data = api.next_ex.argtypes[2]._type_()

    def check(self, rc):
        if rc != 0:
            raise OSError(self.api.geterr(self.handle).decode(errors="replace"))

    def read(self):
        status = self.api.next_ex(self.handle, C.byref(self.header), C.byref(self.data))
        if status in (0, -2):
            return status, None
        self.check(status - 1)
        sec, usec, caplen, wirelen = self.api.header_values(self.header.contents)
        if not 0 <= caplen <= min(wirelen, pcap_live.SNAPLEN):
            raise ValueError("Invalid capture length")
        return 1, Packet(sec + usec / 1e6, self.link, C.string_at(self.data, caplen), wire_size=wirelen)

    def offline_packets(self):
        while True:
            status, packet = self.read()
            if status == -2:
                return
            if status != 1:
                raise OSError(f"Unexpected offline status: {status}")
            yield packet

    def drops(self):
        stats = self.api.stat()
        return self.api.drop_values(stats) if self.api.stats(self.handle, C.byref(stats)) == 0 else None


def fixture_packet(i, link):
    variant = i % 4
    payload = struct.pack("!I", i) + bytes([i % 256]) * (32 + i % 120)
    if variant == 2:
        proto, transport = 17, struct.pack("!HHHH", 31000, PORT, 8 + len(payload), 0)
    else:
        proto = 6
        transport = struct.pack("!HHIIBBHHH", 31000, PORT + (variant == 1), i, 0, 0x50, 0x18, 8192, 0, 0)
    ip = struct.pack("!BBHHHBBH4s4s", 0x45, 0, 20 + len(transport) + len(payload),
                     0, 0, 64, proto, 0, b"\x7f\0\0\x01", b"\x7f\0\0\x01")
    prefix = b"\0" * 12 + b"\x08\0" if link == 1 else b""
    frame = prefix + ip + transport + payload
    data = frame[:-19] if variant == 3 else frame
    return Packet(1_700_000_000 + (1027 * i % 1_000_000) / 1e6, link, data, wire_size=len(frame))


def make_capture(path, count, link):
    with path.open("wb") as stream:
        write_header(stream, link, pcap_live.SNAPLEN)
        for i in range(count):
            write_packet(stream, fixture_packet(i, link))


def verify_offline(api, path, link):
    with path.open("rb") as stream:
        expected = [p for i, p in enumerate(packets(stream)) if i % 4 in (0, 3)]
    with ExitStack() as stack:
        reader = Reader(stack, api, path=path)
        actual = list(reader.offline_packets())
        assert actual == expected, f"PCAP content, filters, timestamps or lengths differ (link {link})"
        assert any(p.wire_size > len(p.data) for p in actual)
    for options in ({"path": path.with_name("missing.pcap")}, {"path": path, "rules": b"tcp port ("}):
        try:
            with ExitStack() as stack:
                Reader(stack, api, **options)
        except OSError as error:
            assert str(error), "Expected a useful error"
        else:
            raise AssertionError("Invalid capture or filter opened")
    return len(actual)


def offline_trial(api, path, expected):
    with ExitStack() as stack:
        reader = Reader(stack, api, path=path)
        wall, cpu = time.perf_counter_ns(), time.thread_time_ns()
        count = sum(1 for _ in reader.offline_packets())
        wall, cpu = time.perf_counter_ns() - wall, time.thread_time_ns() - cpu
    assert count == expected
    return dict(packets=count, wall_ms=wall / 1e6, cpu_ms=cpu / 1e6, packets_per_s=count * 1e9 / wall)


def verify_nano(api, path):
    if api.open_with_precision is None:
        return "unavailable"
    error = C.create_string_buffer(256)
    with ExitStack() as stack:
        handle = api.open_with_precision(os.fsencode(path), 1, error)
        if not handle:
            raise OSError(error.value.decode(errors="replace"))
        stack.callback(api.close, handle)
        header, data = (p._type_() for p in api.next_ex.argtypes[1:])
        assert api.next_ex(handle, C.byref(header), C.byref(data)) == 1
        assert api.header_values(header.contents) == (1_700_000_000, 123456789, 1, 1)
        assert C.string_at(data, 1) == b"\xa5"
    return "exact"


def read_exact(sock, size):
    with sock.makefile("rb") as stream:
        return stream.read(size)


def loopbacks(api):
    error = C.create_string_buffer(256)
    first = api.findalldevs.argtypes[0]._type_()
    if api.findalldevs(C.byref(first), error) != 0:
        raise OSError(error.value.decode(errors="replace"))
    result = []
    try:
        current = first
        while current:
            interface = current.contents
            if interface.name and interface.flags & 1:
                result.append(os.fsdecode(interface.name))
            current = interface.next
        return result
    finally:
        if first:
            api.freealldevs(first)


def send_payload(sock, data, paced):
    if not paced:
        sock.sendall(data)
        return
    for offset in range(0, len(data), 8192):
        sock.sendall(data[offset:offset + 8192])
        time.sleep(.003)


def live_trial(api, device, payload, *, paced):
    with ExitStack() as stack:
        server = stack.enter_context(socket.socket())
        server.bind(("127.0.0.1", 0))
        server.listen()
        server.settimeout(3)
        port = server.getsockname()[1]
        reader = Reader(stack, api, device=device, port=port)
        start = time.perf_counter_ns()
        assert reader.read() == (0, None), "Idle read must return without a packet"
        idle_read_us = (time.perf_counter_ns() - start) / 1000
        streams = TcpStreams(port)
        digests = {key: hashlib.sha256() for key in ("TX", "RX")}
        counts = dict(TX=0, RX=0)
        stop, ready, complete = threading.Event(), threading.Event(), threading.Event()
        worker = SimpleNamespace(packets=0, ignored=0, gaps=0, error=None, cpu_ms=0.0)

        def consume(rows):
            for row in rows:
                if row.get("tcp_gap"):
                    worker.gaps += 1
                direction, data = row["direction"], row["data"]
                counts[direction] += len(data)
                digests[direction].update(data)

        def capture():
            cpu = time.thread_time_ns()
            ready.set()
            try:
                while not stop.is_set():
                    status, packet = reader.read()
                    if status == 0:
                        stop.wait(.01)
                        continue
                    if status != 1:
                        raise OSError(f"Unexpected live status: {status}")
                    worker.packets += 1
                    segment = decode(packet)
                    if not segment or port not in (segment.source[1], segment.destination[1]):
                        worker.ignored += 1
                    consume(streams.feed(packet))
                    if min(counts.values()) >= len(payload):
                        complete.set()
                consume(streams.finish())
            except Exception as error:
                worker.error = error
                complete.set()
            finally:
                worker.cpu_ms = (time.thread_time_ns() - cpu) / 1e6

        thread = threading.Thread(target=capture)
        thread.start()
        try:
            assert ready.wait(2)
            idle_start = time.perf_counter_ns()
            time.sleep(.10)
            assert worker.packets == 0
            idle_stopping = time.perf_counter_ns()
            stop.set()
            thread.join()
            idle_wait_ms = (idle_stopping - idle_start) / 1e6
            idle_stop_ms = (time.perf_counter_ns() - idle_stopping) / 1e6
            idle_cpu_ms = worker.cpu_ms
            if worker.error:
                raise worker.error

            stop.clear()
            ready.clear()
            thread = threading.Thread(target=capture)
            thread.start()
            assert ready.wait(2)
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as unrelated:
                unrelated.sendto(b"not TCP", server.getsockname())
            with socket.create_connection(server.getsockname(), timeout=3) as client:
                peer, _ = server.accept()
                with peer:
                    peer.settimeout(3)
                    def echo():
                        actual = read_exact(peer, len(payload))
                        send_payload(peer, actual[::-1], paced)
                    reply = threading.Thread(target=echo)
                    start = time.perf_counter_ns()
                    reply.start()
                    try:
                        send_payload(client, payload, paced)
                        assert read_exact(client, len(payload)) == payload[::-1], "Bad TCP workload echo"
                    finally:
                        reply.join()
            offered_ms = (time.perf_counter_ns() - start) / 1e6
            tail_ms = (time.perf_counter_ns() - start) / 1e6 - offered_ms if complete.wait(.5) else None
        finally:
            stopping = time.perf_counter_ns()
            stop.set()
            thread.join()
            stop_ms = (time.perf_counter_ns() - stopping) / 1e6
        if worker.error:
            raise worker.error
        expected = {"TX": hashlib.sha256(payload).digest(), "RX": hashlib.sha256(payload[::-1]).digest()}
        exact = all(counts[k] == len(payload) and digest.digest() == expected[k] for k, digest in digests.items())
        return dict(offered_bytes_each_direction=len(payload), reconstructed_bytes=counts, exact=exact,
                    filter_leaks=worker.ignored, gaps=worker.gaps, skipped=streams.skipped,
                    captured_packets=worker.packets, driver_drops=reader.drops(),
                    idle_read_us=idle_read_us, idle_wait_ms=idle_wait_ms, idle_cpu_ms=idle_cpu_ms,
                    idle_stop_ms=idle_stop_ms, socket_roundtrip_ms=offered_ms, capture_tail_ms=tail_ms,
                    stop_ms=stop_ms, capture_thread_cpu_ms=worker.cpu_ms)


def trials(apis, repeats, run):
    result = {name: [] for name in apis}
    for i in range(repeats):
        for name in (apis if i % 2 == 0 else reversed(apis)):
            result[name].append(run(apis[name]))
    return result


def summarize(rows, keys):
    return {name: {k: dict(median=statistics.median(values), min=min(values), max=max(values))
                   for k in keys if (values := [r[k] for r in records if r[k] is not None])}
            for name, records in rows.items()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--library", type=Path, help="Absolute native libpcap file override (Linux)")
    parser.add_argument("--packets", type=int, default=200_000, help="Number of records in the offline workload")
    parser.add_argument("--repeats", type=int, default=7)
    parser.add_argument("--live", metavar="LOOPBACK", help="Also capture synthetic TCP on the selected loopback interface")
    parser.add_argument("--live-bytes", type=int, default=1024 * 1024, help="TCP payload bytes per direction")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.packets < 4 or args.repeats < 1 or args.live_bytes < 1:
        parser.error("use at least four packets, one repeat, and one live payload byte")
    if args.library and (os.name == "nt" or not args.library.is_absolute() or not args.library.is_file()):
        parser.error("--library requires an existing absolute libpcap path on Linux")
    apis, details = backends(str(args.library) if args.library else None)
    report = dict(platform=platform.platform(), python=platform.python_version(), **details, repeats=args.repeats)
    with tempfile.TemporaryDirectory() as directory:
        directory = Path(directory)
        report["offline_correctness"] = {name: {} for name in apis}
        for link in (1, 101):
            path = directory / f"check-{link}.pcap"
            make_capture(path, 1024, link)
            for name, api in apis.items():
                report["offline_correctness"][name][f"link_{link}"] = verify_offline(api, path, link)
        path = directory / "check-nano.pcap"
        path.write_bytes(struct.pack("<IHHIIIIIIII", 0xa1b23c4d, 2, 4, 0, 0, 64, 1,
                                     1_700_000_000, 123456789, 1, 1) + b"\xa5")
        report["nanosecond_file_api"] = {name: verify_nano(api, path) for name, api in apis.items()}
        path = directory / "timed.pcap"
        make_capture(path, args.packets, 1)
        accepted = (args.packets + 3) // 4 + args.packets // 4
        offline = trials(apis, args.repeats, lambda api: offline_trial(api, path, accepted))
        report["offline"] = dict(input_packets=args.packets, trials=offline,
                                 summary=summarize(offline, ("wall_ms", "cpu_ms", "packets_per_s")))
    failed = False
    if args.live:
        payload = random.Random(1).randbytes(args.live_bytes)
        try:
            devices = {name: loopbacks(api) for name, api in apis.items()}
            if not all(args.live in names for names in devices.values()):
                raise ValueError("--live must be a loopback interface found by both bindings")
            live = trials(apis, args.repeats, lambda api: live_trial(api, args.live, payload, paced=True))
            burst = trials(apis, min(3, args.repeats), lambda api: live_trial(api, args.live, payload, paced=False))
            report["live"] = dict(device=args.live, loopbacks=devices, paced_trials=live, burst_trials=burst,
                                  paced_summary=summarize(live, ("idle_read_us", "idle_cpu_ms", "idle_stop_ms",
                                      "socket_roundtrip_ms", "capture_tail_ms", "stop_ms", "capture_thread_cpu_ms")))
            failed = any(not (row["exact"] and not (row["filter_leaks"] or row["gaps"] or row["skipped"]))
                         for records in live.values() for row in records)
        except (OSError, AssertionError, ValueError) as error:
            report["live"] = dict(device=args.live, error=str(error))
            failed = True
    output = json.dumps(report, indent=2) + "\n"
    if args.output:
        args.output.write_text(output, encoding="utf-8")
    print(output, end="")
    return failed


if __name__ == "__main__":
    sys.exit(main())
