import hashlib
import json

PLUGIN = {
    'api': 1,
    'name': 'JSON tools',
    'description': 'LF-delimited JSON objects. Choose Traffic Delimiter 0A and Send ending LF.',
    'settings': {'checksum_field': 'checksum'},
    'framing': {'delimiter': '0A'},
    'actions': ['Generate sample'],
}


def transform(data, context):
    body = json.loads(data)
    key = context['settings']['checksum_field']
    body.pop(key, None)
    canonical = json.dumps(body, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()
    body[key] = hashlib.sha256(canonical).hexdigest()
    return json.dumps(body, ensure_ascii=False, separators=(',', ':')).encode() + b'\n'


def process(data, context):
    body = json.loads(data)
    return {'fields': body, 'values': {k: v for k, v in body.items() if type(v) in (int, float)}}


def rebuild(data, fields, context):
    return transform(json.dumps(fields).encode(), context)


def action(name, data, context):
    sample=rebuild(b'',{'command':'read','channel':1},context)
    return process(sample,context)|{'data':sample}
