import struct

PLUGIN = {
    'api': 1,
    'name': 'Binary sensor',
    'description': 'Four-byte little-endian sample. Set Traffic framing to Fixed length, 4 bytes.',
    'settings': {'temperature_scale': 0.01},
    'actions': ['Generate sample'],
}


def process(data, context):
    if len(data) != 4:
        return {'valid': False, 'message': 'Expected four bytes; select Fixed length / 4 in Traffic framing.'}
    temperature, millivolts = struct.unpack('<hH', data)
    return {
        'fields': [
            {'name': 'temperature_raw', 'value': temperature, 'offset': 0, 'size': 2},
            {'name': 'millivolts', 'value': millivolts, 'offset': 2, 'size': 2},
        ],
        'values': {
            'Temperature': {'value': temperature * context['settings']['temperature_scale'], 'unit': '°C'},
            'Voltage': {'value': millivolts / 1000, 'unit': 'V'},
        },
        'valid': True,
    }


def rebuild(data, fields, context):
    return struct.pack('<hH', fields['temperature_raw'], fields['millivolts'])


def action(name, data, context):
    sample=struct.pack('<hH',2500,3300)
    return process(sample,context)|{'data':sample}
