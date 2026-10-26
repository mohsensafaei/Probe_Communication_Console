"""Exercise COM-pair byte paths with real pySerial socket endpoints, without drivers.

These cross-platform tests do not assert that a Windows kernel COM driver exists.
Use test_serial_hardware.py with explicit COM ports for that integration check.
"""
from contextlib import contextmanager
from pathlib import Path
import socket
import tempfile
import unittest

from probe.capture import load_capture
from probe.diagnostics import received, session, wait_for
from probe.serial_endpoints import VirtualPair, port_identity
from probe.simulation import DeviceModel, Exchange, Reply


@contextmanager
def endpoint():
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        listener.settimeout(3)
        yield listener, "socket://127.0.0.1:%d" % listener.getsockname()[1]


def read_exact(connection, size):
    result = bytearray()
    while len(result) < size:
        chunk = connection.recv(size-len(result))
        if not chunk:
            raise AssertionError("Serial endpoint closed before all bytes arrived")
        result.extend(chunk)
    return bytes(result)


class VirtualCOMTests(unittest.TestCase):
    def test_pair_names_cannot_alias_physical_or_each_other(self):
        self.assertEqual(port_identity(r"\\.\COM20"), port_identity(" com20 "))
        for pair, physical in ((VirtualPair("COM20", "com20"), ""),
                               (VirtualPair("COM20", "COM21"), r"\\.\com21"),
                               (VirtualPair("", "COM21"), "")):
            with self.assertRaises(ValueError):
                pair.validate(physical)
        VirtualPair("COM20", "COM21").validate("COM3")

    def test_com_simulator_binary_capture_reset_and_injection(self):
        model = DeviceModel((Exchange(b"A\x00\xff", (Reply(b"one\x00\xff", 2),)),
                             Exchange(b"A\x00\xff", (Reply(b"two\x00\xff", 2),))))
        with endpoint() as (listener, url), tempfile.TemporaryDirectory() as directory:
            capture = Path(directory)/"capture.jsonl"
            with session("Device Simulator", simulator_model=model, simulator_transport="Virtual COM pair",
                         simulator_port=url, simulator_peer_port="COM21") as (engine, events, ready):
                port = engine.serials[0]
                self.assertEqual(ready["app_path"], "COM21")
                with listener.accept()[0] as app:
                    app.settimeout(3)
                    engine.record(capture)
                    app.sendall(b"A\x00\xffA\x00\xff")
                    self.assertEqual(read_exact(app, 10), b"one\x00\xfftwo\x00\xff")
                    engine.reset_simulator()
                    wait_for(lambda: any(e.get("state") == "ready" for e in events), events)
                    app.sendall(b"A\x00\xff")
                    self.assertEqual(read_exact(app, 5), b"one\x00\xff")
                    engine.send(b"injected")
                    self.assertEqual(read_exact(app, 8), b"injected")
                    wait_for(lambda: received(events).endswith(b"injected"), events)
                    engine.record()
                    rows = load_capture(capture)
                    self.assertEqual(b"".join(e["data"] for e in rows if e["direction"] == "TX"), b"A\x00\xff"*3)
                    self.assertEqual(b"".join(e["data"] for e in rows if e["direction"] == "RX"), received(events))
                # Stop while the serial socket is still open; peer closure is tested separately.
            self.assertFalse(port.is_open)

    def test_com_proxy_duplex_both_injection_sides_and_partner_advertisement(self):
        with endpoint() as (device_listener, device_url), endpoint() as (app_listener, app_url):
            with session("Serial Proxy", serial_port=device_url, app_port=app_url,
                         app_peer_port="COM21") as (engine, events, ready):
                self.assertEqual(ready["app_path"], "COM21")
                with device_listener.accept()[0] as device, app_listener.accept()[0] as app:
                    device.settimeout(3); app.settimeout(3)
                    wire = bytes(range(256))
                    app.sendall(wire)
                    self.assertEqual(read_exact(device, len(wire)), wire)
                    device.sendall(wire[::-1])
                    self.assertEqual(read_exact(app, len(wire)), wire[::-1])
                    engine.send(b"upstream")
                    self.assertEqual(read_exact(device, 8), b"upstream")
                    engine.send(b"downstream", side="App / downstream")
                    self.assertEqual(read_exact(app, 10), b"downstream")
                    wait_for(lambda: engine.tx == 264 and engine.rx == 266, events)

    def test_com_simulator_peer_disconnect_cleans_up(self):
        model = DeviceModel((Exchange(b"A", (Reply(b"B"),)),))
        with endpoint() as (listener, url):
            with session("Device Simulator", simulator_model=model, simulator_transport="Virtual COM pair",
                         simulator_port=url, simulator_peer_port="COM21") as (engine, events, _):
                connection, _ = listener.accept()
                connection.close()
                wait_for(lambda: not engine.thread.is_alive(), timeout=3)
                self.assertTrue(any(e["kind"] == "error" for e in events))
                self.assertFalse(engine.serials[0].is_open)
