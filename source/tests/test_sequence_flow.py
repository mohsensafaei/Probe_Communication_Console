import asyncio
import json
import socket
import time
import unittest
from types import SimpleNamespace

from probe.codec import checksum
from probe.diagnostics import session, wait_for
from probe.protocol import json_value
from probe.scenario import compile_steps, run_scenario, sequence_from_dict
from probe.sequence_flow import Extraction, initial_variables, send_spec


def rows():
    return [dict(step_id="ready",name="Ready",text="PING",delay_ms=0,timeout_ms=1000,
                 flow=dict(extract=[dict(name="sid",source="JSON",selector="data.sessionId")],
                           condition=dict(variable="sid",operator="equals",value="123"),
                           on_true=dict(action="goto",target="use"),on_false=dict(action="fail"))),
            dict(step_id="skip",name="Skip",text="MUST NOT SEND",delay_ms=0),
            dict(step_id="use",name="Use session",text='{"sessionId":${sid:json}}',length_prefix=6,delay_ms=0)]


class TemplateTests(unittest.TestCase):
    def test_json_escaping_length_and_checksum_rebuilt_after_substitution(self):
        _,spec=send_spec(dict(text='{"sessionId":${sid:json}}',send_mode="Text",length_prefix=6,checksum="XOR8"))
        value='a"ب\\c';data=spec.render({"sid":value})
        self.assertEqual(int(data[:6]),len(data)-6)
        self.assertEqual(json.loads(data[6:-1])["sessionId"],value)
        self.assertEqual(data[-1:],checksum(data[6:-1],"XOR8"))
        _,escaped=send_spec(dict(text='${sid:json}\\r\\n',send_mode="Escaped"))
        self.assertEqual(json.loads(escaped.render({"sid":value})[:-2]),value)
        _,binary=send_spec(dict(text="02 ${blob} 03",send_mode="Hex"))
        self.assertEqual(binary.render({"blob":b"\0\xff"}),b"\x02\0\xff\x03")
        with self.assertRaisesRegex(ValueError,"no value"):spec.render({})
        with self.assertRaises(ValueError):send_spec(dict(text="${x:python}"))

    def test_extractions_types_and_validation(self):
        self.assertEqual(Extraction("sid","JSON","/session").read(b'{"session":"123"}'),"123")
        self.assertEqual(Extraction("ref","TLV","C2",format="Hex").read(b"\xc2\x02\0\xff"),b"\0\xff")
        self.assertEqual(Extraction("n","Bytes",offset=1,length=2,format="Unsigned LE").read(b"X\x02\x01"),258)
        definitions=dict(amount=dict(format="JSON",value="100"),blob=dict(format="Hex",value="00 FF"))
        self.assertEqual(initial_variables(definitions),dict(amount=100,blob=b"\0\xff"))
        with self.assertRaises(ValueError):initial_variables(dict(n=dict(format="JSON",value="1e999")))
        for invalid in (dict(flow=dict(extract=[dict(name="a.b",source="JSON")])),
                        dict(flow=dict(on_true=dict(action="eval"))),dict(step_id="a",flow=dict(on_true=dict(action="goto",target="missing")))):
            with self.assertRaises(ValueError):compile_steps([dict(text="A",**invalid)])
        document=dict(format="probe-sequence",version=3,cycles=2,variables=definitions,steps=rows())
        self.assertEqual(sequence_from_dict(document),(document["steps"],2))


class FlowIntegrationTests(unittest.TestCase):
    def test_fragmented_tcp_reply_extracts_branches_and_sends_rendered_json(self):
        with session("TCP Server") as (engine,events,ready):
            with socket.create_connection(ready["address"][:2],timeout=2) as device:
                wait_for(lambda:len(engine.clients)==1,events)
                engine.start_scenario(compile_steps(rows()))
                self.assertEqual(device.recv(4),b"PING")
                device.sendall(b'{"data":{"sessionId":"1')
                device.settimeout(.06)
                with self.assertRaises(socket.timeout):device.recv(1)
                device.settimeout(2);device.sendall(b'23"}}')
                wire=bytearray()
                while len(wire)<6:wire.extend(device.recv(6-len(wire)))
                length=int(wire);body=bytearray()
                while len(body)<length:body.extend(device.recv(length-len(body)))
                self.assertEqual(json_value(bytes(body),"sessionId"),"123")
                done=wait_for(lambda:next((event for event in events if event.get("state")=="complete"),None),events)
                self.assertEqual((done["sent"],done["checked"]),(2,1))
                self.assertFalse(engine.observers)


class FlowRunnerTests(unittest.IsolatedAsyncioTestCase):
    async def run_steps(self,steps,replies=None,variables=None):
        progress=[];sent=[];observers=set();replies=iter(replies or [])
        def event(kind,**fields):
            if kind=="data":
                for observer in tuple(observers):observer(fields)
            else:progress.append(fields)
        async def send(payload,target,side):
            sent.append(payload)
            for chunk in next(replies,[]):event("data",direction="RX",peer=target,data=chunk)
            return True
        engine=SimpleNamespace(observers=observers,cfg={"mode":"TCP Client"},event=event,_send=send)
        await run_scenario(engine,compile_steps(steps),1,"device","Device / upstream",variables)
        self.assertFalse(observers)
        return sent,progress

    async def test_false_condition_and_missing_variable_fail_before_following_send(self):
        sent,progress=await self.run_steps(rows(),[[b'{"data":{"sessionId":"bad"}}']])
        self.assertEqual(sent,[b"PING"]);self.assertEqual(progress[-1]["state"],"failed")
        sent,progress=await self.run_steps([dict(text="${missing}",delay_ms=0)])
        self.assertFalse(sent);self.assertIn("no value",progress[-1]["message"])

    async def test_timeout_route_skips_remaining_repeats_and_does_not_reuse_old_fields(self):
        steps=[dict(step_id="wait",text="A",repeat=3,delay_ms=0,timeout_ms=10,
                    flow=dict(extract=[dict(name="sid",source="JSON",selector="sid")],on_timeout=dict(action="goto",target="end"))),
               dict(step_id="skip",text="B",delay_ms=0),dict(step_id="end",text="${sid}",delay_ms=0)]
        sent,progress=await self.run_steps(steps,variables={"sid":"old"})
        self.assertEqual(sent,[b"A"]);self.assertIn("no value",progress[-1]["message"])

    async def test_condition_actions_numeric_and_finish(self):
        steps=[dict(text="A",delay_ms=0,flow=dict(extract=[dict(name="n",source="Bytes",length=1,format="Unsigned BE")],
                condition=dict(variable="n",operator="greater than",value="5"),on_true=dict(action="stop"))),dict(text="B",delay_ms=0)]
        sent,progress=await self.run_steps(steps,[[b"\x06"]])
        self.assertEqual(sent,[b"A"]);self.assertEqual(progress[-1]["state"],"complete")

    async def test_stop_interrupts_structured_reply_wait(self):
        observers=set();progress=[];started=asyncio.Event()
        def event(kind,**fields):progress.append(fields)
        async def send(*_):started.set();return True
        engine=SimpleNamespace(observers=observers,cfg={"mode":"USB / Serial"},event=event,_send=send)
        task=asyncio.create_task(run_scenario(engine,compile_steps([dict(text="A",timeout_ms=3600000,flow=dict(extract=[dict(name="x",source="JSON",selector="x")]))]),1,"All clients","Device / upstream"))
        await started.wait();before=time.perf_counter();task.cancel()
        with self.assertRaises(asyncio.CancelledError):await task
        self.assertLess(time.perf_counter()-before,.3);self.assertFalse(observers);self.assertEqual(progress[-1]["state"],"stopped")
