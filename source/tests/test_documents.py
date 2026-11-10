import json
from pathlib import Path
import unittest

from probe.configuration.documents import describe
from probe.evidence.case import build_case
from probe.evidence.findings import inspect_event


class DocumentTests(unittest.TestCase):
    def test_bundled_configurations_validate_with_existing_probe_services(self):
        examples=Path(__file__).resolve().parents[1]/'examples'
        for path in examples.glob('*.json'):
            value=json.loads(path.read_text())
            kind={'probe-sequence':'sequence','probe-device':'simulator','probe-protocol':'protocol'}.get(value.get('format') if isinstance(value,dict) else None)
            if kind:self.assertTrue(describe(value,kind),path.name)

    def test_invalid_semantics_are_rejected_without_a_connection(self):
        sequence=dict(format='probe-sequence',version=3,steps=[dict(text='x',flow=dict(on_true=dict(action='goto',target='missing')))])
        with self.assertRaises(ValueError):describe(sequence,'sequence')
        with self.assertRaises(ValueError):describe(dict(format='probe-device',version=1,exchanges=[]),'simulator')
        with self.assertRaises(ValueError):describe(dict(format='probe-protocol',version=1,fields=[dict(kind='unknown')]),'protocol')

    def test_published_schemas_and_examples_agree(self):
        from jsonschema import Draft202012Validator
        root=Path(__file__).resolve().parents[1]
        schemas={p.stem.split('.')[0]:json.loads(p.read_text()) for p in (root/'schemas').glob('*.json')}
        for value in schemas.values():Draft202012Validator.check_schema(value)
        for path in (root/'examples').glob('*.json'):
            value=json.loads(path.read_text())
            kind={'probe-sequence':'sequence','probe-device':'simulator','probe-protocol':'protocol'}.get(value.get('format') if isinstance(value,dict) else None)
            if kind:Draft202012Validator(schemas[kind]).validate(value)
        event=dict(event_id='one',data=b'{"value":3}',time=1,direction='RX',peer='device')
        Draft202012Validator(schemas['analysis']).validate(inspect_event(event))
        case=build_case([dict(name='Device',rows=[event])]);case.pop('events')
        Draft202012Validator(schemas['case']).validate(case)
        with self.assertRaises(Exception):Draft202012Validator(schemas['sequence']).validate(dict(format='probe-sequence',version=3,steps=[dict(text='x',timeout_ms=-1)]))
