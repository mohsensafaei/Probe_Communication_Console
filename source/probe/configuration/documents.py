from ..protocol import validate_fields
from ..scenario import compile_steps, sequence_from_dict
from ..simulation import model_from_dict


def describe(value, kind):
    if kind=='sequence':
        rows,cycles=sequence_from_dict(value);steps=compile_steps(rows)
        lines=[f'{len(steps)} messages; '+(f'{cycles} cycles.' if cycles else 'Repeats until stopped.')]
        for i,step in enumerate(steps[:50],1):
            lines.append(f'{i}. {step.name[:80]} | {len(step.payload)} preview bytes | repeat {step.repeat} | interval {step.delay_ms} ms | '+
                         (f'reply timeout {step.timeout_ms} ms' if step.wait_for_reply or step.expect or step.flow else 'no reply check'))
        if len(steps)>50:lines.append('Preview shows the first 50 messages; all validated messages will be imported.')
        lines.append('Templates and response routes remain dynamic. A valid file does not prove device behavior.')
    elif kind=='simulator':
        model=model_from_dict(value)
        lines=[f'{len(model.exchanges)} rules; request framing: '+(model.framing.mode if model.framing else 'Exact stream')]
        for i,exchange in enumerate(model.exchanges[:50],1):
            lines.append(f'{i}. {exchange.name[:80] or exchange.request[:24].hex(" ")} | {len(exchange.replies)} reply chunks | '+
                         (f'FAULT: {exchange.fault.kind}' if exchange.fault else 'normal reply'))
        if len(model.exchanges)>50:lines.append('Preview shows the first 50 rules; all validated rules will be imported.')
    elif kind=='protocol':
        if not isinstance(value,dict) or value.get('format')!='probe-protocol' or value.get('version')!=1:raise ValueError('Choose a Probe protocol profile.')
        fields=validate_fields(value.get('fields'));lines=[f'{len(fields)} protocol fields.']
        for field in fields:lines.append(f"{field.get('name','Field')} | offset {field.get('offset',0)} | length {field.get('length',1)} | {field.get('kind','Hex')}")
    else:raise ValueError('Unknown document type.')
    return '\n'.join(lines)
