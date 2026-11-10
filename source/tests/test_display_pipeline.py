import random
import subprocess
import sys
import threading
import unittest
from queue import Empty

from probe.codec import Framer
from probe.event_buffer import DisplayEventBuffer, event_cost
from probe.traffic_model import DisplayFraming, TrafficHistory


def event(data=b"A", **fields):
    return dict(kind="data", time=1.0, direction="RX", peer="device", data=data, **fields)


def drain(buffer):
    rows = []
    while True:
        try:
            rows.append(buffer.get_nowait())
        except Empty:
            return rows


class DisplayBufferTests(unittest.TestCase):
    def test_fifo_keeps_data_and_control_order(self):
        buffer = DisplayEventBuffer()
        rows = [event(), dict(kind="state", state="Connected"), event(b"B"), dict(kind="info", message="ok")]
        for row in rows:
            buffer.put_nowait(row)
        self.assertEqual(drain(buffer), rows)
        self.assertEqual(buffer.stats()["pending_bytes"], 0)

    def test_data_flood_cannot_evict_state_or_recording_error(self):
        buffer = DisplayEventBuffer(max_events=2)
        buffer.put_nowait(dict(kind="state", state="Disconnected"))
        buffer.put_nowait(dict(kind="recording_error", message="disk full"))
        for i in range(1000):
            buffer.put_nowait(event(str(i).encode()))
        rows = drain(buffer)
        self.assertEqual([r["kind"] for r in rows], ["state", "recording_error", "data", "data"])
        self.assertEqual([r["data"] for r in rows[2:]], [b"998", b"999"])
        self.assertTrue(rows[2]["_display_gap"])
        self.assertNotIn("_display_gap", rows[3])
        self.assertEqual(buffer.stats()["dropped"], 998)

    def test_oversize_gap_is_after_previously_queued_bytes(self):
        row = event()
        buffer = DisplayEventBuffer(max_bytes=event_cost(row) * 2)
        buffer.put_nowait(row)
        buffer.put_nowait(event(b"X" * 4096))
        buffer.put_nowait(event(b"B"))
        a, b = drain(buffer)
        self.assertNotIn("_display_gap", a)
        self.assertTrue(b["_display_gap"])
        self.assertNotIn("_display_gap", row)

    def test_byte_budget_includes_nested_hid_metadata(self):
        buffer = DisplayEventBuffer(max_bytes=4096)
        buffer.put_nowait(event(hid=dict(fields=[dict(field="X", value="123") for _ in range(100)])))
        self.assertTrue(buffer.empty())
        self.assertEqual(buffer.stats()["dropped"], 1)
        for _ in range(100):
            buffer.put_nowait(event(b"Z" * 1024))
            self.assertLessEqual(buffer.stats()["pending_bytes"], 4096)

    def test_control_only_flood_is_bounded_and_visible(self):
        buffer = DisplayEventBuffer(max_controls=3)
        for i in range(10):
            buffer.put_nowait(dict(kind="info", message=str(i)))
        self.assertEqual([r["message"] for r in drain(buffer)], ["7", "8", "9"])
        self.assertEqual(buffer.stats()["dropped_controls"], 7)

    def test_reset_statistics_does_not_hide_stream_gap(self):
        buffer = DisplayEventBuffer(max_events=1)
        buffer.put_nowait(event())
        buffer.put_nowait(event(b"B"))
        buffer.reset_stats()
        self.assertEqual(buffer.stats()["dropped"], 0)
        self.assertTrue(buffer.get_nowait()["_display_gap"])

    def test_multiple_producers_keep_accounting_and_per_producer_order(self):
        buffer = DisplayEventBuffer(max_events=4000)
        def produce(peer):
            for i in range(500):
                row = event(str(i).encode())
                row["peer"] = peer
                buffer.put_nowait(row)
        threads = [threading.Thread(target=produce, args=(str(i),)) for i in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        rows = drain(buffer)
        self.assertEqual(len(rows), 2000)
        for peer in map(str, range(4)):
            self.assertEqual([int(r["data"]) for r in rows if r["peer"] == peer], list(range(500)))
        self.assertEqual(buffer.stats()["pending_bytes"], 0)
        self.assertEqual(buffer.stats()["dropped"], 0)


class DisplayModelTests(unittest.TestCase):
    def test_modified_frames_split_and_join_original_bytes(self):
        framing = DisplayFraming(lambda: Framer('Fixed length', size=2))
        rows = list(framing.feed(event(b'ABCD', original_hex='61626364')))
        self.assertEqual([r['original_hex'] for r in rows], ['6162', '6364'])
        framing = DisplayFraming(lambda: Framer('Fixed length', size=4))
        self.assertEqual(list(framing.feed(event(b'AB', original_hex='6162', modified_by=['upper']))), [])
        row, = framing.feed(event(b'CD'))
        self.assertEqual(row['original_hex'], '61624344')
        self.assertEqual(row['modified_by'], ['upper'])
        row, = framing.feed(event(b'EFGH'))
        self.assertNotIn('original_hex', row)
        self.assertNotIn('_original', row)

    def test_original_bytes_survive_idle_tick_and_partial_flush(self):
        for mode in ('Idle gap', 'Delimiter', 'Fixed length'):
            framing = DisplayFraming(lambda: Framer(mode, size=4))
            list(framing.feed(event(b'AB', original_hex='6162')))
            rows = framing.tick(wall_time=2) if mode == 'Idle gap' else framing.flush()
            self.assertEqual(rows[0]['original_hex'], '6162')
            self.assertNotIn('_original', rows[0])

    def test_length_changing_plugins_keep_exact_chunk_provenance(self):
        framing = DisplayFraming(lambda: Framer('Fixed length', size=4))
        list(framing.feed(event(b'AB', original_hex='6162')))
        rows = list(framing.feed(event(b'CDE', original_hex='63')))
        self.assertEqual([(r['data'], r['original_hex']) for r in rows], [(b'AB', '6162'), (b'CDE', '63')])
        self.assertTrue(all(r['display_partial'] for r in rows))
        self.assertFalse(framing.streams)
        blocked, = framing.feed(event(b'', original_hex='6465', plugin_error='blocked'))
        self.assertEqual(blocked['original_hex'], '6465')

    def test_framing_separates_sessions_and_proxy_clients(self):
        for field in ('session', 'client_peer'):
            framing = DisplayFraming(lambda: Framer('Fixed length', size=4))
            self.assertEqual(list(framing.feed(event(b'AB', **{field:'one'}))), [])
            self.assertEqual(list(framing.feed(event(b'CD', **{field:'two'}))), [])
            self.assertEqual([r['data'] for r in framing.flush()], [b'AB', b'CD'])

    def test_headless_imports(self):
        subprocess.run([sys.executable, "-c", "import sys; import probe.event_buffer, probe.traffic_model; assert 'tkinter' not in sys.modules"], check=True)

    def test_history_batches_match_independent_rolling_reference(self):
        rng = random.Random(53)
        history = TrafficHistory(7, 40)
        expected = []
        count = evicted = 0
        for _ in range(100):
            before = {key for key, _ in expected}
            for_batch = [event(rng.randbytes(rng.randrange(0, 55))) for _ in range(rng.randrange(1, 20))]
            for row in for_batch:
                count += 1
                expected.append((str(count), row))
                while len(expected) > 7 or sum(len(r["data"]) for _, r in expected) > 40:
                    expected.pop(0)
                    evicted += 1
            change = history.extend(for_batch)
            self.assertEqual([(key,{k:v for k,v in row.items() if k not in ('event_id','event_version')}) for key,row in history.events.items()], expected)
            self.assertEqual(change.added, tuple(key for key, _ in expected if key not in before))
            self.assertEqual(set(change.removed), before - set(history.events))
            self.assertEqual(history.retained_bytes, sum(len(r["data"]) for _, r in expected))
            self.assertEqual(history.evicted, evicted)

    def test_oversize_row_never_survives_retention(self):
        history = TrafficHistory(2, 4)
        history.extend([event()])
        change = history.extend([event(b"TOO LARGE")])
        self.assertEqual(change.added, ())
        self.assertEqual(change.removed, ("1",))
        self.assertEqual(history.retained_bytes, 0)

    def test_many_small_frames_render_only_survivors(self):
        framing = DisplayFraming(lambda: Framer("Fixed length", size=1))
        history = TrafficHistory()
        change = history.extend(framing.feed(event(bytes(range(256)) * 256)))
        self.assertEqual(len(change.added), 2000)
        self.assertEqual(history.evicted, 65536 - 2000)
        self.assertEqual(b"".join(r["data"] for r in history.events.values()), (bytes(range(256)) * 256)[-2000:])

    def test_peer_state_is_bounded_and_eviction_marks_partial_bytes(self):
        framing = DisplayFraming(lambda: Framer("Fixed length", size=4), max_streams=2)
        rows = []
        for peer in range(10):
            row = event(bytes([peer])); row["peer"] = str(peer)
            rows.extend(framing.feed(row))
            self.assertLessEqual(len(framing.streams), 2)
        rows.extend(framing.flush())
        self.assertEqual(b"".join(r["data"] for r in rows), bytes(range(10)))
        self.assertTrue(all(r["display_partial"] for r in rows))
        self.assertFalse(framing.streams)

    def test_chunks_and_hid_do_not_retain_peer_state(self):
        framing = DisplayFraming(lambda: Framer())
        row = event()
        self.assertEqual(list(framing.feed(row)), [row])
        self.assertFalse(framing.streams)
        framing = DisplayFraming(lambda: Framer("Fixed length", size=4))
        hid = event(hid={"report_type": "Input"})
        self.assertEqual(list(framing.feed(hid)), [hid])
        self.assertFalse(framing.streams)

    def test_idle_gap_uses_monotonic_acquisition_despite_wall_clock_jump(self):
        framing = DisplayFraming(lambda: Framer("Idle gap", idle=.05))
        first = event(b"A", monotonic_ns=1_000_000_000)
        second = event(b"B", monotonic_ns=1_010_000_000); second["time"] = 5000
        self.assertEqual(list(framing.feed(first)), [])
        self.assertEqual(list(framing.feed(second)), [])
        self.assertEqual(framing.tick(9999, 1.04), [])
        self.assertEqual([r["data"] for r in framing.tick(9999, 1.07)], [b"AB"])

    def test_gap_flush_never_fabricates_contiguous_message(self):
        framing = DisplayFraming(lambda: Framer("Fixed length", size=4))
        self.assertEqual(list(framing.feed(event(b"AB"))), [])
        rows = framing.flush("display data lost")
        self.assertEqual(list(framing.feed(event(b"CD"))), [])
        rows.extend(framing.flush())
        self.assertEqual([r["data"] for r in rows], [b"AB", b"CD"])
        self.assertEqual(rows[0]["display_reason"], "display data lost")

    def test_pending_metadata_does_not_hold_original_large_read(self):
        framing = DisplayFraming(lambda: Framer("Fixed length", size=1024))
        list(framing.feed(event(b"X" * 65537)))
        framer, metadata, _ = next(iter(framing.streams.values()))
        self.assertEqual(framer.buffer, b"X")
        self.assertNotIn("data", metadata)

    def test_capacity_flush_is_labelled_as_partial(self):
        framing = DisplayFraming(lambda: Framer("Delimiter", delimiter=b"\n"))
        rows = list(framing.feed(event(b"X" * 65536)))
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0]["display_partial"])
        self.assertEqual(rows[0]["display_reason"], "frame buffer limit")


if __name__ == "__main__":
    unittest.main()
