import hashlib
import json
import os
from pathlib import Path
import signal
import tempfile
import unittest

from probe.recording import CaptureWriter
from probe.diagnostics import session, wait_for
from probe.scenario import Step


class CaptureWorkerTests(unittest.TestCase):
    def test_capture_and_raw_drain_in_order_and_failed_open_preserves_stream(self):
        errors=[]
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'capture.jsonl';raw=Path(d)/'raw.bin';writer=CaptureWriter(errors.append)
            try:
                writer.control('capture',path);writer.control('raw',raw)
                payload=bytes(range(256))*32
                for i in range(30):writer.enqueue(dict(kind='data',time=i,direction='RX',data=payload))
                with self.assertRaises(OSError):writer.control('capture',Path(d)/'missing'/'bad.jsonl')
                writer.enqueue(dict(kind='data',time=30,direction='RX',data=b'END'))
                writer.control('capture');writer.control('raw')
                rows=[json.loads(line) for line in path.read_text().splitlines()]
                self.assertEqual([row['time'] for row in rows],list(range(31)))
                self.assertEqual(b''.join(bytes.fromhex(row['hex']) for row in rows),payload*30+b'END')
                self.assertEqual(raw.read_bytes(),payload*30+b'END');self.assertFalse(errors)
            finally:writer.close()
            self.assertFalse(writer.process.is_alive());self.assertFalse(writer.monitor.is_alive())

    def test_nested_hid_field_lists_count_toward_capture_budget(self):
        errors=[];writer=CaptureWriter(errors.append,max_bytes=4096)
        try:
            writer.enqueue(dict(kind='data',direction='RX',data=b'A',
                                hid=dict(fields=[dict(field='X',value='123',bit=0,bits=8) for _ in range(100)])))
            self.assertTrue(writer.failed);self.assertIn('incomplete',errors[0])
        finally:writer.close()

    def test_overflow_is_explicit(self):
        errors=[];writer=CaptureWriter(errors.append,max_bytes=1)
        try:
            writer.enqueue(dict(kind='data',data=b'X',direction='RX'))
            self.assertTrue(writer.failed);self.assertIn('incomplete',errors[0])
        finally:writer.close()

    @unittest.skipUnless(os.name=='posix','Uses SIGSTOP to suspend the disk worker')
    def test_suspended_disk_worker_does_not_block_sends(self):
        with tempfile.TemporaryDirectory() as d,session('USB / Serial',serial_port='loop://') as (engine,events,_):
            engine.record(Path(d)/'capture.jsonl');worker=engine.capture_writer
            os.kill(worker.process.pid,signal.SIGSTOP)
            try:
                engine.start_scenario((Step('Send',b'ABC',delay_ms=5,repeat=10),))
                wait_for(lambda:any(e.get('state')=='complete' for e in events),events)
                self.assertEqual(engine.tx,30)
            finally:os.kill(worker.process.pid,signal.SIGCONT)
            engine.record()
            rows=[json.loads(line) for line in Path(d,'capture.jsonl').read_text().splitlines()]
            self.assertEqual(sum(len(bytes.fromhex(row['hex'])) for row in rows if row.get('direction')=='TX'),30)

    def test_heavy_work_runs_in_another_process(self):
        with session('USB / Serial',serial_port='loop://') as (engine,events,_):
            async def check():engine.event('info',message=str(await engine.compute(os.getpid)))
            engine.schedule(check())
            pid=wait_for(lambda:next((e['message'] for e in events if e.get('kind')=='info' and e.get('message','').isdigit()),None),events)
            self.assertNotEqual(int(pid),os.getpid())

    def test_failed_recording_restart_does_not_resume_old_raw_file(self):
        with tempfile.TemporaryDirectory() as d,session('USB / Serial',serial_port='loop://') as (engine,events,_):
            old=Path(d)/'old.jsonl';raw=Path(d)/'old.bin';new=Path(d)/'new.jsonl'
            engine.record(old);engine.record(raw,raw=True);engine.capture_writer.max_bytes=1
            engine.send(b'A');wait_for(lambda:engine.rx==1,events)
            self.assertTrue(any(e.get('kind')=='recording_error' for e in events))
            engine.record(new);engine.send(b'B');wait_for(lambda:engine.rx==2,events);engine.record()
            self.assertEqual(raw.read_bytes(),b'')
            self.assertTrue(any(bytes.fromhex(row.get('hex',''))==b'B' for row in map(json.loads,new.read_text().splitlines())))
