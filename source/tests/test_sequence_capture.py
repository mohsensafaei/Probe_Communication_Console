"""Captured provenance must never change payload bytes or select a destination."""
import unittest
from probe.scenario import compile_steps, steps_from_capture


class CapturedSequenceTests(unittest.TestCase):
    def rows(self):
        return [dict(direction=d, data=data, time=t, peer='COM34') for d, data, t in
                [('TX', b'COMMAND\0\xff', 1), ('RX', bytes(range(256)), 1.2),
                 ('RX', b'\x00REPLY\xff', 1.5), ('TX', b'NEXT', 2)]]

    def test_rx_and_tx_copy_exact_bytes_and_uniform_timing(self):
        for direction in ('RX', 'TX'):
            rows = [r for r in self.rows() if r['direction'] == direction]
            result = steps_from_capture(rows, 100)
            self.assertEqual([s.payload for s in compile_steps(result)], [r['data'] for r in rows])
            self.assertEqual([s.delay_ms for s in compile_steps(result)], [100, 100])
            self.assertEqual([r['source_direction'] for r in result], [direction, direction])
            self.assertTrue(all(not s.expect for s in compile_steps(result)))
            self.assertNotIn('side', result[0])
            self.assertEqual(rows, [r for r in self.rows() if r['direction'] == direction])

    def test_recorded_timing_is_explicit_and_uses_selected_record_gaps(self):
        result = steps_from_capture(self.rows()[1:3], 100, recorded_timing=True)
        self.assertEqual([s.delay_ms for s in compile_steps(result)], [300, 100])
        result = steps_from_capture([self.rows()[0], self.rows()[3]], 50, recorded_timing=True)
        self.assertEqual([s.delay_ms for s in compile_steps(result)], [1000, 50])

    def test_invalid_captures_and_bounds(self):
        for rows in ([], self.rows()*251, [dict(direction='RX', data='text')],
                     [dict(direction='RX', data=b'')], [dict(direction='XX', data=b'A')],
                     [dict(direction='RX', data=b'A'*(8*1024*1024+1))]):
            with self.assertRaises(ValueError):steps_from_capture(rows)
        for interval in (-1, 1.5, True, 3600001):
            with self.assertRaises(ValueError):steps_from_capture(self.rows(), interval)
        for gap in (float('nan'), float('inf'), 3601):
            rows = [dict(direction='RX', data=b'A', time=0), dict(direction='RX', data=b'B', time=gap)]
            with self.assertRaises(ValueError):steps_from_capture(rows, recorded_timing=True)
