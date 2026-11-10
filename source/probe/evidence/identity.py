import re
from collections import deque
from uuid import uuid4

ID = re.compile(r'[A-Za-z0-9_.:-]{1,128}\Z')


def namespace():
    return uuid4().hex


def restore(row):
    result = {}
    for key in ('event_id','clock_id'):
        if key in row:
            if not isinstance(row[key], str) or not ID.fullmatch(row[key]):raise ValueError('Invalid event ID.')
            result[key] = row[key]
    if 'source_refs' in row:
        refs = row['source_refs']
        if not isinstance(refs, list) or len(refs) > 128:raise ValueError('Invalid source references.')
        for ref in refs:
            if not isinstance(ref, dict) or not isinstance(ref.get('event_id'), str) or not ID.fullmatch(ref['event_id']):raise ValueError('Invalid source event ID.')
            if any(type(ref.get(k)) is not int for k in ('start', 'end')) or not 0 <= ref['start'] < ref['end'] <= 24*1024*1024:raise ValueError('Invalid source byte range.')
        result['source_refs'] = [dict(event_id=r['event_id'], start=r['start'], end=r['end']) for r in refs]
    for key in ('event_version', 'monotonic_ns', 'scheduled_ns', 'dispatch_lateness_ns'):
        if key in row:
            if type(row[key]) is not int or row[key] < 0:raise ValueError('Invalid '+key+'.')
            result[key] = row[key]
    if 'source_refs_complete' in row:
        if type(row['source_refs_complete']) is not bool:raise ValueError('Invalid source reference status.')
        result['source_refs_complete'] = row['source_refs_complete']
    return result


CLOCK_ID = namespace()


class Origins:
    def __init__(self):
        self.spans = deque()
        self.pending = 0
        self.missing = False

    def add(self, event):
        size = len(event['data'])
        if not size:return
        self.pending += size
        if not event.get('event_id') or len(self.spans) >= 128:self.missing = True;self.spans.clear()
        if not self.missing:self.spans.append((event['event_id'], 0, size))

    def take(self, size):
        self.pending -= size
        if self.missing:
            if not self.pending:self.missing = False
            return [], False
        refs = []
        while size and self.spans:
            identity, start, end = self.spans.popleft()
            stop = min(end, start+size)
            refs.append(dict(event_id=identity, start=start, end=stop))
            size -= stop-start
            if stop < end:self.spans.appendleft((identity, stop, end))
        return refs, not size
