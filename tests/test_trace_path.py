import unittest
from probe.traffic.trace import combine, find_matches


def row(key,data,**kw):
    return str(key),dict(direction='TX',peer='device',time=float(key),data=data,**kw)


class TracePathTests(unittest.TestCase):
    def test_stream_matches_split_coalesced_and_binary_bytes(self):
        reference={'data':b'\x00\xffABC'}
        rows=[row(1,b'prefix\x00\xff'),row(2,b'A'),row(3,b'BCsuffix')]
        matches=find_matches(reference,rows)
        self.assertEqual(len(matches),1)
        self.assertEqual(matches[0]['keys'],('1','2','3'))
        self.assertEqual(matches[0]['data'],reference['data'])
        self.assertEqual(matches[0]['span'],'#1:6 → #3:2')
        self.assertEqual(rows[0][1]['data'],b'prefix\x00\xff')

    def test_different_directions_peers_and_clients_are_never_joined(self):
        for field in ('direction','peer','client_peer','session'):
            rows=[row(1,b'AB'),row(2,b'CD')];rows[1][1][field]='other'
            self.assertEqual(find_matches({'data':b'ABCD'},rows),[])
            with self.assertRaises(ValueError):combine(rows)

    def test_repeated_occurrences_are_explicit_and_bounded(self):
        rows=[row(1,b'A'*10000)]
        matches=find_matches({'data':b'A'},rows)
        self.assertEqual(len(matches),100)
        self.assertEqual(matches[0]['span'],'#1:0 → #1:1')
        self.assertEqual(find_matches({'data':b''},rows),[])

    def test_large_repeated_payload_has_only_nonoverlapping_spans(self):
        needle=b"A"*1048576
        matches=find_matches({"data":needle},[row(1,needle*8)])
        self.assertEqual(len(matches),8)
        self.assertTrue(all(match["data"] is needle for match in matches))

    def test_scalar_id_finds_changed_payload_and_preserves_types(self):
        reference={'data':b'000040{"data":{"sid":0,"amount":100000}}'}
        rows=[row(1,b'{"data":{"sid":0,"amount":10000}}'),row(2,b'{"data":{"sid":"0"}}'),row(3,b'{"data":{"sid":false}}'),row(4,b'\xff')]
        for field in ('data.sid','/data/sid'):
            matches=find_matches(reference,rows,field)
            self.assertEqual([m['keys'] for m in matches],[('1',)])
            self.assertEqual(matches[0]['data'],rows[0][1]['data'])
        for field in ('unknown','data','[]'):
            with self.assertRaises(ValueError):find_matches(reference,rows,field)

    def test_manual_combination_preserves_capture_order_and_empty_rows(self):
        rows=[row(1,b'\0'),row(2,b''),row(3,b'\xff')]
        self.assertEqual(combine(rows)['data'],b'\0\xff')
        self.assertEqual(find_matches({'data':b'\0\xff'},rows)[0]['keys'],('1','2','3'))
        with self.assertRaises(ValueError):combine([])


if __name__=='__main__':unittest.main()
