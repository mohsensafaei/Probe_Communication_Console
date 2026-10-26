"""Small real-I/O checks run against the installed/frozen program itself."""
import contextlib
import os
import socket
import tempfile
import time
from pathlib import Path

from .engine import Engine


def wait_for(predicate, events=(), timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        errors = [e["message"] for e in events if e["kind"] == "error"]
        if errors:
            raise RuntimeError("; ".join(errors))
        value = predicate()
        if value:
            return value
        time.sleep(.01)
    raise RuntimeError("Transport self-test timed out")


@contextlib.contextmanager
def session(mode, **options):
    events = []
    engine = Engine(events.append)
    cfg = dict(mode=mode, host="127.0.0.1", port=9000,
               bind="127.0.0.1", listen_port=0, baud=115200)
    cfg.update(options)
    engine.start(cfg)
    try:
        ready = wait_for(lambda: next((e for e in events if e.get("state") == "Connected"), None), events)
        yield engine, events, ready
    finally:
        engine.stop()
        engine.join()
        if engine.thread.is_alive():
            raise RuntimeError("Transport self-test leaked a thread")


def received(events):
    return b"".join(e["data"] for e in events if e["kind"] == "data" and e["direction"] == "RX")


def expect_equal(actual, expected):
    if actual != expected:
        raise RuntimeError(f"Byte mismatch: expected {len(expected)}, got {len(actual)} bytes")


def self_test():
    import serial
    from serial.tools import list_ports
    # These URL handlers are imported dynamically by pySerial in frozen builds.
    from serial.urlhandler import protocol_loop, protocol_rfc2217, protocol_socket
    from .capture import load_capture
    from .terminal import TerminalModel
    list(list_ports.comports())
    payload = bytes(range(256))
    with session("USB / Serial", serial_port="loop://") as (engine, events, _):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "capture.jsonl"
            engine.record(path)
            engine.send(payload)
            wait_for(lambda: len(received(events)) == len(payload), events)
            expect_equal(received(events), payload)
            engine.record()
            expect_equal(b"".join(e["data"] for e in load_capture(path) if e["direction"] == "RX"), payload)
    print("PASS serial loopback, capture and URL handlers")
    with session("TCP Server") as (server, se, ready):
        server.echo = True
        with session("TCP Client", port=ready["address"][1]) as (client, ce, _):
            client.send(payload)
            wait_for(lambda: len(received(ce)) == len(payload), ce)
            expect_equal(received(ce), payload)
        with session("TCP Proxy", port=ready["address"][1]) as (_, events, ready):
            with socket.create_connection(ready["address"][:2], timeout=5) as app:
                app.sendall(payload)
                expect_equal(app.makefile("rb").read(len(payload)), payload)
    print("PASS TCP client, server and proxy")
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as app:
        app.bind(("127.0.0.1", 0))
        app.settimeout(5)
        with session("UDP", port=app.getsockname()[1]) as (engine, events, ready):
            engine.echo = True
            app.sendto(payload, ready["address"])
            expect_equal(app.recvfrom(4096)[0], payload)
    print("PASS UDP duplex")
    if os.name == "posix":
        import tty
        for mode in ("USB / Serial", "Serial Proxy", "Serial ↔ TCP"):
            master, slave = os.openpty()
            tty.setraw(slave)
            try:
                with session(mode, serial_port=os.ttyname(slave), app_port="Auto PTY") as (engine, events, ready):
                    if mode == "USB / Serial":
                        engine.send(payload)
                        wait_for(lambda: engine.tx == len(payload), events)
                        expect_equal(os.read(master, len(payload)), payload)
                        os.write(master, payload)
                        wait_for(lambda: len(received(events)) == len(payload), events)
                        expect_equal(received(events), payload)
                    elif mode == "Serial Proxy":
                        with serial.Serial(ready["app_path"], 115200, timeout=5) as app:
                            app.write(payload)
                            wait_for(lambda: engine.tx == len(payload), events)
                            expect_equal(os.read(master, len(payload)), payload)
                            os.write(master, payload)
                            expect_equal(app.read(len(payload)), payload)
                    else:
                        with socket.create_connection(ready["address"][:2], timeout=5) as app:
                            app.sendall(payload)
                            wait_for(lambda: engine.tx == len(payload), events)
                            expect_equal(os.read(master, len(payload)), payload)
                            os.write(master, payload)
                            expect_equal(app.makefile("rb").read(len(payload)), payload)
                print(f"PASS Linux PTY: {mode}")
            finally:
                os.close(master)
                os.close(slave)
    model = TerminalModel(20, 4)
    model.feed(b"\x1b[31mOK\x1b[0m")
    if model.screen.display[0].strip() != "OK" or model.screen.buffer[0][0].fg != "red":
        raise RuntimeError("ANSI terminal self-test failed")
    print("PASS ANSI terminal")
    from .simulation import DeviceModel, Exchange, Reply
    from .scenario import Step
    model = DeviceModel((Exchange(b"PING\r\n", (Reply(b"PONG\r\n", 2),)),))
    with session("Device Simulator", simulator_model=model) as (_, events, ready):
        with session("TCP Client", port=ready["address"][1]) as (engine, events, _):
            engine.start_scenario((Step("Ping", b"PING\r\n", 1, expect=b"PONG\r\n"),), cycles=3)
            done = wait_for(lambda: next((e for e in events if e.get("state") == "complete"), None), events)
            if done["checked"] != 3:
                raise RuntimeError("Scenario reply validation failed")
    if os.name == "posix":
        with session("Device Simulator", simulator_model=model, simulator_transport="Virtual serial (PTY)") as (_, events, ready):
            with serial.Serial(ready["app_path"], 115200, timeout=3) as app:
                app.write(b"PING\r\n")
                expect_equal(app.read(6), b"PONG\r\n")
    print("PASS device simulator (TCP; PTY on POSIX) and timed reply-checked sequences")
    from .protocol import json_value
    from .comparison import compare_bytes
    from .scenario import compile_steps
    if json_value(b'000019{"sessionId":"123"}',"sessionId")!="123":
        raise RuntimeError("Protocol Inspector JSON extraction failed")
    if not any(item.kind=="changed" for item in compare_bytes(b"AB",b"AC")):
        raise RuntimeError("Capture comparison failed")
    dynamic=DeviceModel((Exchange(b"SESSION?",(Reply(b'{"sessionId":"123"}'),)),
                         Exchange(b'{"sessionId":"123"}',(Reply(b"OK"),))))
    with session("Device Simulator",simulator_model=dynamic) as (_,events,ready):
        with session("TCP Client",port=ready["address"][1]) as (engine,events,_):
            steps=compile_steps([dict(name="Read session",text="SESSION?",delay_ms=0,
                                      flow=dict(extract=[dict(name="sid",source="JSON",selector="sessionId")])),
                                 dict(name="Use session",text='{"sessionId":${sid:json}}',delay_ms=0,expect="4F4B")])
            engine.start_scenario(steps)
            wait_for(lambda:any(event.get("state")=="complete" for event in events),events)
    print("PASS protocol interpretation, byte comparison and reply variables over TCP")
