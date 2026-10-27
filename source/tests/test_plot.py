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

class CustomSamplesTests(unittest.TestCase):
    def model(self,**config):
        defaults=dict(kind="JSON field",field="data.temp",framing="JSON messages")
        defaults.update(config)
        return NumericSamples(defaults)

    def test_json_split_coalesced_prefix_and_missing_fields(self):
        m=self.model();m.feed("a",b'{"data":{"te');m.feed("b",b'{"data":{"temp":7}}')
        m.feed("a",b'mp":25.5}}{"data":{"temp":26}}{"data":{"other":1}}')
        self.assertEqual(list(m.peers['a']['rows']),[(25.5,),(26,)])
        self.assertEqual(list(m.peers['b']['rows']),[(7,)])
        m.feed('a',b'000020{"data":{"temp":27}}')
        self.assertEqual(m.peers['a']['rows'][-1],(27,))

    def test_columns_named_values_and_binary_frames(self):
        m=self.model(kind="Delimited column",column=2,separator=";",framing="LF lines")
        m.feed('a',b'12;3.3;99\n4;5');m.feed('a',b';6\n')
        self.assertEqual(list(m.peers['a']['rows']),[(3.3,),(5,)])
        m=self.model(kind="Named value",field="temp",framing="LF lines")
        m.feed('a',b'voltage=3.3 temp: -2.5e1\nother=22\n')
        self.assertEqual(list(m.peers['a']['rows']),[(-25,)])
        m=self.model(kind="Bytes",framing="Fixed bytes",size=4,offset=1,type="Unsigned 16",endian="Little")
        m.feed('a',b'\xAA\x34');m.feed('a',b'\x12\xBB\xAA\x78\x56\xBB')
        self.assertEqual(list(m.peers['a']['rows']),[(0x1234,),(0x5678,)])

    def test_invalid_non_numeric_and_bounded_custom_data(self):
        from probe.plot_extract import validate
        for c in (dict(kind="Bytes",framing="Fixed bytes",size=2,offset=1,type="Unsigned 16"),dict(kind="JSON field",framing="JSON messages",size=0)):
            with self.assertRaises(ValueError):validate(c)
        m=self.model();m.feed('a',b'{"data":{"temp":true}}{"data":{"temp":"NaN"}}')
        self.assertFalse(m.peers['a']['rows'])
        m.feed('a',b'{'*70000);self.assertLessEqual(len(m.peers['a']['tail']),65536)
