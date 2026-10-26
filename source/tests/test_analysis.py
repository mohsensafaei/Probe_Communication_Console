import json
import unittest

from probe.codec import checksum
from probe.comparison import MAX_COMPARE, compare_bytes, comparison_report, parse_ranges
from probe.protocol import IncompleteMessage, custom_fields, inspect_payload, json_frame, json_value, tlv_fields


class ProtocolTests(unittest.TestCase):
    def test_json_nested_unicode_and_escaped_string_ranges(self):
        value={"data":{"sessionId":"a\"ب\\c","items":[3,True,None]},"a/b~c":7}
        body=json.dumps(value,ensure_ascii=False,separators=(",",":")).encode()
        data=str(len(body)).zfill(6).encode()+body
        parsed,fields,end=json_frame(data)
        self.assertEqual(parsed,value);self.assertEqual(end,len(data));self.assertEqual(fields[0].status,"Valid")
        for field in fields[1:]:
            raw=data[field.offset:field.offset+field.size]
            self.assertEqual(json.loads(raw),json_value(data,field.selector))
        self.assertEqual(json_value(data,"data.items[0]"),3)
        self.assertEqual(json_value(data,"/a~1b~0c"),7)
        self.assertEqual(inspect_payload(data)[0],"JSON")
        self.assertEqual(inspect_payload(b"\0\xff")[0],"Raw bytes")

    def test_json_partial_length_mismatch_and_limits(self):
        for data in (b'{"x":',b'000009{"x":1}',b'{"x":"\xd8'):
            with self.assertRaises(IncompleteMessage):json_frame(data)
        self.assertEqual(json_frame(b'000001{"x":1}')[1][0].status,"Mismatch")
        self.assertEqual(inspect_payload(b'000009{"x":1}',"JSON")[1][0].status,"Mismatch")
        self.assertEqual(json_frame(b'{"x":1}garbage')[1][-1].name,"Trailing bytes")
        with self.assertRaises(ValueError):json_frame(b"["*34+b"0"+b"]"*34)
        with self.assertRaises(ValueError):json_frame(json.dumps(list(range(2001))).encode())
        with self.assertRaises(ValueError):json_value(b'{"x":1}',"missing")

    def test_explicit_tlv_and_ber_nested_exact_ranges(self):
        data=bytes.fromhex("A4 02 00 FF C2 03 31 32 33")
        fields=tlv_fields(data)
        self.assertEqual([field.selector for field in fields],["A4","C2"])
        self.assertEqual(data[fields[1].offset:fields[1].offset+fields[1].size],b"123")
        ber=bytes.fromhex("6F 07 9F 02 04 01 02 03 04")
        fields=tlv_fields(ber,True)
        self.assertEqual([f.selector for f in fields],["6F","6F/9F02"])
        long=bytes.fromhex("84 81 80")+b"X"*128
        self.assertEqual(tlv_fields(long,True)[0].size,128)
        for incomplete in (b"\xA4",b"\xA4\x02\x00"):
            with self.assertRaises(IncompleteMessage):tlv_fields(incomplete)
        with self.assertRaises(ValueError):tlv_fields(b"\x84\x80",True)

    def test_custom_length_integer_checksum_validation_and_truncated_fields(self):
        body=b"\x02\xffDATA";data=b"000006"+body;data+=checksum(data,"CRC16 Modbus")
        definitions=[dict(name="Length",offset=0,length=6,kind="Length ASCII",start=6,end=12),
                     dict(name="Flags",offset=6,length=2,kind="Unsigned LE"),
                     dict(name="CRC",offset=12,length=2,kind="Checksum",algorithm="CRC16 Modbus"),
                     dict(name="Missing",offset=30,length=2,kind="Hex")]
        fields=custom_fields(data,definitions)
        self.assertEqual([f.status for f in fields],["Valid","Info","Valid","Truncated"])
        self.assertEqual(fields[1].value,str(0xff02))
        changed=data[:-1]+bytes([data[-1]^1])
        self.assertEqual(custom_fields(changed,definitions)[2].status,"Mismatch")
        self.assertEqual(custom_fields(b"\xff",[dict(kind="Signed BE",length=1)])[0].value,"-1")
        with self.assertRaises(ValueError):custom_fields(data,[dict(kind="Float LE",length=3)])


class ComparisonTests(unittest.TestCase):
    def test_changed_inserted_removed_and_exact_offsets(self):
        for a,b,kind in ((b"ABCD",b"ABXCD","added"),(b"ABXCD",b"ABCD","removed"),(b"ABCD",b"ABZD","changed")):
            changes=compare_bytes(a,b)
            self.assertEqual([d.kind for d in changes if d.kind!="equal"],[kind])
            self.assertEqual(b"".join(a[d.a_start:d.a_end] for d in changes),a)
            self.assertEqual(b"".join(b[d.b_start:d.b_end] for d in changes),b)
        self.assertFalse(compare_bytes(b"",b""))

    def test_ignored_json_values_of_different_lengths_do_not_shift_other_fields(self):
        a=b'{"session":"1","amount":100}'
        b=b'{"session":"long value","amount":101}'
        differences=compare_bytes(a,b,selectors=["/session"])
        changed=[d for d in differences if d.kind not in ("equal","ignored")]
        self.assertEqual(len(changed),1)
        self.assertEqual(a[changed[0].a_start:changed[0].a_end],b"0")
        self.assertEqual(b[changed[0].b_start:changed[0].b_end],b"1")
        self.assertTrue(any(d.kind=="ignored" for d in differences))
        report=comparison_report(a,b,differences,selectors=["/session"])
        self.assertEqual(bytes.fromhex(report["a_hex"]),a)
        self.assertEqual(bytes.fromhex(report["b_hex"]),b)

    def test_byte_ranges_and_invalid_ignores_are_explicit(self):
        ranges=parse_ranges("0:2, 4:6")
        differences=compare_bytes(b"ABCDEF",b"xxCDyy",ranges)
        self.assertFalse(any(d.kind in ("changed","added","removed") for d in differences))
        for bad in ("2:1","-1:2","0:2:3","abc"):
            with self.assertRaises(ValueError):parse_ranges(bad)
        with self.assertRaises(ValueError):compare_bytes(b"ABCD",b"ABCD",[(0,3),(2,4)])
        with self.assertRaises(ValueError):compare_bytes(b'{}',b'{}',selectors=["/missing"])
        with self.assertRaises(ValueError):compare_bytes(b"A"*(MAX_COMPARE+1),b"")
