"""Device-less simulation and hardware-test runner integration regressions."""
import json
import os
from pathlib import Path
import socket
import tempfile
import time
import unittest

from probe.diagnostics import session, received, wait_for
from probe.scenario import Step, compile_steps, sequence_from_dict
from probe.simulation import (DeviceModel, Exchange, Reply, RequestMatcher,
                              compile_capture, model_from_dict, model_to_dict)


def model(delay=0):
    return DeviceModel((Exchange(b"PING\r\n", (Reply(b"PONG\r\n", delay),)),
                        Exchange(b"BUY\0\xff", (Reply(b"OK\0\xff", delay),))))


def exchange(sock, request, size):
    sock.sendall(request)
    data = bytearray()
    while len(data) < size:
        chunk = sock.recv(size-len(data))
        if not chunk: raise AssertionError("Simulator closed before delivering the reply")
        data.extend(chunk)
    return bytes(data)


class ModelTests(unittest.TestCase):
    def rows(self):
        return [dict(kind="data", direction=d, data=b, time=t, peer="device") for d, b, t in
                (("TX", b"PI", 1), ("TX", b"NG\r\n", 1.01), ("RX", b"PO", 1.02),
                 ("RX", b"NG\r\n", 1.04), ("TX", b"BUY\0\xff", 1.1), ("RX", b"OK\0\xff", 1.2))]

    def test_capture_compilation_preserves_bytes_and_timing(self):
        compiled = compile_capture(self.rows())
        self.assertEqual(compiled.exchanges[0].request, b"PING\r\n")
        self.assertEqual([r.data for r in compiled.exchanges[0].replies], [b"PO", b"NG\r\n"])
        self.assertAlmostEqual(compiled.exchanges[0].replies[0].delay_ms, 10)
        self.assertAlmostEqual(compiled.exchanges[0].replies[1].delay_ms, 20)
        self.assertEqual(model_from_dict(json.loads(json.dumps(model_to_dict(compiled)))), compiled)

    def test_peer_selection_legacy_proxy_and_startup_chatter(self):
        rows = self.rows()
        for row in rows:
            if row["direction"] == "TX": row["peer"] = "App → device"
        rows.insert(0, dict(kind="data", direction="RX", data=b"BOOT", time=0, peer="device"))
        self.assertEqual(compile_capture(rows).ignored_startup_bytes, 4)
        rows.append(dict(kind="data", direction="RX", data=b"other", time=2, peer="other"))
        with self.assertRaisesRegex(ValueError, "Choose one"): compile_capture(rows)
        self.assertEqual(len(compile_capture(self.rows(), "device").exchanges), 2)

    def test_inverse_direction_and_missing_replies(self):
        rows = self.rows()
        for row in rows: row["direction"] = "RX" if row["direction"] == "TX" else "TX"
        self.assertEqual(compile_capture(rows, request_direction="RX").exchanges[0].request, b"PING\r\n")
        with self.assertRaises(ValueError): compile_capture([])
        with self.assertRaises(ValueError): compile_capture(self.rows()[:2])

    def test_split_coalesced_binary_requests_and_bounded_resync(self):
        matcher = RequestMatcher(model())
        self.assertEqual(matcher.feed(b"garbagePI"), [])
        matches = matcher.feed(b"NG\r\nBUY\0\xffPING\r\n")
        self.assertEqual([m.request for m in matches], [b"PING\r\n", b"BUY\0\xff", b"PING\r\n"])
        self.assertEqual(matcher.discarded, 7)
        matcher.feed(b"x"*100000)
        self.assertLessEqual(len(matcher.buffer), 6)

    def test_stateful_replies_exhaustion_and_unordered_ambiguity(self):
        stateful = DeviceModel((Exchange(b"A", (Reply(b"1"),)), Exchange(b"A", (Reply(b"2"),))))
        matcher = RequestMatcher(stateful, repeat=False)
        self.assertEqual([m.replies[0].data for m in matcher.feed(b"AAA")], [b"1", b"2"])
        with self.assertRaisesRegex(ValueError, "different replies"): RequestMatcher(stateful, ordered=False)
        with self.assertRaisesRegex(ValueError, "prefix"):
            RequestMatcher(DeviceModel((Exchange(b"A", (Reply(b"1"),)), Exchange(b"AB", (Reply(b"2"),)))), ordered=False)
        self.assertEqual(len(RequestMatcher(model(), ordered=False).feed(b"BUY\0\xffBUY\0\xffPING\r\n")), 3)

    def test_model_rejects_bad_bytes_or_timing(self):
        for request, delay in (("", 0), ("GG", 0), ("41", float("nan")), ("41", -1), ("41", 3600001)):
            with self.assertRaises(ValueError):
                model_from_dict(dict(format="probe-device", version=1,
                                     exchanges=[dict(request=request, replies=[dict(hex="42", delay_ms=delay)])]))

    def test_sequence_validation_and_legacy_import(self):
        rows = [dict(name="Buy", text="00 FF", send_mode="Hex", delay_ms="3", repeat="2", expect="06", timeout_ms="25")]
        self.assertEqual(compile_steps(rows)[0], Step("Buy", b"\0\xff", 3, 2, b"\x06", 25))
        self.assertEqual(sequence_from_dict(rows), (rows, 1))
        self.assertEqual(sequence_from_dict(dict(format="probe-sequence", version=1, cycles=0, steps=rows)), (rows, 0))
        for key, value in (("delay_ms", "-1"), ("delay_ms", "1.5"), ("repeat", "0"), ("timeout_ms", "0"), ("expect", "GG")):
            with self.assertRaises(ValueError): compile_steps([{**rows[0], key: value}])
        with self.assertRaises(ValueError): compile_steps([])


class TestLabTransportTests(unittest.TestCase):
    def test_tcp_clients_have_independent_conversations(self):
        with session("Device Simulator", simulator_model=model()) as (engine, events, ready):
            with socket.create_connection(ready["address"][:2], timeout=3) as a, socket.create_connection(ready["address"][:2], timeout=3) as b:
                a.sendall(b"junkPI")
                self.assertEqual(exchange(a, b"NG\r\nBUY\0\xff", 10), b"PONG\r\nOK\0\xff")
                self.assertEqual(exchange(b, b"PING\r\n", 6), b"PONG\r\n")
                self.assertEqual(exchange(a, b"PING\r\n", 6), b"PONG\r\n")
                self.assertEqual(engine.serials, [])
                self.assertTrue(any(e.get("state") == "unmatched" for e in events))

    @unittest.skipIf(os.name != "posix", "Requires Linux/POSIX PTY")
    def test_virtual_serial_without_physical_hardware(self):
        import serial
        with session("Device Simulator", simulator_model=model(), simulator_transport="Virtual serial (PTY)") as (engine, events, ready):
            path = ready["app_path"]
            with serial.Serial(path, 115200, timeout=2) as app:
                app.write(b"PING\r\nBUY\0\xff")
                self.assertEqual(app.read(10), b"PONG\r\nOK\0\xff")
                self.assertEqual(engine.serials, [])
        self.assertFalse(Path(path).exists())

    def test_delay_reset_and_stop_pending_replies(self):
        delayed = DeviceModel((Exchange(b"A", (Reply(b"1", 20), Reply(b"2", 30))),))
        with session("Device Simulator", simulator_model=delayed, simulator_repeat=False) as (engine, events, ready):
            with socket.create_connection(ready["address"][:2], timeout=2) as app:
                started = time.monotonic()
                self.assertEqual(exchange(app, b"A", 2), b"12")
                self.assertGreaterEqual(time.monotonic()-started, .04)
                engine.reset_simulator()
                wait_for(lambda: any(e.get("state") == "ready" for e in events), events)
                self.assertEqual(exchange(app, b"A", 2), b"12")
        with session("Device Simulator", simulator_model=model(10000)) as (engine, events, ready):
            with socket.create_connection(ready["address"][:2], timeout=2) as app:
                app.sendall(b"PING\r\n")
                wait_for(lambda: engine.tx > 0, events)
                started = time.monotonic()
                engine.stop(); engine.join()
                self.assertLess(time.monotonic()-started, 1)
                self.assertEqual(engine.rx, 0)

    def test_capture_works_after_original_device_stops(self):
        with tempfile.TemporaryDirectory() as directory:
            from probe.capture import load_capture
            path = Path(directory)/"recording.jsonl"
            with session("USB / Serial", serial_port="loop://") as (engine, events, _):
                engine.record(path); engine.send(b"QUERY\0\xff")
                wait_for(lambda: received(events) == b"QUERY\0\xff", events)
                engine.record()
            compiled = compile_capture(load_capture(path))
            with session("Device Simulator", simulator_model=compiled) as (_, events, ready):
                with socket.create_connection(ready["address"][:2], timeout=3) as app:
                    self.assertEqual(exchange(app, b"QUERY\0\xff", 7), b"QUERY\0\xff")

    def test_sequence_timing_repeats_and_expected_replies(self):
        steps = (Step("A", b"A", 10, expect=b"A"), Step("B", b"B", 5, repeat=2, expect=b"B"))
        with session("USB / Serial", serial_port="loop://") as (engine, events, _):
            started = time.monotonic()
            engine.start_scenario(steps, cycles=2)
            done = wait_for(lambda: next((e for e in events if e.get("state") == "complete"), None), events)
            self.assertEqual(received(events), b"ABBABB")
            self.assertEqual((done["sent"], done["checked"], done["cycle"]), (6, 6, 2))
            self.assertGreaterEqual(time.monotonic()-started, .04)
            self.assertFalse(engine.observers)

    def test_sequence_failure_and_infinite_loop_cancel(self):
        with session("USB / Serial", serial_port="loop://") as (engine, events, _):
            engine.start_scenario((Step("Missing reply", b"A", expect=b"NOT_A", timeout_ms=40),))
            failure = wait_for(lambda: next((e for e in events if e.get("state") == "failed"), None), events)
            self.assertIn("40 ms", failure["message"])
            engine.start_scenario((Step("Loop", b"B", 2),), cycles=0)
            wait_for(lambda: engine.tx > 5, events)
            engine.stop_scenario()
            wait_for(lambda: any(e.get("state") == "stopped" for e in events), events)
            count = engine.tx
            time.sleep(.04)
            self.assertEqual(engine.tx, count)
            self.assertFalse(engine.observers)

    def test_sequence_over_tcp_checks_real_simulated_reply(self):
        with session("Device Simulator", simulator_model=model()) as (_, events, ready):
            with session("TCP Client", port=ready["address"][1]) as (engine, traffic, _):
                engine.start_scenario((Step("Ping", b"PING\r\n", 1, expect=b"PONG\r\n"),
                                       Step("Buy", b"BUY\0\xff", 3, expect=b"OK\0\xff")), cycles=3)
                done = wait_for(lambda: next((e for e in traffic if e.get("state") == "complete"), None), traffic)
                self.assertEqual(done["checked"], 6)
                self.assertEqual(done["sent"], 6)


class ScenarioEdgeTests(unittest.TestCase):
    def test_stop_before_scheduled_runner_starts(self):
        with session("USB / Serial", serial_port="loop://") as (engine, events, _):
            async def start_then_cancel():
                engine.start_scenario((Step("Cancel before first send", b"NO"),), cycles=0)
                engine.stop_scenario()
                engine.event("info", message="queued cancellation")
            engine.schedule(start_then_cancel())
            wait_for(lambda: any(e.get("message")=="queued cancellation" for e in events), events)
            time.sleep(.03)
            self.assertEqual(engine.tx,0)
            self.assertIsNone(engine.scenario_task)

    def test_sequence_udp_waits_for_actual_sender_reply(self):
        import threading
        with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as device:
            device.bind(("127.0.0.1",0));device.settimeout(2)
            def echo():
                data,address=device.recvfrom(100)
                device.sendto(b"REPLY:"+data,address)
            worker=threading.Thread(target=echo);worker.start()
            with session("UDP",port=device.getsockname()[1]) as (engine,events,_):
                engine.start_scenario((Step("UDP request",b"HELLO",expect=b"REPLY:HELLO"),))
                done=wait_for(lambda:next((e for e in events if e.get("state")=="complete"),None),events)
                self.assertEqual(done["checked"],1)
            worker.join(2);self.assertFalse(worker.is_alive())

    def test_reset_cancels_delayed_simulated_reply(self):
        delayed=DeviceModel((Exchange(b"A",(Reply(b"B",80),)),))
        with session("Device Simulator",simulator_model=delayed) as (engine,events,ready):
            with socket.create_connection(ready["address"][:2],timeout=2) as app:
                app.sendall(b"A")
                wait_for(lambda:engine.tx>0,events)
                engine.reset_simulator()
                wait_for(lambda:any(e.get("state")=="ready" for e in events),events)
                self.assertEqual(exchange(app,b"A",1),b"B")
                app.settimeout(.12)
                with self.assertRaises(socket.timeout):app.recv(1)

    def test_long_repeated_sequence_preserves_order(self):
        with session("Device Simulator",simulator_model=model()) as (_,events,ready):
            with session("TCP Client",port=ready["address"][1]) as (engine,traffic,_):
                engine.start_scenario((Step("Ping",b"PING\r\n",expect=b"PONG\r\n"),
                                       Step("Buy",b"BUY\0\xff",expect=b"OK\0\xff")),cycles=200)
                done=wait_for(lambda:next((e for e in traffic if e.get("state")=="complete"),None),traffic,timeout=10)
                self.assertEqual(done["checked"],400)
                self.assertEqual(done["sent"],400)

    def test_serial_tcp_reply_checks_on_both_injection_sides(self):
        with session("Serial ↔ TCP", serial_port="loop://") as (engine,events,ready):
            with socket.create_connection(ready["address"][:2],timeout=3) as app:
                wait_for(lambda:len(engine.clients)==1,events)
                engine.start_scenario((Step("Physical device",b"DEVICE",expect=b"DEVICE"),))
                self.assertEqual(app.recv(6),b"DEVICE")
                wait_for(lambda:any(e.get("state")=="complete" for e in events),events)
                events.clear()
                engine.start_scenario((Step("Downstream app",b"PING",expect=b"ACK"),),side="App / downstream")
                self.assertEqual(app.recv(4),b"PING")
                app.sendall(b"ACK")
                done=wait_for(lambda:next((e for e in events if e.get("state")=="complete"),None),events)
                self.assertEqual(done["checked"],1)
                self.assertEqual(app.recv(3),b"ACK")

    def test_fast_full_duplex_serial_reply_records_tx_first(self):
        payload=bytes(range(256))*32
        with tempfile.TemporaryDirectory() as directory:
            from probe.capture import load_capture
            path=Path(directory)/"fast.jsonl"
            with session("USB / Serial",serial_port="loop://") as (engine,events,_):
                engine.record(path)
                engine.send(payload)
                wait_for(lambda:len(received(events))==len(payload),events)
                engine.record()
                rows=load_capture(path)
                self.assertEqual(rows[0]["direction"],"TX")
                self.assertEqual(received(events),payload)
                compiled=compile_capture(rows)
                self.assertEqual(compiled.exchanges[0].request,payload)
                self.assertEqual(b"".join(r.data for r in compiled.exchanges[0].replies),payload)
