"""Semantic device rules and deterministic fault behavior over real streams."""
from dataclasses import replace
import json
import os
import socket
import time
import unittest
from probe.codec import checksum
from probe.diagnostics import session, wait_for
from probe.simulation import DeviceModel, Exchange, Reply, RequestMatcher, model_to_dict, model_from_dict
from probe.simulator_rules import FrameSpec, Condition, Fault, RequestFrames, reply_plan


def semantic(fault=None, conditions=None, framing=None, replies=None):
    return DeviceModel((Exchange(b'',replies or (Reply(b'OK'),),tuple(conditions or [Condition(selector='data.service',value='03')]),fault,'Payment'),),framing=framing or FrameSpec())


def request(service='03',**data):
    return json.dumps({'data':{'service':service,**data}},ensure_ascii=False).encode()


class SemanticRules(unittest.TestCase):
    def test_json_fragmented_coalesced_variable_fields_and_prefix(self):
        m=RequestMatcher(semantic(),ordered=False)
        body=request(session='changed',amount=1000)
        prefix=f'{len(body):06}'.encode()
        self.assertEqual(m.feed(prefix+body[:10]),[])
        self.assertEqual(len(m.feed(body[10:]+request())),2)
        self.assertEqual(m.details,[(0,1,prefix+body),(0,2,request())])
        self.assertEqual(m.feed(request('02')),[])
        self.assertIn('data.service',m.errors[0])
        self.assertEqual(m.feed(b'000001'+body),[])
        self.assertIn('length',m.errors[0])
        m.reset();self.assertEqual(len(m.feed(request())),1);self.assertEqual(m.details,[(0,1,request())])

    def test_required_fields_types_and_numeric_predicates(self):
        conditions=[Condition(selector='data.amount',operator='greater than',value='99'),Condition(selector='data.session',operator='exists')]
        m=RequestMatcher(semantic(conditions=conditions))
        for raw in (request(amount=100),request(amount=1,session='a'),request(amount='NaN',session='a')):
            self.assertEqual(m.feed(raw),[])
        self.assertEqual(len(m.feed(request(amount=100,session='a'))),1)
        unicode_model=semantic(conditions=[Condition(selector='data.name',value='سلام')])
        self.assertEqual(len(RequestMatcher(unicode_model).feed(request(name='سلام'))),1)
        array=semantic(conditions=[Condition(selector='/items/0/value',value='yes')])
        self.assertEqual(len(RequestMatcher(array).feed(b'{"items":[{"value":"yes"}]}')),1)

    def test_tlv_ber_text_and_byte_ranges(self):
        cases=[(b'\x01\x02AB',Condition('TLV','01','equals','4142',format='Hex')),
               (bytes.fromhex('E1059F02024142'),Condition('BER-TLV','E1/9F02','equals','AB')),
               (b'READ 42',Condition('Text',operator='contains',value='READ')),
               (b'\xff\x64\0',Condition('Bytes',operator='equals',value='100',offset=1,length=2,format='Unsigned LE'))]
        for body,condition in cases:
            with self.subTest(condition=condition):
                m=RequestMatcher(semantic(conditions=[condition],framing=FrameSpec('Fixed length',size=len(body))))
                self.assertEqual(len(m.feed(body[:1])+m.feed(body[1:])),1)
        malformed=RequestMatcher(semantic(conditions=[Condition('TLV','01','exists')],framing=FrameSpec('Fixed length',size=3)))
        self.assertEqual(malformed.feed(b'\x01\x05A'),[])
        self.assertIn('incomplete',malformed.errors[0])

    def test_framing_crc_and_invalid_lengths(self):
        body=b'\x01\x02AB';prefix=(len(body)+2).to_bytes(2,'little');wire=prefix+body+checksum(prefix+body,'CRC16 Modbus')
        spec=FrameSpec('Length prefix',prefix_size=2,prefix_format='Unsigned LE',check='CRC16 Modbus')
        model=semantic(conditions=[Condition('TLV','01','equals','AB')],framing=spec)
        m=RequestMatcher(model)
        self.assertEqual(m.feed(wire[:-1]),[]);self.assertEqual(len(m.feed(wire[-1:])),1)
        bad=wire[:-1]+bytes([wire[-1]^1]);self.assertEqual(m.feed(bad),[]);self.assertIn('mismatch',m.errors[0])
        f=RequestFrames(FrameSpec('Length prefix',prefix_size=2));self.assertEqual(f.feed(b'XX'),[]);self.assertTrue(f.errors)
        f=RequestFrames(FrameSpec('Delimiter',delimiter=b'\r\n'));self.assertEqual(f.feed(b'abc\r'),[]);self.assertEqual(f.feed(b'\nxyz\r\n'),[b'abc\r\n',b'xyz\r\n'])
        f=RequestFrames(FrameSpec());f.feed(b'{'+b' '*70000);self.assertLess(len(f.buffer),65536);self.assertTrue(f.errors)
        f.feed(b'['*40);self.assertTrue(f.errors)

    def test_ambiguity_ordered_rules_and_exact_framing_validation(self):
        a=semantic().exchanges[0];model=DeviceModel((a,replace(a,name='Duplicate')),framing=FrameSpec())
        m=RequestMatcher(model,ordered=False);self.assertEqual(m.feed(request()),[]);self.assertIn('Ambiguous',m.errors[0])
        m=RequestMatcher(model,repeat=False);self.assertEqual(len(m.feed(request()*3)),2)
        exact=DeviceModel((Exchange(b'{"a":1}\r\n',(Reply(b'1'),)),),framing=FrameSpec())
        self.assertEqual(len(RequestMatcher(exact).feed(b'{"a":1}\n')),1)
        with self.assertRaisesRegex(ValueError,'fit Request framing'):
            RequestMatcher(DeviceModel((Exchange(b'A',(Reply(b'B'),)),),framing=FrameSpec()))
        with self.assertRaisesRegex(ValueError,'framing'):RequestMatcher(replace(semantic(),framing=None))

    def test_v1_compatibility_and_v2_roundtrip_validation(self):
        old=DeviceModel((Exchange(b'A',(Reply(b'B',5),)),))
        self.assertEqual(model_to_dict(old)['version'],1)
        self.assertEqual(model_from_dict(model_to_dict(old)),old)
        model=semantic(Fault('No reply','Once on match N',3))
        self.assertEqual(model_to_dict(model)['version'],2)
        self.assertEqual(model_from_dict(json.loads(json.dumps(model_to_dict(model)))),model)
        for patch in (dict(match=[]),dict(fault={'kind':'Split','count':0}),dict(fault={'kind':'Corrupt byte','offset':999}),dict(name='a'*121)):
            data=model_to_dict(model);data['exchanges'][0].update(patch)
            with self.assertRaises(ValueError):model_from_dict(data)
        with self.assertRaises(ValueError):Condition(selector='invalid..field')
        with self.assertRaises(ValueError):Fault('Duplicate',count=100)
        with self.assertRaises(ValueError):Fault('Delay',delay_ms=float('nan'))


class FaultPlans(unittest.TestCase):
    def test_all_faults_preserve_original_and_repeatable_triggers(self):
        base=Exchange(b'A',(Reply(b'AB',10),Reply(b'CD',20)))
        cases=[(Fault('Delay',delay_ms=30),[(b'AB',40),(b'CD',20)],False),
            (Fault('No reply'),[],False),(Fault('Error reply',payload=b'ERR'),[(b'ERR',10)],False),
            (Fault('Disconnect',count=3),[(b'AB',10),(b'C',20)],True),
            (Fault('Truncate',count=1),[(b'A',10)],False),
            (Fault('Corrupt byte',offset=-1,xor_mask=1),[(b'AB',10),(b'CE',20)],False),
            (Fault('Duplicate',count=2,gap_ms=5),[(b'AB',10),(b'CD',20),(b'AB',5),(b'CD',20)],False),
            (Fault('Split',count=1,gap_ms=2),[(b'A',10),(b'B',2),(b'C',2),(b'D',2)],False)]
        for fault,chunks,closed in cases:
            item=replace(base,fault=replace(fault,trigger='Once on match N',nth=3))
            for hit in (1,2,4):self.assertEqual(reply_plan(item,hit).chunks,((b'AB',10),(b'CD',20)))
            self.assertEqual(reply_plan(item,3).chunks,tuple(chunks));self.assertEqual(reply_plan(item,3).disconnect,closed)
        self.assertEqual(base.replies,(Reply(b'AB',10),Reply(b'CD',20)))
        self.assertEqual([i for i in range(1,7) if Fault('No reply','Every Nth match',3).applies(i)],[3,6])


class FaultTransports(unittest.TestCase):
    def test_per_client_nth_no_reply_and_reset(self):
        with session('Device Simulator',simulator_model=semantic(Fault('No reply','Once on match N',3))) as (engine,events,ready):
            with socket.create_connection(ready['address'][:2],timeout=2) as a, socket.create_connection(ready['address'][:2],timeout=2) as b:
                for _ in range(2):a.sendall(request());self.assertEqual(a.recv(2),b'OK')
                a.sendall(request());a.settimeout(.06)
                with self.assertRaises(socket.timeout):a.recv(2)
                b.sendall(request());self.assertEqual(b.recv(2),b'OK')
                a.settimeout(2);a.sendall(request());self.assertEqual(a.recv(2),b'OK')
                engine.reset_simulator();wait_for(lambda:any(e.get('state')=='ready' for e in events),events)
                a.sendall(request());self.assertEqual(a.recv(2),b'OK')
                self.assertTrue(any(e.get('state')=='fault' and 'match 3' in e['message'] for e in events))

    def test_disconnect_closes_only_client_and_keeps_server(self):
        with session('Device Simulator',simulator_model=semantic(Fault('Disconnect',count=1))) as (_,events,ready):
            for _ in range(2):
                with socket.create_connection(ready['address'][:2],timeout=2) as app:
                    app.sendall(request());self.assertEqual(app.recv(2),b'O');self.assertEqual(app.recv(2),b'')

    def test_reply_faults_deliver_expected_wire_bytes(self):
        cases=[(Fault('Error reply',payload=b'ERR'),b'ERR'),
               (Fault('Truncate',count=2),b'AB'),
               (Fault('Corrupt byte',offset=0,xor_mask=1),b'@BCD'),
               (Fault('Split',count=1,gap_ms=3),b'ABCD')]
        for fault,expected in cases:
            model=semantic(fault,replies=(Reply(b'AB'),Reply(b'CD')))
            with self.subTest(kind=fault.kind),session('Device Simulator',simulator_model=model) as (_,events,ready):
                with socket.create_connection(ready['address'][:2],timeout=2) as app:
                    app.sendall(request());data=bytearray()
                    while len(data)<len(expected):data.extend(app.recv(len(expected)-len(data)))
                    self.assertEqual(bytes(data),expected)
                    app.settimeout(.03)
                    with self.assertRaises(socket.timeout):app.recv(1)
                    if fault.kind=='Split':
                        chunks=[e for e in events if e.get('kind')=='data' and e['direction']=='RX']
                        self.assertEqual([e['data'] for e in chunks],[b'A',b'B',b'C',b'D'])

    def test_reset_and_stop_cancel_fault_delay(self):
        model=semantic(Fault('Delay',delay_ms=10000))
        with session('Device Simulator',simulator_model=model) as (engine,events,ready):
            with socket.create_connection(ready['address'][:2],timeout=.08) as app:
                app.sendall(request());wait_for(lambda:any(e.get('state')=='fault' for e in events),events)
                engine.reset_simulator();wait_for(lambda:any(e.get('state')=='ready' for e in events),events)
                with self.assertRaises(socket.timeout):app.recv(2)
                app.sendall(request());wait_for(lambda:sum(e.get('state')=='fault' for e in events)==2,events)
                start=time.monotonic();engine.stop();engine.join();self.assertLess(time.monotonic()-start,1)
                self.assertEqual(engine.rx,0)

    @unittest.skipIf(os.name!='posix','Requires POSIX PTY')
    def test_semantic_and_duplicate_over_pty(self):
        import serial
        with session('Device Simulator',simulator_transport='Virtual serial (PTY)',simulator_model=semantic(Fault('Duplicate',count=2,gap_ms=2))) as (_,events,ready):
            with serial.Serial(ready['app_path'],115200,timeout=2) as app:
                raw=request(amount=1234);app.write(raw[:6]);app.write(raw[6:]);self.assertEqual(app.read(4),b'OKOK')


if __name__=='__main__':unittest.main()
