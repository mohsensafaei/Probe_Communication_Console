"""On-demand matching of retained traffic; no transport or GUI dependencies."""
from bisect import bisect_right
from .traffic_search import field_keys, json_body


def flow(event):
    return tuple(event.get(key, '') for key in ('direction', 'peer', 'client_peer'))


def message(keys, event, data=None, method='Selected manually', span=''):
    return {**event, 'keys': tuple(keys), 'data': event['data'] if data is None else data,
            'method': method, 'span': span}


def find_matches(reference, rows, field='', limit=100):
    if not reference['data']:return []
    if field.strip():
        keys=field_keys(field.strip())
        def identity(data):
            value=json_body(data)
            for key in keys:value=value[int(key)] if isinstance(value,list) else value[key]
            if value is None or isinstance(value,(dict,list)):raise ValueError('Choose a scalar JSON identifier.')
            return type(value),value
        try:expected=identity(reference['data'])
        except (ValueError,TypeError,KeyError,IndexError,RecursionError) as exc:
            raise ValueError('Identifier not found in the reference. Use a complete JSON message and a scalar field.') from exc
        result=[]
        for key,event in rows:
            try:matched=identity(event['data'])==expected
            except (ValueError,TypeError,KeyError,IndexError,RecursionError):continue
            if matched:result.append(message((key,),event,method='Matched by '+field))
            if len(result)>=limit:break
        return result
    streams={}
    for key,event in rows:streams.setdefault(flow(event),[]).append((key,event))
    result=[];needle=reference['data']
    for stream in streams.values():
        offsets=[0]
        for _,event in stream:offsets.append(offsets[-1]+len(event['data']))
        data=b''.join(event['data'] for _,event in stream);start=0
        while len(result)<limit:
            start=data.find(needle,start)
            if start<0:break
            end=start+len(needle)
            first=bisect_right(offsets,start)-1;last=bisect_right(offsets,end-1)-1
            selected=stream[first:last+1]
            span=f'#{selected[0][0]}:{start-offsets[first]} → #{selected[-1][0]}:{end-offsets[last]}'
            result.append(message((key for key,_ in selected),selected[0][1],needle,'Matching bytes in stream',span))
            start+=1
        if len(result)>=limit:break
    return sorted(result,key=lambda event:event['time'])


def combine(rows):
    if not rows:raise ValueError('Select target traffic first.')
    if len({flow(event) for _,event in rows})!=1:raise ValueError('Combine only one direction, peer and client.')
    return message((key for key,_ in rows),rows[0][1],b''.join(event['data'] for _,event in rows))
