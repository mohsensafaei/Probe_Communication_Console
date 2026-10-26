"""Reply-gated sequences: real transport ordering, routing, timeout and Stop."""
import socket
import time
import unittest
from types import SimpleNamespace

from probe.diagnostics import session, received, wait_for
from probe.scenario import Step, compile_steps, run_scenario, sequence_from_dict


class ReplySequenceTests(unittest.TestCase):
    def test_reply_flag_round_trip_and_validation(self):
        row = dict(text="00 FF", send_mode="Hex", delay_ms=0, wait_for_reply=True, timeout_ms=500)
        document = dict(format="probe-sequence", version=2, steps=[row])
        rows, cycles = sequence_from_dict(document)
        self.assertEqual((compile_steps(rows)[0].wait_for_reply, cycles), (True, 1))
        self.assertFalse(compile_steps([dict(text="legacy")])[0].wait_for_reply)
        for invalid in ("false", "true", 1, None):
            with self.assertRaisesRegex(ValueError, "true or false"):
                compile_steps([{**row, "wait_for_reply": invalid}])

    def test_only_selected_peer_reply_releases_next_send(self):
        with session("TCP Server") as (engine, events, ready):
            with socket.create_connection(ready["address"][:2], timeout=2) as a, \
                 socket.create_connection(ready["address"][:2], timeout=2) as b:
                wait_for(lambda: len(engine.clients) == 2, events)
                target = next(peer for peer in engine.clients if peer.endswith(f":{a.getsockname()[1]}"))
                steps = (Step("First", b"A", wait_for_reply=True), Step("Second", b"B", wait_for_reply=True))
                with self.assertRaisesRegex(ValueError, "Select one client"):
                    engine.start_scenario(steps)
                # Startup chatter, the outgoing A and a different client's RX
                # must not count as A's response.
                a.sendall(b"old reply")
                wait_for(lambda: engine.rx >= 9, events)
                engine.start_scenario(steps, target=target)
                self.assertEqual(a.recv(1), b"A")
                b.sendall(b"unrelated reply")
                wait_for(lambda: engine.rx >= 24, events)
                a.settimeout(.05)
                with self.assertRaises(socket.timeout):a.recv(1)
                a.settimeout(2);a.sendall(b"ACK")
                self.assertEqual(a.recv(1), b"B")
                a.sendall(b"DONE")
                done = wait_for(lambda: next((e for e in events if e.get("state") == "complete"), None), events)
                self.assertEqual((done["sent"], done["checked"]), (2, 2))
                self.assertFalse(engine.observers)

    def test_timeout_and_stop_never_send_the_following_message(self):
        with session("TCP Server") as (engine, events, ready):
            with socket.create_connection(ready["address"][:2], timeout=2) as app:
                wait_for(lambda: len(engine.clients) == 1, events)
                engine.start_scenario((Step("Timeout", b"A", wait_for_reply=True, timeout_ms=70), Step("Never", b"B")))
                self.assertEqual(app.recv(1), b"A")
                failed = wait_for(lambda: next((e for e in events if e.get("state") == "failed"), None), events)
                self.assertIn("70 ms", failed["message"])
                self.assertEqual(engine.tx, 1)
                self.assertFalse(engine.observers)
                engine.start_scenario((Step("Long wait", b"C", wait_for_reply=True, timeout_ms=3600000), Step("Never", b"D")))
                self.assertEqual(app.recv(1), b"C")
                started = time.perf_counter();engine.stop_scenario()
                wait_for(lambda: any(e.get("state") == "stopped" for e in events), events)
                self.assertLess(time.perf_counter()-started, .5)
                self.assertEqual(engine.tx, 2)
                self.assertFalse(engine.observers)

    def test_serial_any_reply_repeats_and_cycles(self):
        with session("USB / Serial", serial_port="loop://") as (engine, events, _):
            engine.start_scenario((Step("Binary", b"\0\xff", repeat=2, wait_for_reply=True),), cycles=3)
            done = wait_for(lambda: next((e for e in events if e.get("state") == "complete"), None), events)
            self.assertEqual(received(events), b"\0\xff" * 6)
            self.assertEqual((done["sent"], done["checked"]), (6, 6))

    def test_serial_bridge_any_reply_on_both_injection_sides(self):
        with session("Serial ↔ TCP", serial_port="loop://") as (engine, events, ready):
            with socket.create_connection(ready["address"][:2], timeout=2) as app:
                wait_for(lambda: len(engine.clients) == 1, events)
                engine.start_scenario((Step("Device", b"DEVICE", wait_for_reply=True),))
                wait_for(lambda: any(e.get("state") == "complete" for e in events), events)
                self.assertEqual(app.recv(6), b"DEVICE")
                events.clear()
                engine.start_scenario((Step("App", b"PING", wait_for_reply=True),), side="App / downstream")
                self.assertEqual(app.recv(4), b"PING")
                app.sendall(b"ACK")
                done = wait_for(lambda: next((e for e in events if e.get("state") == "complete"), None), events)
                self.assertEqual(done["checked"], 1)


class ImmediateReplyTests(unittest.IsolatedAsyncioTestCase):
    async def test_observer_is_armed_before_send_and_expected_bytes_still_match(self):
        observers, progress = set(), []
        def event(kind, **fields):
            if kind == "data":
                for observe in tuple(observers):observe(fields)
            else:progress.append(fields)
        sent = []
        async def send(payload, target, side):
            sent.append(payload)
            for data in (b"", b"noise", b"O", b"K"):
                event("data", direction="RX", peer=target, data=data)
            return True
        engine = SimpleNamespace(observers=observers, cfg={"mode":"TCP Client"}, _send=send, event=event)
        await run_scenario(engine, (Step("Immediate", b"Q", expect=b"OK", wait_for_reply=True),), 1, "device", "Device / upstream")
        self.assertEqual(sent, [b"Q"])
        self.assertEqual(progress[-1]["state"], "complete")
        self.assertEqual(progress[-1]["checked"], 1)
        self.assertFalse(observers)

    async def test_empty_incoming_data_does_not_release_next_send(self):
        observers, progress, sent = set(), [], []
        def event(kind, **fields):
            if kind == "data":
                for observe in tuple(observers):observe(fields)
            else:progress.append(fields)
        async def send(payload, target, side):
            sent.append(payload)
            event("data", direction="RX", peer=target, data=b"")
            return True
        engine = SimpleNamespace(observers=observers, cfg={"mode":"TCP Client"}, _send=send, event=event)
        await run_scenario(engine, (Step("Empty", b"A", wait_for_reply=True, timeout_ms=20), Step("Never", b"B")), 1, "device", "Device / upstream")
        self.assertEqual(sent, [b"A"])
        self.assertEqual(progress[-1]["state"], "failed")
        self.assertFalse(observers)
