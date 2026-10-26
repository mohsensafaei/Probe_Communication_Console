import unittest

from probe.plot_ui import NumericSamples


class NumericSamplesTests(unittest.TestCase):
    def test_fragmented_csv_and_peers_never_share_a_partial_line(self):
        samples=NumericSamples();samples.feed("a",b"1,2");samples.feed("b",b"3,4\n")
        self.assertEqual(samples.first,"b")
        self.assertFalse(samples.peers["a"]["rows"])
        samples.feed("a",b"\r\n5;6\n")
        self.assertEqual(list(samples.peers["a"]["rows"]),[(1,2),(5,6)])
        self.assertEqual(list(samples.peers["b"]["rows"]),[(3,4)])

    def test_non_numeric_binary_non_finite_and_long_lines_are_ignored(self):
        samples=NumericSamples();samples.feed("a",b'{"value":12}\n\0\xff\nNaN\n1e999\n1,2,3,4,5\n')
        self.assertFalse(samples.peers["a"]["rows"])
        samples.feed("a",b"X"*2000);samples.feed("a",b"123\n7\n")
        self.assertEqual(list(samples.peers["a"]["rows"]),[(7,)])

    def test_samples_peers_and_unfinished_lines_are_bounded(self):
        samples=NumericSamples()
        for i in range(20):samples.feed(str(i),b"0\n"*350+b"1"*5000)
        self.assertEqual(len(samples.peers),16)
        self.assertTrue(all(len(state["rows"])==300 and len(state["tail"])<=1024 for state in samples.peers.values()))
