import json
import unittest
from probe.evidence.findings import inspect_event, observed_interval
from probe.codec import checksum


class FindingsTests(unittest.TestCase):
    def event(self,data):return dict(event_id='sample',data=data,time=1)

    def test_json_length_reports_numbers_and_exact_utf8_body_range(self):
        body='{"value":"é"}'.encode()
        report=inspect_event(self.event(b'000001'+body))
        check,=report['checks']
        self.assertEqual(check['actual'],1);self.assertEqual(check['expected'],len(body))
        self.assertEqual(check['checked_range'],[6,6+len(body)])
        self.assertEqual(check['status'],'mismatch');json.dumps(report,allow_nan=False)

    def test_custom_checksum_is_same_calculation_as_inspector(self):
        fields=[dict(name='CRC',kind='Checksum',offset=3,length=2,algorithm='CRC16 Modbus')]
        body=b'abc';data=body+checksum(body,'CRC16 Modbus')
        check,=inspect_event(self.event(data),fields)['checks']
        self.assertEqual(check['actual'],check['expected']);self.assertEqual(check['status'],'valid')
        self.assertEqual(check['checked_range'],[0,3])
        bad=inspect_event(self.event(data[:-1]+bytes([data[-1]^1])),fields)['checks'][0]
        self.assertEqual(bad['status'],'mismatch');self.assertNotEqual(bad['actual'],bad['expected'])

    def test_truncation_invalid_json_and_redaction_are_not_protocol_verdicts(self):
        fields=[dict(name='value',kind='Text',offset=2,length=4)]
        check,=inspect_event(self.event(b'abc'),fields)['checks']
        self.assertEqual((check['status'],check['actual'],check['expected']),('truncated',1,4))
        self.assertEqual(inspect_event(self.event(b'{'))['status'],'unavailable')
        report=inspect_event(dict(self.event(b'***'),redacted=True))
        self.assertEqual(report['status'],'not_checked_redacted');self.assertEqual(report['fields'],[])

    def test_intervals_require_a_shared_clock_not_just_numeric_precision(self):
        first=dict(event_id='a',time=10,monotonic_ns=100,clock_id='clock')
        second=dict(event_id='b',time=1,monotonic_ns=200,clock_id='clock')
        self.assertEqual(observed_interval(first,second)['seconds'],1e-7)
        second['clock_id']='other'
        interval=observed_interval(first,second)
        self.assertEqual(interval['seconds'],-9);self.assertEqual(interval['clock'],'wall_time')
        self.assertFalse(interval['shared_clock'])
