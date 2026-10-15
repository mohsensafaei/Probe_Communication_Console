"""Opt-in USB modem tests. Send only the read-only AT attention command.

PROBE_TEST_SERIAL_PORT=/dev/ttyACM0 .venv/bin/python -m unittest discover \
    -s tests -p test_serial_hardware.py -v

Set PROBE_TEST_GUI=1 under xvfb-run to include the two real-device GUI tests.
Never discover/open a hardware port automatically during normal unit tests.
"""
from contextlib import contextmanager
from collections.abc import Callable, Iterator
from dataclasses import dataclass
import os
from pathlib import Path
import socket
import tempfile
import time
from typing import Any
import unittest
from unittest.mock import patch

import serial

from probe.capture import load_capture
from probe.diagnostics import received, session, wait_for
from probe.engine import Engine

Event = dict[str, Any]
COMMAND = b"AT\r"
ACK = b"\r\nOK\r\n"
PORT = os.environ.get("PROBE_TEST_SERIAL_PORT", "")
PAIR_PORT = os.environ.get("PROBE_TEST_APP_PORT", "")
PARTNER_PORT = os.environ.get("PROBE_TEST_PEER_PORT", "")
HAS_PAIR = os.name == "posix" or bool(PAIR_PORT and PARTNER_PORT)


@dataclass(frozen=True)
class SerialHardware:
    port: str
    baud: int = 115200


@contextmanager
def hardware_session(
    mode: str, hardware: SerialHardware
) -> Iterator[tuple[Engine, list[Event], Event]]:
    with session(mode, serial_port=hardware.port, baud=hardware.baud,
                 app_port="Auto PTY" if os.name == "posix" else PAIR_PORT,
                 app_peer_port=PARTNER_PORT) as connected:
        yield connected


@unittest.skipUnless(PORT, "Set PROBE_TEST_SERIAL_PORT for an attached AT-capable device")
class SerialHardwareTests(unittest.TestCase):
    def setUp(self) -> None:
        self.hardware = SerialHardware(PORT)

    def test_direct_usb_attention_and_capture(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "capture.jsonl"
            with hardware_session("USB / Serial", self.hardware) as (engine, events, _):
                engine.record(path)
                engine.send(COMMAND)
                wait_for(lambda: ACK in received(events), events)
                engine.record()
                self.assertEqual(engine.tx, len(COMMAND))
                rows = load_capture(path)
                self.assertEqual(b"".join(e["data"] for e in rows if e["direction"] == "TX"), COMMAND)
                self.assertEqual(b"".join(e["data"] for e in rows if e["direction"] == "RX"), received(events))
                self.assertIn(ACK, received(events))

    @unittest.skipUnless(HAS_PAIR, "Set PROBE_TEST_APP_PORT and PROBE_TEST_PEER_PORT for an installed COM pair")
    def test_usb_proxy_duplex_capture_and_injection(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            capture = Path(directory) / "capture.jsonl"
            raw = Path(directory) / "rx.bin"
            with hardware_session("Serial Proxy", self.hardware) as (engine, events, ready):
                engine.record(capture)
                engine.record(raw, raw=True)
                with serial.Serial(ready["app_path"], 115200, timeout=5) as app:
                    app.write(COMMAND)
                    reply = app.read_until(ACK, size=4096)
                    self.assertIn(ACK, reply)
                    wait_for(lambda: len(received(events)) >= len(reply), events)
                    self.assertEqual(received(events), reply)
                    self.assertEqual(engine.tx, len(COMMAND))
                    # Device-side injection follows the same physical USB path.
                    engine.send(COMMAND)
                    injected_reply = app.read_until(ACK, size=4096)
                    self.assertIn(ACK, injected_reply)
                    wait_for(lambda: engine.rx >= len(reply) + len(injected_reply), events)
                    self.assertEqual(engine.tx, 2 * len(COMMAND))
                    # App-side injection must reach the app without writing to USB.
                    marker = b"PROBE_APP_SIDE_TEST\r\n"
                    engine.send(marker, side="App / downstream")
                    self.assertEqual(app.read(len(marker)), marker)
                    wait_for(lambda: received(events).endswith(marker), events)
                    self.assertEqual(engine.tx, 2 * len(COMMAND))
                    engine.record()
                    engine.record(raw=True)
                    self.assertEqual(raw.read_bytes(), reply + injected_reply + marker)
                    rows = load_capture(capture)
                    self.assertEqual(b"".join(e["data"] for e in rows if e["direction"] == "TX"), COMMAND * 2)
                    self.assertEqual(b"".join(e["data"] for e in rows if e["direction"] == "RX"), raw.read_bytes())

    def test_real_usb_to_tcp_bridge(self) -> None:
        with hardware_session("Serial ↔ TCP", self.hardware) as (engine, events, ready):
            with socket.create_connection(ready["address"][:2], timeout=5) as app:
                app.sendall(COMMAND)
                reply = bytearray()
                while ACK not in reply:
                    chunk = app.recv(4096)
                    self.assertTrue(chunk, "USB-to-TCP bridge closed before the device acknowledged AT")
                    reply.extend(chunk)
                wait_for(lambda: len(received(events)) >= len(reply), events)
                self.assertEqual(received(events), bytes(reply))
                self.assertEqual(engine.tx, len(COMMAND))


    def test_recorded_phone_emulation_after_device_session_closes(self) -> None:
        from probe.diagnostics import session
        from probe.simulation import compile_capture
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/"phone.jsonl"
            with hardware_session("USB / Serial", self.hardware) as (engine, events, _):
                engine.record(path)
                engine.send(COMMAND)
                wait_for(lambda: ACK in received(events), events)
                engine.record()
                reply = received(events)
            model = compile_capture(load_capture(path))
            transport = "Virtual serial (PTY)" if os.name == "posix" else "Virtual COM pair" if HAS_PAIR else "TCP socket"
            with session("Device Simulator", simulator_model=model, simulator_transport=transport,
                         simulator_port=PAIR_PORT, simulator_peer_port=PARTNER_PORT) as (engine, events, ready):
                if transport == "TCP socket":
                    with socket.create_connection(ready["address"][:2], timeout=3) as app:
                        app.sendall(COMMAND)
                        actual = bytearray()
                        while len(actual) < len(reply):
                            chunk = app.recv(len(reply)-len(actual))
                            self.assertTrue(chunk)
                            actual.extend(chunk)
                        self.assertEqual(bytes(actual), reply)
                else:
                    with serial.Serial(ready["app_path"], 115200, timeout=3) as app:
                        app.write(COMMAND)
                        self.assertEqual(app.read(len(reply)), reply)
                self.assertNotIn(PORT, [port.port for port in engine.serials])


@unittest.skipUnless(PORT and os.environ.get("PROBE_TEST_GUI") == "1",
                     "Set PROBE_TEST_SERIAL_PORT and PROBE_TEST_GUI=1 with an X display")
class SerialHardwareGUITests(unittest.TestCase):
    def setUp(self) -> None:
        from probe.app import Probe
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        patcher = patch("probe.app.data_directory", return_value=Path(directory.name))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.app = Probe()
        self.addCleanup(self.app.close)
        self.errors: list[tuple[Any, ...]] = []
        self.app.report_callback_exception = lambda *error: self.errors.append(error)
        self.app.update()

    def spin(self, predicate: Callable[[], bool], timeout: float = 5) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.app.update()
            self.assertFalse(self.errors, self.errors)
            if predicate():
                return
            time.sleep(.01)
        self.fail(f"GUI condition timed out: {self.app.status.cget('text')}")

    def connect(self, mode: str) -> None:
        self.app.choose_mode(mode)
        self.app.vars["serial_port"].set(PORT)
        if os.name == "nt" and mode == "Serial Proxy":
            self.app.vars["app_port"].set(PAIR_PORT)
            self.app.vars["app_peer_port"].set(PARTNER_PORT)
        self.app.toggle()
        self.spin(lambda: self.app.engine.ready)

    def test_gui_direct_usb_transmit_receive_and_terminal(self) -> None:
        self.connect("USB / Serial")
        self.app.vars["send_mode"].set("Hex")
        self.app.payload.delete("1.0", "end")
        self.app.payload.insert("1.0", COMMAND.hex(" "))
        self.assertTrue(self.app.send())
        self.spin(lambda: ACK in b"".join(e["data"] for e in self.app.events.values() if e["direction"] == "RX"))
        self.assertEqual(self.app.engine.tx, len(COMMAND))
        self.assertIn("OK", "".join(self.app.terminal.model.screen.display))

    @unittest.skipUnless(HAS_PAIR, "Set PROBE_TEST_APP_PORT and PROBE_TEST_PEER_PORT for an installed COM pair")
    def test_gui_usb_proxy_forwarding(self) -> None:
        self.connect("Serial Proxy")
        self.spin(lambda: "App-side port:" in self.app.status.cget("text"))
        with serial.Serial(self.app.engine.app_path, 115200, timeout=5) as app:
            app.write(COMMAND)
            reply = app.read_until(ACK, size=4096)
            self.assertIn(ACK, reply)
            self.spin(lambda: ACK in b"".join(e["data"] for e in self.app.events.values() if e["direction"] == "RX"))
            self.assertEqual(self.app.engine.tx, len(COMMAND))
        self.app.toggle()
        self.spin(lambda: not self.app.active)


if __name__ == "__main__":
    unittest.main()
