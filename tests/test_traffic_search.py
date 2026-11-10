import unittest
from probe.traffic.search import MODES, TrafficSearch


def event(data,peer='COM34'):
    return dict(data=data,peer=peer)


class TrafficSearchTests(unittest.TestCase):
    def test_hex_is_byte_aligned_and_validated(self):
        for value in ('A4 FF 00','A4FF00','0xA4,0xFF,0x00'):
            matcher=TrafficSearch(value,'Hex bytes')
            self.assertFalse(matcher.error);self.assertTrue(matcher.matches(event(b'\x01\xA4\xFF\0\x02')))
        self.assertFalse(TrafficSearch('AB','Hex bytes').matches(event(b'\x0A\xBC')))
        for value in ('A','GG','0x',','):
            matcher=TrafficSearch(value,'Hex bytes');self.assertTrue(matcher.error);self.assertFalse(matcher.matches(event(b'\xAA')))
        self.assertTrue(TrafficSearch('hex:A4 FF').matches(event(b'\xA4\xff')))

    def test_text_values_unicode_and_full_payload(self):
        self.assertTrue(TrafficSearch('approved').matches(event(b'X'*9000+b'APPROVED')))
        self.assertTrue(TrafficSearch('COM34').matches(event(b'x')))
        self.assertTrue(TrafficSearch('سلام').matches(event(b'{"message":"\\u0633\\u0644\\u0627\\u0645"}')))
        self.assertTrue(TrafficSearch('STRASSE').matches(event('Straße'.encode())))
        self.assertFalse(TrafficSearch('missing').matches(event(b'APPROVED')))

    def test_only_text_and_hex_modes_and_idle_queries(self):
        self.assertEqual(MODES,('Text','Hex bytes'))
        for mode in MODES:
            idle=TrafficSearch('',mode)
            self.assertFalse(idle.error);self.assertTrue(idle.matches(event(b'\xff not JSON')))
        self.assertTrue(TrafficSearch('100','Text').matches(event(b'{"data":{"amount":"10000"}}')))
        self.assertTrue(TrafficSearch('1','JSON field').error)
        self.assertTrue(TrafficSearch('').matches(event(b'any bytes\0')))
        self.assertTrue(TrafficSearch('A'*4097).error)
