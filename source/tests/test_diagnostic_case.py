import copy
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from probe.capture import load_capture
from probe.evidence.case import build_case, save_case, select_rows, summary


def row(index,data=b'hello'):
    return dict(kind='data',event_id=f'event:{index}',time=index,monotonic_ns=index*1000,clock_id='clock',
                direction='RX',peer='sensor',data=data)


def probe(rows):
    return dict(name='Sensor',config=dict(mode='TCP Client',encoding='utf-8',host='localhost',password='never-export'),rows=rows,
                health=dict(display_dropped=2),fields=[],plugins=[])


class DiagnosticCaseTests(unittest.TestCase):
    def test_context_is_ordered_deduplicated_and_bounded(self):
        rows=[row(i) for i in range(8)]
        self.assertEqual([e['event_id'] for e in select_rows(rows,{'event:2','event:4'},1)],[f'event:{i}' for i in range(1,6)])
        with self.assertRaises(ValueError):select_rows(rows,{'missing'})
        with self.assertRaises(ValueError):select_rows(rows,{'event:2'},21)

    def test_zip_retains_exact_bytes_ids_health_and_never_mutates_input(self):
        rows=[row(1,b'\0\xff'),row(2,b'{"value":3}')];rows[0]['original_hex']='0102'
        source=probe(rows);original=copy.deepcopy(source);case=build_case([source],'Wrong value','Expected 4')
        self.assertEqual(source,original);self.assertEqual(case['completeness'],'unknown')
        self.assertNotIn('password',case['probes'][0]['settings'])
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'case.zip';save_case(path,case)
            with zipfile.ZipFile(path) as archive:
                self.assertEqual(set(archive.namelist()),{'README.md','case.json','traffic.jsonl'})
                events=[json.loads(line) for line in archive.read('traffic.jsonl').splitlines()]
                self.assertEqual(events[0]['hex'],'00FF');self.assertEqual(events[0]['original_hex'],'0102')
                self.assertEqual(events[0]['event_id'],'event:1')
                metadata=json.loads(archive.read('case.json'));self.assertEqual(metadata['probes'][0]['health']['display_dropped'],2)
        self.assertEqual(case['intervals'][0]['clock'],'host_monotonic')

    def test_literal_redaction_covers_utf8_original_hex_and_metadata(self):
        secret='سری';raw=secret.encode()
        source=probe([dict(row(1,b'{"value":"'+raw+b'"}'),original_hex=raw.hex(),plugin_error=raw.hex(),hid={'secret':secret})])
        source['name']=secret
        case=build_case([source],secret,secret,masks=[secret])
        encoded=json.dumps(case,ensure_ascii=False)
        self.assertNotIn(secret,encoded);self.assertNotIn(raw.hex().upper(),encoded)
        self.assertNotIn('hid',case['events'][0]);self.assertNotIn('plugin_error',case['events'][0])
        self.assertEqual(case['analysis'][0]['status'],'not_checked_redacted')
        self.assertEqual(bytes.fromhex(case['events'][0]['original_hex']),b'*'*len(raw))
        self.assertEqual(source['name'],secret)

    def test_payload_omission_and_sanitized_replay_rejection(self):
        case=build_case([probe([row(1,b'secret')])],include_payload=False)
        self.assertNotIn('hex',case['events'][0]);self.assertNotIn('secret',summary(case))
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'redacted.jsonl'
            path.write_text(json.dumps(dict(case['events'][0],hex='00')))
            with self.assertRaisesRegex(ValueError,'Sanitized'):load_capture(path)

    def test_large_selections_fail_explicitly_and_summary_is_bounded(self):
        with self.assertRaisesRegex(ValueError,'200'):build_case([probe([row(i) for i in range(201)])])
        with self.assertRaisesRegex(ValueError,'8 MiB'):build_case([probe([row(1,b'x'*(8*1024*1024+1))])])
        case=build_case([probe([row(i) for i in range(200)])])
        self.assertLessEqual(len(summary(case,500)),560)

    def test_masks_do_not_corrupt_structural_keys_and_ids_remain_valid(self):
        case=build_case([probe([row(1,b'event')])],masks=['event','probe','RX'])
        self.assertEqual(case['format'],'probe-diagnostic-case');self.assertEqual(case['events'][0]['direction'],'RX')
        self.assertTrue(case['events'][0]['event_id'].startswith('masked:'))
