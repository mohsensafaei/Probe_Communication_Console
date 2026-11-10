from dataclasses import asdict

from ..protocol import inspect_payload


def inspect_event(event, definitions=(), mode=None):
    report=dict(format='probe-analysis',version=1,event_id=event.get('event_id'),byte_count=len(event['data']),
                partial=bool(event.get('display_partial')),fields=[],checks=[])
    if event.get('redacted'):
        return dict(report,status='not_checked_redacted')
    try:
        mode=mode or ('Custom fields' if definitions else 'Auto')
        mode,fields=inspect_payload(event['data'],'Raw bytes' if mode=='Raw Bytes' else mode,definitions)
        report.update(status='inspected',mode=mode,fields=[asdict(field) for field in fields])
        for field in fields:
            if field.status not in ('Valid','Mismatch','Truncated'):continue
            report['checks'].append(dict(rule='field_bounds' if field.status=='Truncated' else 'checksum' if field.kind=='Checksum' else 'length',
                field=field.name,status=field.status.lower(),actual=field.actual,expected=field.expected,
                range=[field.offset,field.offset+field.size],checked_range=[field.checked_start,field.checked_end]))
    except (ValueError,TypeError,KeyError,RecursionError) as exc:
        report.update(status='unavailable',reason=str(exc))
    return report


def observed_interval(first, second):
    same_clock=first.get('clock_id') and first.get('clock_id')==second.get('clock_id')
    monotonic=same_clock and all(type(e.get('monotonic_ns')) is int for e in (first,second))
    seconds=(second['monotonic_ns']-first['monotonic_ns'])/1e9 if monotonic else second['time']-first['time']
    return dict(from_event_id=first.get('event_id'),to_event_id=second.get('event_id'),seconds=seconds,
                clock='host_monotonic' if monotonic else 'wall_time',shared_clock=bool(monotonic),
                meaning='Host observation interval; not wire latency or request/response correlation.')
