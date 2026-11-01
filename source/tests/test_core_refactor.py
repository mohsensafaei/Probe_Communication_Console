"""Behavioral and boundary checks for the headless/presentation split."""
import csv
import io
import json
import random
import subprocess
import sys
import unittest
from probe.codec import Framer, visible, CONTROLS
from probe.comparison import compare_bytes
from probe.exporting import write_export


class CoreRefactorTests(unittest.TestCase):
    def test_core_imports_do_not_initialize_gui(self):
        subprocess.run([sys.executable,'-c',
            "import sys; import probe.exporting, probe.plot_model, probe.simulation; assert 'tkinter' not in sys.modules"],check=True)

    def test_visible_all_bytes_encodings_and_unicode(self):
        for encoding in ('utf-8','latin-1','utf-16-le','cp1256'):
            data=bytes(range(256))*2
            expected=''.join(f"⟨{CONTROLS.get(ord(c),f'{ord(c):02X}')}⟩" if ord(c)<32 or ord(c)==127 else c for c in data.decode(encoding,errors='replace'))
            self.assertEqual(visible(data,encoding),expected)

    def test_framer_random_chunking_is_lossless(self):
        rng=random.Random(73)
        data=bytes(range(256))*256
        for mode,kwargs in [('Fixed length',dict(size=7)),('Delimiter',dict(delimiter=b'\x0a\x0b'))]:
            f=Framer(mode,**kwargs);parts=[];offset=0
            while offset<len(data):
                size=rng.randint(1,2000);parts.extend(f.feed(data[offset:offset+size],0));offset+=size
            parts.extend(f.flush());self.assertEqual(b''.join(parts),data)
            if mode=='Fixed length':self.assertTrue(all(len(p)==7 for p in parts[:-1]))

    def test_diff_offsets_partition_originals(self):
        rng=random.Random(71)
        for _ in range(100):
            a=rng.randbytes(rng.randrange(0,80));b=rng.randbytes(rng.randrange(0,80))
            changes=compare_bytes(a,b)
            self.assertEqual(b''.join(a[d.a_start:d.a_end] for d in changes),a)
            self.assertEqual(b''.join(b[d.b_start:d.b_end] for d in changes),b)
            for d in changes:
                if d.kind=='equal':self.assertEqual(a[d.a_start:d.a_end],b[d.b_start:d.b_end])

    def test_export_formats_selection_and_metadata(self):
        event=dict(kind='data',time=1,direction='RX',peer='COM34',data=b'\0\xffAB',monotonic_ns=42)
        for suffix in ('.csv','.txt','.jsonl'):
            for hx,text in ((True,False),(False,True),(True,True)):
                stream=io.StringIO();write_export(stream,[event],suffix,hx,text)
                if suffix=='.jsonl':
                    row=json.loads(stream.getvalue());self.assertEqual(row['monotonic_ns'],42)
                    self.assertEqual('hex' in row,hx);self.assertEqual('text' in row,text)
                    if hx:self.assertEqual(bytes.fromhex(row['hex']),event['data'])
                elif suffix=='.csv':
                    row=next(csv.DictReader(io.StringIO(stream.getvalue())))
                    self.assertEqual(row['byte_count'],'4');self.assertEqual('hex' in row,hx);self.assertEqual('text' in row,text)
                else:
                    self.assertEqual('Hex:' in stream.getvalue(),hx);self.assertEqual('Decoded text:' in stream.getvalue(),text)
        self.assertNotIn('hex',event)
        with self.assertRaises(ValueError):write_export(io.StringIO(),[event],include_hex=False,include_text=False)
