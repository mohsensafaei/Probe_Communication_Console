'Traffic file serialization, independent of Tk and endpoint ownership.'
import csv
import datetime as dt
import json

from .codec import visible


def write_export(stream, rows, suffix='.jsonl', include_hex=True, include_text=True, encoding='utf-8'):
    """Write rows in order; never mutate input bytes or capture metadata."""
    if not (include_hex or include_text):
        raise ValueError('Choose Hex, Decoded text or both.')
    suffix = suffix.lower()
    if suffix == '.csv':
        rows = tuple(rows)
        tcp = any(row.get('tcp_capture') for row in rows)
        fields = ['timestamp', 'direction', 'peer', 'byte_count']
        if include_hex: fields.append('hex')
        if include_text: fields.append('text')
        if tcp: fields.append('tcp_capture')
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
    for event in rows:
        data = event['data']
        if suffix in ('.csv', '.txt'):
            timestamp = dt.datetime.fromtimestamp(event['time']).isoformat()
        if suffix == '.csv':
            row = dict(timestamp=timestamp, direction=event['direction'], peer=event['peer'], byte_count=len(data))
            if include_hex: row['hex'] = data.hex(' ').upper()
            if include_text: row['text'] = visible(data, encoding)
            if tcp: row['tcp_capture'] = bool(event.get('tcp_capture'))
            writer.writerow(row)
        elif suffix == '.txt':
            stream.write(f"{timestamp} {event['direction']} {event['peer']} {len(data)} bytes\n")
            if include_hex: stream.write('Hex: ' + data.hex(' ').upper() + '\n')
            if include_text: stream.write('Decoded text: ' + visible(data, encoding) + '\n')
            stream.write('\n')
        else:
            row = {k: v for k, v in event.items() if k not in ('data', 'hex', 'text')}
            if include_hex: row['hex'] = data.hex().upper()
            if include_text: row['text'] = visible(data, encoding)
            stream.write(json.dumps(row, ensure_ascii=False) + '\n')
