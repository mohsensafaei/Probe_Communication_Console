import json
import os
from pathlib import Path
import socket
import tempfile
import unittest

from probe.diagnostics import expect_equal, received, session, wait_for
from probe.plugins import MAX_DATA, PluginWorker, metadata, result
from probe.simulation import DeviceModel, Exchange, Reply, model_from_dict, model_to_dict
from probe.simulator_rules import Fault


SAMPLE = '''
PLUGIN = {'api': 1, 'name': 'Test', 'settings': {'gain': 2}, 'actions': ['Generate']}
def process(data, context):
    s=context['state'];s['count']=s.get('count',0)+1
    return {'fields': {'count': s['count'], 'size': len(data)}, 'values': {'scaled': len(data)*context['settings']['gain']}}
def transform(data, context):
    return data.upper()
def rebuild(data, fields, context):
    return str(fields['size']).encode()
def action(name, data, context):
    return b'generated'
'''


class PluginTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.base=Path(self.temp.name);self.workers=[]
        self.context=dict(direction='TX',peer='a',session='one',workspace=1)

    def tearDown(self):
        for worker in self.workers:
            worker.close()
            if worker.thread:worker.thread.join(3)
            self.assertFalse(worker.process and worker.process.is_alive())
        self.temp.cleanup()

    def entry(self,code=SAMPLE,**options):
        folder=self.base/str(len(list(self.base.iterdir())));folder.mkdir();path=folder/'main.py';path.write_text(code)
        return dict(id=folder.name,path=str(path),enabled=True,changes=False,direction='Both') | options

    def worker(self,entries,timeout=2):
        worker=PluginWorker(entries,timeout);self.workers.append(worker);return worker

    def call(self,worker,op='process',data=b'abc',context=None,**options):
        return worker.submit(op,data,context or self.context,**options).result(8)

    def test_metadata_never_executes_code_and_validates_api(self):
        e=self.entry("PLUGIN={'name':'Safe to inspect'}\nraise RuntimeError('executed')")
        self.assertEqual(metadata(e['path'])['name'],'Safe to inspect')
        e=self.entry("PLUGIN={'api':999}")
        with self.assertRaises(ValueError):metadata(e['path'])

    def test_fields_values_settings_state_and_optional_hooks(self):
        e=self.entry(settings={'gain':3});w=self.worker([e])
        first=self.call(w)[0]['result'];self.assertEqual(first['values']['scaled'],9)
        self.assertEqual(first['fields'][0]['value'],1)
        self.assertEqual(self.call(w,context=dict(self.context,direction='RX'))[0]['result']['fields'][0]['value'],2)
        for change in ({'peer':'b'},{'session':'two'},{'client_peer':'another'}):
            self.assertEqual(self.call(w,context=self.context|change)[0]['result']['fields'][0]['value'],1)
        self.assertEqual(self.call(w,'rebuild',plugin=e['id'],fields={'size':42})[0]['result']['data_hex'],b'42'.hex())
        self.assertEqual(self.call(w,'action',plugin=e['id'],action='Generate')[0]['result']['data_hex'],b'generated'.hex())
        self.call(w,'end',context=dict(session='one',peer='a'))
        self.assertEqual(self.call(w)[0]['result']['fields'][0]['value'],3)
        self.assertEqual(self.call(w,context=self.context|{'session':'three'})[0]['result']['fields'][0]['value'],1)

    def test_changes_require_permission_and_direction(self):
        e=self.entry();w=self.worker([e])
        self.assertEqual(self.call(w,'transform')['data'],b'abc')
        e.update(changes=True,direction='RX');w=self.worker([e])
        self.assertEqual(self.call(w,'transform')['data'],b'abc')
        self.assertEqual(self.call(w,'transform',context=dict(self.context,direction='RX'))['data'],b'ABC')

    def test_respond_permission_order_and_bounds(self):
        code='def respond(request, reply, context):return request + reply'
        decline=self.entry('def respond(*args):return None',changes=True)
        w=self.worker([self.entry(code),self.entry(code,changes=True,direction='TX'),decline])
        rx=dict(self.context,direction='RX')
        self.assertIsNone(self.call(w,'respond',context=rx,reply=b'reply'))
        w=self.worker([decline,self.entry(code,changes=True,direction='RX'),self.entry('def respond(*args):return b"wrong"',changes=True)])
        self.assertEqual(self.call(w,'respond',context=rx,reply=b'default'),b'abcdefault')
        with self.assertRaisesRegex(RuntimeError,'input exceeds'):
            self.call(w,'respond',context=rx,reply=b'x'*MAX_DATA)
        w=self.worker([self.entry('def respond(*args):return "invalid"',changes=True)])
        with self.assertRaisesRegex(RuntimeError,'return None or bytes'):
            self.call(w,'respond',context=rx,reply=b'')

    def test_simulator_auto_replies_to_complete_requests_and_correct_client(self):
        examples=Path(__file__).resolve().parents[1]/'examples'
        model=model_from_dict(json.loads((examples/'simulator-plugin-reply.json').read_text()))
        w=self.worker([dict(id='responder',path=str(examples/'plugins'/'simulator_reply.py'),enabled=True,changes=True)])
        with session('Device Simulator',plugins=w,simulator_model=model) as (_,events,ready):
            address=ready['address'][:2]
            with socket.create_connection(address,timeout=5) as a, socket.create_connection(address,timeout=5) as b:
                first=b'{"requestId":"alpha"}'
                a.sendall(first[:8]);wait_for(lambda:any(e.get('state')=='waiting' for e in events),events)
                b.sendall(b'{"requestId":"beta"}')
                with b.makefile('rb') as reader:self.assertEqual(json.loads(reader.readline()),{'requestId':'beta','ok':True})
                a.sendall(first[8:]+b'{"requestId":"gamma"}')
                with a.makefile('rb') as reader:
                    self.assertEqual([json.loads(reader.readline())['requestId'] for _ in range(2)],['alpha','gamma'])
            wait_for(lambda:len([e for e in events if e.get('direction')=='RX'])==3,events)
            self.assertEqual(len({e['peer'] for e in events if e.get('direction')=='RX'}),2)

    def test_simulator_respond_declines_suppresses_and_preserves_faults(self):
        w=self.worker([self.entry('def respond(request, reply, context):\n return {b"A": None, b"B": b"", b"C": b"123"}[request]',changes=True)])
        model=DeviceModel((Exchange(b'A',(Reply(b'D'),Reply(b'E'))),Exchange(b'B',(Reply(b'WRONG'),)),
                           Exchange(b'C',(),fault=Fault('Truncate',count=2))))
        with session('Device Simulator',plugins=w,simulator_model=model) as (_,events,ready):
            with socket.create_connection(ready['address'][:2],timeout=5) as app, app.makefile('rb') as reader:
                app.sendall(b'ABC');self.assertEqual(reader.read(4),b'DE12')
                wait_for(lambda:any(e.get('matches')==3 for e in events),events)
            self.assertEqual(received(events),b'DE12')

    def test_simulator_plugin_error_blocks_default_reply(self):
        w=self.worker([self.entry('def respond(*args):raise ValueError("bad reply")',changes=True)])
        model=DeviceModel((Exchange(b'A',(Reply(b'WRONG'),)),))
        with session('Device Simulator',plugins=w,simulator_model=model) as (_,events,ready):
            with socket.create_connection(ready['address'][:2],timeout=5) as app:
                app.sendall(b'A');wait_for(lambda:any('Reply blocked' in e.get('message','') for e in events),events)
                app.settimeout(.08)
                with self.assertRaises(socket.timeout):app.recv(1)
            self.assertEqual(received(events),b'')

    @unittest.skipUnless(os.name=='posix','Requires POSIX PTY')
    def test_simulator_plugin_only_reply_over_pty(self):
        import serial
        w=self.worker([self.entry('def respond(request, reply, context):return request[::-1]',changes=True)])
        model=model_from_dict(model_to_dict(DeviceModel((Exchange(b'abc',()),))))
        with session('Device Simulator',plugins=w,simulator_model=model,simulator_transport='Virtual serial (PTY)') as (_,_,ready):
            with serial.Serial(ready['app_path'],115200,timeout=5) as app:
                app.write(b'a');app.write(b'bc');self.assertEqual(app.read(3),b'cba')

    def test_transform_order_and_relative_helper_imports(self):
        a=self.entry('def transform(data, context):return data+b"1"',changes=True)
        b=self.entry('from .helper import transform',changes=True)
        Path(b['path']).with_name('helper.py').write_text('def transform(data, context):return b"2"+data')
        self.assertEqual(self.call(self.worker([a,b]),'transform')['data'],b'2abc1')

    def test_analysis_errors_are_reported_without_disabling_other_plugins(self):
        a=self.entry('def process(data, context):raise ValueError("bad packet")')
        b=self.entry();w=self.worker([a,b]);rows=self.call(w)
        self.assertIn('bad packet',rows[0]['error']);self.assertIn('result',rows[1]);self.assertFalse(w.failed)
        self.assertEqual(len(self.call(w)),2)

    def test_result_and_input_limits(self):
        for bad in ({'values':{'x':float('nan')}},{'fields':[{'name':'x'}]},{'fields':[{'name':'x','value':1,'offset':-1}]},{'data':'text'},{'label':'x'*70000}):
            with self.assertRaises((ValueError,TypeError)):result(bad)
        w=self.worker([self.entry()])
        with self.assertRaises(RuntimeError):self.call(w,data=b'x'*(MAX_DATA+1))
        self.assertIsNone(w.thread)

    def test_real_examples_decode_edit_and_rebuild(self):
        import struct
        import hashlib
        examples=Path(__file__).resolve().parents[1]/'examples'/'plugins'
        e=dict(id='sensor',path=str(examples/'binary_sensor.py'),enabled=True)
        w=self.worker([e]);row=self.call(w,data=struct.pack('<hH',2500,3300))[0]['result']
        self.assertEqual(row['values']['Temperature']['value'],25)
        rebuilt=self.call(w,'rebuild',plugin='sensor',fields=dict(temperature_raw=1234,millivolts=5000))[0]['result']
        self.assertEqual(bytes.fromhex(rebuilt['data_hex']),struct.pack('<hH',1234,5000))
        e=dict(id='json',path=str(examples/'json_tools.py'),enabled=True,changes=True)
        w=self.worker([e]);out=self.call(w,'transform',b'{"value":42,"checksum":"old"}\n')['data']
        body=json.loads(out);digest=body.pop('checksum')
        canonical=json.dumps(body,sort_keys=True,separators=(',',':')).encode()
        self.assertEqual(digest,hashlib.sha256(canonical).hexdigest())

    def test_raw_rx_recording_keeps_input_when_a_proxy_changes_it(self):
        e=self.entry('def transform(data,c):return data.upper()',changes=True,direction='RX')
        w=self.worker([e]);raw=self.base/'rx.bin';record=self.base/'traffic.jsonl'
        with session('TCP Server') as (server,_,ready):
            server.echo=True
            with session('TCP Proxy',port=ready['address'][1]) as (proxy,events,pready):
                proxy.plugins=w;proxy.record(record);proxy.record(raw,raw=True)
                with socket.create_connection(pready['address'][:2],timeout=4) as client:
                    client.sendall(b'abc');expect_equal(client.recv(3),b'ABC')
                    wait_for(lambda:any(e.get('direction')=='RX' for e in events))
                proxy.record();proxy.record(raw=True)
        self.assertEqual(raw.read_bytes(),b'abc')
        row=next(json.loads(line) for line in record.read_text().splitlines() if 'original_hex' in json.loads(line))
        self.assertEqual(row['hex'],'414243');self.assertEqual(row['original_hex'],'616263')

    def test_timeout_and_import_failure_fail_closed(self):
        w=self.worker([self.entry('def transform(data, context):\n while True:pass',changes=True)],timeout=.1)
        self.call(w,'ready')
        with self.assertRaisesRegex(RuntimeError,'timed out'):self.call(w,'transform')
        wait_for(lambda:w.closed)
        with self.assertRaises(RuntimeError):self.call(w,'transform')
        broken=self.worker([self.entry('raise ValueError("cannot import")')])
        with self.assertRaisesRegex(RuntimeError,'cannot import'):self.call(broken)

    def test_transforms_take_priority_over_analysis_backlog(self):
        gate=self.base/'gate'
        code=f'from pathlib import Path\nimport time\ndef process(data,c):\n while not Path({str(gate)!r}).exists():time.sleep(.005)\n c["state"]["n"]=c["state"].get("n",0)+1\n return {{}}\ndef transform(data,c):return str(c["state"].get("n",0)).encode()'
        w=self.worker([self.entry(code,changes=True)]);self.call(w,'ready')
        analysis=[w.submit('process',b'a',self.context) for _ in range(10)]
        transformed=w.submit('transform',b'abc',self.context);gate.touch()
        self.assertLessEqual(int(transformed.result(5)['data']),1)
        for f in analysis:f.result(4)

    def test_close_during_import_cancels_queued_work(self):
        w=self.worker([self.entry('import time\ntime.sleep(30)')])
        future=w.submit('process',b'abc',self.context)
        w.close();w.thread.join(3)
        self.assertFalse(w.thread.is_alive())
        with self.assertRaises(RuntimeError):future.result(1)

    def test_split_frames_coalescing_and_incomplete_eof(self):
        code="PLUGIN={'framing':{'delimiter':'0A'}}\ndef transform(data, context):return data.upper()"
        w=self.worker([self.entry(code,changes=True)])
        self.assertEqual(self.call(w,'transform',b'ab')['data'],b'')
        self.assertEqual(self.call(w,'transform',b'c\nd\ne')['data'],b'ABC\nD\n')
        self.assertEqual(self.call(w,'transform',b'x',context=dict(self.context,peer='b'))['data'],b'')
        with self.assertRaisesRegex(RuntimeError,'1 incomplete'):self.call(w,'end',context=self.context)
        self.assertEqual(self.call(w,'transform',b'f\n')['data'],b'F\n')

    def test_tcp_proxy_transforms_both_directions_and_records_original_bytes(self):
        w=self.worker([self.entry(changes=True)])
        with session('TCP Server') as (server,_,ready):
            server.echo=True
            with session('TCP Proxy',port=ready['address'][1]) as (proxy,events,pready):
                proxy.plugins=w
                with socket.create_connection(pready['address'][:2],timeout=4) as client:
                    client.sendall(b'abc');expect_equal(client.recv(3),b'ABC')
                    wait_for(lambda:any(e.get('direction')=='RX' for e in events))
                rows=[e for e in events if e['kind']=='data']
                tx=next(e for e in rows if e['direction']=='TX')
                self.assertEqual(tx['data'],b'ABC');self.assertEqual(tx['original_hex'],b'abc'.hex())

    def test_failed_transform_does_not_send_original_payload(self):
        w=self.worker([self.entry('def transform(data, context):raise ValueError("blocked")',changes=True)])
        with session('TCP Server') as (server,events,ready):
            server.plugins=w
            with socket.create_connection(ready['address'][:2],timeout=4) as client:
                wait_for(lambda:bool(server.clients));server.send(b'private')
                wait_for(lambda:any(e.get('plugin_error') for e in events))
                client.settimeout(.15)
                with self.assertRaises(socket.timeout):client.recv(32)
            blocked=next(e for e in events if e.get('plugin_error'))
            self.assertEqual(blocked['data'],b'');self.assertEqual(blocked['original_hex'],b'private'.hex())


if __name__=='__main__':unittest.main()
