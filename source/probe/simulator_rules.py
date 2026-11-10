'Bounded request framing, semantic predicates and repeatable reply faults.'
import math
import re
from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation

from .codec import checksum, parse_hex
from .protocol import IncompleteMessage, json_frame, tlv_fields
from .sequence_flow import compile_flow, display_value
from .traffic_search import field_keys

MAX_REQUEST=65536
MAX_DELAY=3600000
FRAME_MODES=('JSON','Delimiter','Fixed length','Length prefix')
SOURCES=('JSON','TLV','BER-TLV','Text','Bytes')
OPERATORS=('equals','not equals','contains','greater than','less than','exists')
FAULTS=('Delay','No reply','Error reply','Disconnect','Truncate','Corrupt byte','Duplicate','Split')


def integer(value,label,minimum=0,maximum=MAX_REQUEST):
    if isinstance(value,bool) or not re.fullmatch(r'-?\d+',str(value).strip()):raise ValueError(f'{label} must be an integer.')
    result=int(value)
    if not minimum<=result<=maximum:raise ValueError(f'{label} must be {minimum}–{maximum}.')
    return result


def milliseconds(value,label='Delay'):
    try:result=float(value)
    except (TypeError,ValueError):raise ValueError(f'{label} must be 0–{MAX_DELAY} ms.') from None
    if not math.isfinite(result) or not 0<=result<=MAX_DELAY:raise ValueError(f'{label} must be 0–{MAX_DELAY} ms.')
    return result


@dataclass(frozen=True)
class FrameSpec:
    mode: str = 'JSON'
    delimiter: bytes = b'\n'
    size: int = 16
    prefix_size: int = 6
    prefix_format: str = 'ASCII'
    check: str = 'None'
    check_start: int = 0

    def __post_init__(self):
        if self.mode not in FRAME_MODES:raise ValueError('Choose JSON, Delimiter, Fixed length or Length prefix framing.')
        if not isinstance(self.delimiter,bytes) or not 1<=len(self.delimiter)<=32:raise ValueError('Request delimiter needs 1–32 bytes.')
        integer(self.size,'Request size',1,MAX_REQUEST)
        integer(self.prefix_size,'Length-prefix size',1,12 if self.prefix_format=='ASCII' else 4)
        if self.prefix_format not in ('ASCII','Unsigned LE','Unsigned BE'):raise ValueError('Choose an ASCII, little-endian or big-endian length prefix.')
        integer(self.check_start,'Checksum coverage start',0,MAX_REQUEST)
        checksum(b'',self.check)
        if self.mode=='JSON' and self.check!='None':raise ValueError('Trailing checksums need Delimiter, Fixed length or Length prefix framing.')

    def declared_length(self,data):
        prefix=data[:self.prefix_size]
        if len(prefix)<self.prefix_size:raise IncompleteMessage('Waiting for the length prefix.')
        if self.prefix_format=='ASCII':
            if not prefix.isdigit():raise ValueError('Length prefix contains non-decimal bytes.')
            size=int(prefix)
        else:size=int.from_bytes(prefix,'little' if self.prefix_format.endswith('LE') else 'big')
        if not 1<=size<=MAX_REQUEST-self.prefix_size:raise ValueError('Declared request length is outside the 64 KiB frame limit.')
        return size

    def payload(self,raw):
        if len(raw)>MAX_REQUEST:raise ValueError('Request exceeds 64 KiB.')
        end=len(raw)
        if self.mode=='Delimiter':
            if not raw.endswith(self.delimiter):raise ValueError('Request does not end with the configured delimiter.')
            end-=len(self.delimiter)
        if self.mode=='Length prefix' and len(raw)!=self.prefix_size+self.declared_length(raw):raise ValueError('Request length does not match its prefix.')
        if self.mode=='Fixed length' and len(raw)!=self.size:raise ValueError('Request has the wrong fixed length.')
        if self.check!='None':
            width=len(checksum(b'',self.check));last=end-width
            if not self.check_start<=last:raise ValueError('Request is too short for its checksum coverage.')
            if checksum(raw[self.check_start:last],self.check)!=raw[last:end]:raise ValueError(f'{self.check} mismatch in request.')
            end=last
        start=self.prefix_size if self.mode=='Length prefix' else 0
        body=raw[start:end]
        if self.mode=='JSON':
            _,fields,finish=json_frame(body,strict_length=False)
            if any(f.status=='Mismatch' for f in fields):raise ValueError('JSON body length does not match its ASCII prefix.')
            if body[finish:].strip():raise ValueError('Unexpected bytes after the JSON request.')
            body=re.sub(rb'^\s*\d{1,12}\s*(?=[{\[])',b'',body).strip()
        return body


def frame_to_dict(frame):
    if frame is None:return None
    result=asdict(frame);result['delimiter']=frame.delimiter.hex().upper();return result


def frame_from_dict(value):
    if value is None:return None
    if not isinstance(value,dict):raise ValueError('Request framing must be an object.')
    return FrameSpec(str(value.get('mode','JSON')),parse_hex(str(value.get('delimiter','0A'))),
                     integer(value.get('size',16),'Request size',1),integer(value.get('prefix_size',6),'Prefix size',1,12),
                     str(value.get('prefix_format','ASCII')),str(value.get('check','None')),integer(value.get('check_start',0),'Checksum coverage start'))


class RequestFrames:
    """Message boundaries are independent of socket/serial read boundaries."""
    def __init__(self,spec):self.spec=spec;self.reset()
    def reset(self):
        self.buffer=bytearray();self.depth=0;self.quoted=False;self.escaped=False;self.started=False;self.prefix_digits=0
        self.errors=[];self.discarded=0;self.expected=None
    def discard(self,reason):
        self.discarded+=len(self.buffer)
        if len(self.errors)<8:self.errors.append(reason)
        self.buffer.clear();self.depth=0;self.quoted=self.escaped=self.started=False;self.prefix_digits=0;self.expected=None
    def feed(self,data):
        self.errors=[];result=[];spec=self.spec
        # Slice input so an untrusted peer cannot build an unbounded pending frame.
        for byte in data:
            self.buffer.append(byte)
            if spec.mode=='JSON':
                if not self.started:
                    if byte in b' \r\n\t':
                        if not self.prefix_digits:self.buffer.clear()
                        continue
                    if 48<=byte<=57:
                        self.prefix_digits+=1
                        if self.prefix_digits>12:self.discard('JSON length prefix exceeds 12 digits.')
                        continue
                    if byte not in (123,91):self.discard('Expected a JSON object/array or an ASCII length prefix.');continue
                    self.started=True;self.depth=1
                elif self.quoted:
                    if self.escaped:self.escaped=False
                    elif byte==92:self.escaped=True
                    elif byte==34:self.quoted=False
                elif byte==34:self.quoted=True
                elif byte in (123,91):
                    self.depth+=1
                    if self.depth>32:self.discard('JSON request exceeds 32 nested levels.');continue
                elif byte in (125,93):self.depth-=1
                if self.started and self.depth==0:
                    result.append(bytes(self.buffer));self.buffer.clear();self.started=False;self.prefix_digits=0
            elif spec.mode=='Delimiter':
                if self.buffer.endswith(spec.delimiter):result.append(bytes(self.buffer));self.buffer.clear()
            elif spec.mode=='Fixed length':
                if len(self.buffer)==spec.size:result.append(bytes(self.buffer));self.buffer.clear()
            elif len(self.buffer)>=spec.prefix_size:
                try:
                    if self.expected is None:self.expected=spec.prefix_size+spec.declared_length(self.buffer)
                except ValueError as exc:self.discard(str(exc));continue
                if len(self.buffer)==self.expected:
                    result.append(bytes(self.buffer));self.buffer.clear();self.expected=None
            if len(self.buffer)>=MAX_REQUEST:self.discard('Incomplete request reached the 64 KiB frame limit.')
        return result


@dataclass(frozen=True)
class Condition:
    source: str = 'JSON'
    selector: str = ''
    operator: str = 'equals'
    value: str = ''
    offset: int = 0
    length: int = 1
    format: str = 'Text'

    def __post_init__(self):
        if self.source not in SOURCES or self.operator not in OPERATORS:raise ValueError('Choose a supported request source and condition.')
        if not isinstance(self.value,str) or len(self.value)>65536:raise ValueError('Condition values are limited to 64 KiB.')
        if self.source!='Text':
            compile_flow(dict(flow=dict(extract=[dict(name='field',source=self.source,selector=self.selector,
                offset=self.offset,length=self.length,format=self.format)])))
        elif len(self.selector)>256:raise ValueError('Request selectors are limited to 256 characters.')
        if self.format=='Hex' and self.source in ('TLV','BER-TLV','Bytes') and self.operator!='exists':
            parse_hex(self.value)
            if self.operator in ('greater than','less than'):raise ValueError('Use Unsigned LE/BE for numeric byte comparisons.')
        if self.operator in ('greater than','less than'):
            try:value=Decimal(self.value)
            except InvalidOperation:raise ValueError('Numeric conditions need a numeric expected value.') from None
            if not value.is_finite():raise ValueError('Numeric conditions need finite values.')

    def evaluate(self,context):
        label=f'{self.source} {self.selector or (str(self.offset)+":"+str(self.offset+self.length) if self.source=="Bytes" else "request")}'
        try:actual=context.read(self)
        except (ValueError,KeyError,IndexError,TypeError,RecursionError) as exc:return False,f'{label}: {str(exc)[:180]}'
        if self.operator=='exists':return True,''
        if isinstance(actual,bytes):
            expected=parse_hex(self.value)
            match=(actual==expected if self.operator=='equals' else actual!=expected if self.operator=='not equals' else expected in actual)
        else:
            a,b=display_value(actual),self.value
            if self.operator=='equals':match=a==b
            elif self.operator=='not equals':match=a!=b
            elif self.operator=='contains':match=b in a
            else:
                try:x,y=Decimal(a),Decimal(b)
                except InvalidOperation:return False,f'{label}: actual value is not numeric.'
                if not x.is_finite() or not y.is_finite():return False,f'{label}: non-finite numeric value.'
                match=x>y if self.operator=='greater than' else x<y
        return match,'' if match else f'{label}: expected {self.operator} {self.value[:80]!r}; got {display_value(actual)[:80]!r}.'


class RequestContext:
    def __init__(self,body):self.body=body;self.cache={}
    def read(self,condition):
        source=condition.source
        if source=='JSON':
            if 'JSON' not in self.cache:self.cache['JSON']=json_frame(self.body)[0]
            value=self.cache['JSON']
            for key in ([] if condition.selector in ('','$') else field_keys(condition.selector)):
                value=value[int(key)] if isinstance(value,list) else value[key]
            return value
        if source=='Text':return self.body.decode('utf-8')
        if source in ('TLV','BER-TLV'):
            if source not in self.cache:self.cache[source]=tlv_fields(self.body,source=='BER-TLV')
            field=next((f for f in self.cache[source] if f.selector==condition.selector.upper()),None)
            if field is None:raise ValueError('Tag is missing.')
            raw=self.body[field.offset:field.offset+field.size]
        else:
            if len(self.body)<condition.offset+condition.length:raise ValueError('Required byte range is missing.')
            raw=self.body[condition.offset:condition.offset+condition.length]
        if condition.format=='Hex':return raw
        if condition.format.startswith('Unsigned'):
            if len(raw)>8:raise ValueError('Integer fields support at most 8 bytes.')
            return int.from_bytes(raw,'little' if condition.format.endswith('LE') else 'big')
        return raw.decode('utf-8')


def conditions_from_dict(value):
    if value is None:return None
    if not isinstance(value,list) or not 1<=len(value)<=16:raise ValueError('Use 1–16 AND conditions per request rule.')
    result=[]
    for item in value:
        if not isinstance(item,dict):raise ValueError('Each request condition must be an object.')
        result.append(Condition(str(item.get('source','JSON')),str(item.get('selector','')),str(item.get('operator','equals')),
            str(item.get('value','')),integer(item.get('offset',0),'Field offset'),integer(item.get('length',1),'Field length',1),str(item.get('format','Text'))))
    return tuple(result)


@dataclass(frozen=True)
class Fault:
    kind: str
    trigger: str = 'Every match'
    nth: int = 1
    delay_ms: float = 0
    payload: bytes = b''
    count: int = 1
    gap_ms: float = 0
    offset: int = -1
    xor_mask: int = 1

    def __post_init__(self):
        if self.kind not in FAULTS or self.trigger not in ('Every match','Once on match N','Every Nth match'):raise ValueError('Choose a supported fault and trigger.')
        integer(self.nth,'Matching request number',1,1000000);milliseconds(self.delay_ms);milliseconds(self.gap_ms,'Chunk/copy gap')
        integer(self.count,'Fault byte/copy count',0,8*1024*1024);integer(self.offset,'Corrupt byte offset',-1,8*1024*1024)
        integer(self.xor_mask,'XOR mask',1,255)
        if not isinstance(self.payload,bytes) or len(self.payload)>8*1024*1024:raise ValueError('Fault reply exceeds 8 MiB.')
        if self.kind=='Error reply' and not self.payload:raise ValueError('Enter the complete error reply payload.')
        if self.kind=='Duplicate' and not 2<=self.count<=16:raise ValueError('Duplicate needs 2–16 total copies.')
        if self.kind=='Split' and not 1<=self.count<=MAX_REQUEST:raise ValueError('Split chunk size must be 1–65536 bytes.')
    def applies(self,hit):return self.trigger=='Every match' or (hit==self.nth if self.trigger=='Once on match N' else hit%self.nth==0)


def fault_to_dict(fault):
    if fault is None:return None
    result=asdict(fault);result['payload']=fault.payload.hex().upper();return result


def fault_from_dict(value):
    if value is None:return None
    if not isinstance(value,dict):raise ValueError('Fault settings must be an object.')
    return Fault(str(value.get('kind','')),str(value.get('trigger','Every match')),integer(value.get('nth',1),'Matching request number',1,1000000),
                 milliseconds(value.get('delay_ms',0)),parse_hex(str(value.get('payload',''))),integer(value.get('count',1),'Fault count',0,8*1024*1024),
                 milliseconds(value.get('gap_ms',0)),integer(value.get('offset',-1),'Corrupt byte offset',-1,8*1024*1024),integer(value.get('xor_mask',1),'XOR mask',1,255))


@dataclass(frozen=True)
class ReplyPlan:
    chunks: tuple
    disconnect: bool = False
    description: str = ''


def reply_plan(exchange,hit):
    fault=exchange.fault;original=tuple((r.data,r.delay_ms) for r in exchange.replies)
    if fault is None or not fault.applies(hit):return ReplyPlan(original)
    description=f'{fault.kind} · rule match {hit}'
    if fault.kind=='No reply':return ReplyPlan((),description=description)
    if fault.kind=='Delay':
        if not original:return ReplyPlan(((b'',fault.delay_ms),),description=description)
        chunks=((original[0][0],original[0][1]+fault.delay_ms),)+original[1:]
        if chunks[0][1]>MAX_DELAY:raise ValueError('Combined reply/fault delay exceeds one hour.')
        return ReplyPlan(chunks,description=description)
    first_delay=original[0][1] if original else 0
    if fault.kind=='Error reply':return ReplyPlan(((fault.payload,first_delay),),description=description)
    if fault.kind in ('Truncate','Disconnect'):
        chunks=[];remaining=fault.count
        for data,delay in original:
            if remaining<=0:break
            chunks.append((data[:remaining],delay));remaining-=len(data)
        return ReplyPlan(tuple(chunks),fault.kind=='Disconnect',description)
    if fault.kind=='Duplicate':
        if len(original)*fault.count>2000:raise ValueError('Duplicated reply exceeds 2000 chunks.')
        chunks=list(original)
        for _ in range(fault.count-1):
            if original:chunks.extend(((original[0][0],fault.gap_ms),)+original[1:])
        return ReplyPlan(tuple(chunks),description=description)
    data=b''.join(part for part,_ in original)
    if fault.kind=='Split':
        if (len(data)+fault.count-1)//fault.count>2000:raise ValueError('Split reply exceeds 2000 chunks. Increase chunk size.')
        return ReplyPlan(tuple((data[i:i+fault.count],first_delay if i==0 else fault.gap_ms) for i in range(0,len(data),fault.count)),description=description)
    if not data:raise ValueError('Corrupt byte needs a nonempty reply.')
    offset=len(data)-1 if fault.offset==-1 else fault.offset
    if offset>=len(data):raise ValueError('Corrupt byte offset is outside the reply.')
    # Retain original capture chunking and delays when corrupting one byte.
    chunks=[];base=0
    for part,delay in original:
        if base<=offset<base+len(part):
            pos=offset-base;part=part[:pos]+bytes([part[pos]^fault.xor_mask])+part[pos+1:]
        chunks.append((part,delay));base+=len(part)
    return ReplyPlan(tuple(chunks),description=description)
