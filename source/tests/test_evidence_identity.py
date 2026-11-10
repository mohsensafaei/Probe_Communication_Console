import io
import json
from pathlib import Path
import tempfile
import unittest

from probe.codec import Framer
from probe.engine import Engine
from probe.exporting import write_export
from probe.capture import load_capture
from probe.traffic_model import DisplayFraming, TrafficHistory


def event(identity, data):
    return dict(kind='data', event_id=identity, time=1, monotonic_ns=2, direction='RX', peer='device', data=data)


class IdentityTests(unittest.TestCase):
    def test_engine_ids_are_unique_across_sessions_and_precede_recording(self):
        rows=[];engine=Engine(rows.append);engine.workspace=2
        engine.event('data',direction='RX',peer='device',data=b'a')
        engine.event('data',direction='TX',peer='device',data=b'b')
        other=[];Engine(other.append).event('data',direction='RX',peer='device',data=b'a')
        ids=[e['event_id'] for e in rows+other]
        self.assertEqual(len(ids),len(set(ids)))
        self.assertIn(':2:1',ids[0]);self.assertEqual(rows[0]['event_version'],1)

    def test_split_coalesced_frames_keep_exact_source_offsets(self):
        framing=DisplayFraming(lambda:Framer('Fixed length',size=3))
        self.assertEqual(list(framing.feed(event('a',b'12'))),[])
        rows=list(framing.feed(event('b',b'34567')))
        self.assertEqual([r['data'] for r in rows],[b'123',b'456'])
        self.assertEqual(rows[0]['source_refs'],[dict(event_id='a',start=0,end=2),dict(event_id='b',start=0,end=1)])
        self.assertEqual(rows[1]['source_refs'],[dict(event_id='b',start=1,end=4)])
        tail,=framing.flush()
        self.assertEqual(tail['source_refs'],[dict(event_id='b',start=4,end=5)])
        self.assertTrue(tail['display_partial']);self.assertTrue(tail['source_refs_complete'])
        self.assertEqual(len({r['event_id'] for r in rows+[tail]}),3)

    def test_reference_overload_is_bounded_and_never_invents_sources(self):
        framing=DisplayFraming(lambda:Framer('Fixed length',size=140))
        rows=[]
        for i in range(140):rows.extend(framing.feed(event(str(i),b'x')))
        row,=rows
        self.assertEqual(row['data'],b'x'*140);self.assertFalse(row['source_refs_complete'])
        self.assertEqual(row['source_refs'],[])
        row,=list(framing.feed(event('next',b'y'*140)))
        self.assertTrue(row['source_refs_complete'])

    def test_ids_survive_export_import_and_legacy_ids_are_content_based(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'capture.jsonl'
            original=event('stable',b'abc');original.update(original_hex='646566',scheduled_ns=1,dispatch_lateness_ns=1)
            with path.open('w') as stream:write_export(stream,[original])
            loaded,=load_capture(path)
            for key in ('event_id','monotonic_ns','original_hex','scheduled_ns'):self.assertEqual(loaded[key],original[key])
            path.write_text(json.dumps(dict(time=1,direction='RX',hex='616263')))
            first,=load_capture(path);renamed=path.with_name('renamed.jsonl');path.rename(renamed)
            second,=load_capture(renamed)
            self.assertEqual(first['event_id'],second['event_id'])

    def test_invalid_identity_and_ranges_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'bad.jsonl'
            for metadata in (dict(event_id='../bad'),dict(source_refs=[{}]),dict(source_refs_complete='yes'),
                             dict(source_refs=[dict(event_id='ok',start=0,end=2)],source_refs_complete=True)):
                path.write_text(json.dumps(dict(time=1,direction='RX',hex='00',**metadata)))
                with self.assertRaises(ValueError):load_capture(path)

    def test_history_copy_does_not_mutate_shared_events_or_reassign_loaded_ids(self):
        original=dict(kind='data',time=1,direction='RX',peer='device',data=b'x')
        history=TrafficHistory();history.extend([original])
        row=next(iter(history.events.values()))
        self.assertNotIn('event_id',original)
        output=io.StringIO();write_export(output,[row]);self.assertIn(row['event_id'],output.getvalue())
        second=TrafficHistory();second.extend([row]);self.assertEqual(next(iter(second.events.values()))['event_id'],row['event_id'])
