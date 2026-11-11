import json

PLUGIN = {'name': 'Simulator request ID', 'description': 'Echo a JSON requestId in an automatic reply.'}


def respond(request, reply, context):
    if context['rule_name'] != 'Echo request ID':
        return None
    body = json.loads(request)
    return json.dumps({'requestId': body['requestId'], 'ok': True}, separators=(',', ':')).encode() + b'\n'
