import unittest
from probe.traffic_search import TrafficSearch


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

    def test_json_field_path_value_and_exists(self):
        wire=event(b'000075{"data":{"amount":"10000","other":"20000","items":[{"id":3}],"a.b":7}}')
        self.assertTrue(TrafficSearch('100','JSON field','data.amount').matches(wire))
        self.assertFalse(TrafficSearch('20000','JSON field','data.amount').matches(wire))
        self.assertTrue(TrafficSearch('3','JSON field','data.items[0].id').matches(wire))
        self.assertTrue(TrafficSearch('7','JSON field','/data/a.b').matches(wire))
        self.assertTrue(TrafficSearch('','JSON field','data.amount').matches(wire))
        self.assertFalse(TrafficSearch('','JSON field','data.unknown').matches(wire))
        self.assertTrue(TrafficSearch('','JSON field','').error)
        self.assertFalse(TrafficSearch('1','JSON field','data.amount').matches(event(b'\xff')))
        self.assertTrue(TrafficSearch('').matches(event(b'any bytes\0')))
        self.assertTrue(TrafficSearch('A'*4097).error)
