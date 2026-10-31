"""Bounded HID descriptor decoding and transfer-to-report reconstruction.

HID 1.11 short items, little-endian bit fields. This never opens a device.
Unknown usages stay numeric; unsupported/truncated layouts remain explicit.
"""
from collections import defaultdict, OrderedDict
from dataclasses import dataclass
import struct

MAX_REPORT = 65536
MAX_DESCRIPTOR = 16384


def usage_name(page, usage):
    names = {1:{0x30:'X',0x31:'Y',0x32:'Z',0x33:'Rx',0x34:'Ry',0x35:'Rz',0x38:'Wheel',0x39:'Hat switch'},
             8:{1:'Num Lock',2:'Caps Lock',3:'Scroll Lock',4:'Compose',5:'Kana'}}
    if page == 9:return f'Button {usage}'
    if page == 7:
        if 4 <= usage <= 29:return 'Key '+chr(65+usage-4)
        return {0:'No key',0x28:'Enter',0x29:'Escape',0x2A:'Backspace',0x2B:'Tab',0x2C:'Space',
                0xE0:'Left Ctrl',0xE1:'Left Shift',0xE2:'Left Alt',0xE3:'Left GUI',
                0xE4:'Right Ctrl',0xE5:'Right Shift',0xE6:'Right Alt',0xE7:'Right GUI'}.get(usage,f'Key 0x{usage:02X}')
    return names.get(page,{}).get(usage,f'Usage {page:04X}:{usage:04X}')


@dataclass(frozen=True)
class Field:
    kind: str
    report_id: int
    offset: int
    size: int
    count: int
    flags: int
    minimum: int
    page: int
    usages: tuple
    usage_min: int = 0


class ReportDescriptor:
    def __init__(self, data):
        if len(data)>MAX_DESCRIPTOR:raise ValueError('HID descriptor exceeds 16 KiB.')
        self.data=bytes(data);self.fields=[];self.bits=defaultdict(int);self.numbered=False;self.warnings=[]
        g=dict(page=0,minimum=0,maximum=0,size=0,count=0,report_id=0);stack=[];local={};pos=0
        while pos<len(data):
            prefix=data[pos];pos+=1
            if prefix==0xFE:
                if pos+2>len(data):raise ValueError('Truncated HID long item.')
                length=data[pos];pos+=2
                if pos+length>len(data):raise ValueError('Truncated HID long-item body.')
                pos+=length;self.warnings.append('Long item skipped.');continue
            n=(0,1,2,4)[prefix&3];typ=(prefix>>2)&3;tag=prefix>>4
            if pos+n>len(data):raise ValueError('Truncated HID short item.')
            raw=data[pos:pos+n];pos+=n;value=int.from_bytes(raw,'little');signed=int.from_bytes(raw,'little',signed=True)
            if typ==1:
                if tag==0:g['page']=value
                elif tag==1:g['minimum']=signed
                elif tag==2:g['maximum']=signed if g['minimum']<0 else value
                elif tag==7:g['size']=value
                elif tag==8:
                    if not 1<=value<=255:raise ValueError('Invalid HID Report ID.')
                    g['report_id']=value;self.numbered=True
                elif tag==9:g['count']=value
                elif tag==10:
                    if len(stack)>=32:raise ValueError('HID global stack is too deep.')
                    stack.append(dict(g))
                elif tag==11:
                    if not stack:raise ValueError('Unbalanced HID global Pop.')
                    g=stack.pop()
            elif typ==2:
                if tag==0:
                    usages=local.setdefault('usages',[])
                    if len(usages)>=4096:raise ValueError('Too many HID usages.')
                    usages.append(value if n==4 else (g['page']<<16)|value)
                elif tag==1:local['umin']=value if n==4 else (g['page']<<16)|value
                elif tag==2:local['umax']=value if n==4 else (g['page']<<16)|value
                elif tag==10:self.warnings.append('Usage alternatives are not decoded.')
            elif typ==0:
                kind={8:'Input',9:'Output',11:'Feature'}.get(tag)
                if kind:
                    size,count=g['size'],g['count'];key=(kind,g['report_id'])
                    if size>64 or count>4096 or self.bits[key]+size*count>MAX_REPORT*8:raise ValueError('HID report layout exceeds decoding limits.')
                    usages=list(local.get('usages',[]))
                    if 'umin' in local and 'umax' in local:
                        if not 0<=local['umax']-local['umin']<=4095:raise ValueError('Invalid HID usage range.')
                        usages.extend(range(local['umin'],local['umax']+1))
                    self.fields.append(Field(kind,g['report_id'],self.bits[key],size,count,value,g['minimum'],g['page'],tuple(usages),local.get('umin',0)&0xFFFF))
                    self.bits[key]+=size*count
                    if len(self.fields)>1024:raise ValueError('Too many HID fields.')
                local={}
        if stack:self.warnings.append('Unbalanced HID global Push.')

    def decode(self, data, kind='Input'):
        if len(data)>MAX_REPORT:raise ValueError('HID report exceeds 64 KiB.')
        report_id=data[0] if self.numbered and data else 0
        body=data[1:] if self.numbered else data;key=(kind,report_id)
        if key not in self.bits:return [],f'No {kind} layout for Report ID {report_id}.'
        result=[];value=int.from_bytes(body,'little');truncated=len(body)*8<self.bits[key]
        for field in self.fields:
            if (field.kind,field.report_id)!=key or field.flags&1 or not field.size:continue
            for i in range(field.count):
                bit=field.offset+i*field.size
                if bit+field.size>len(body)*8:break
                number=(value>>bit)&((1<<field.size)-1)
                if field.minimum<0 and number&(1<<(field.size-1)):number-=1<<field.size
                usage=field.usages[min(i,len(field.usages)-1)] if field.usages else field.page<<16
                if field.flags&2:
                    name=usage_name(usage>>16,usage&0xFFFF);display=str(number)
                else:
                    name=f'Array {i+1}'
                    index=number-field.minimum
                    selected=field.usages[index] if 0<=index<len(field.usages) else (field.page<<16)|(number&0xFFFF)
                    display=usage_name(selected>>16,selected&0xFFFF)+f' ({number})'
                result.append(dict(field=name,value=display,bit=bit+(8 if self.numbered else 0),bits=field.size,
                                   relative=bool(field.flags&4),page=usage>>16,usage=usage&0xFFFF))
                if len(result)>=512:break
            if len(result)>=512:break
        note='Truncated report.' if truncated else '; '.join(dict.fromkeys(self.warnings))
        return result,note or 'Decoded with HID report descriptor.'


def interfaces_from_config(data):
    """Return HID interface -> interrupt endpoints from a USB configuration."""
    result={};current=None;pos=0
    while pos+2<=len(data):
        length,typ=data[pos:pos+2]
        if length<2 or pos+length>len(data):break
        d=data[pos:pos+length]
        if typ==4 and length>=9:
            current=d[2] if d[5]==3 else None
            if current is not None:result.setdefault(current,set())
        elif typ==5 and length>=7 and current is not None and d[3]&3==3:result[current].add(d[2])
        pos+=length
    return result


class HidTracker:
    """Collapse USB submit/complete pairs; retain original HID payload bytes."""
    def __init__(self, interfaces=None, descriptors=None):
        self.interfaces={int(k):set(v) for k,v in (interfaces or {}).items()};self.descriptors={}
        self.pending=OrderedDict();self.vid=self.pid=None
        for interface,data in (descriptors or {}).items():self.set_descriptor(int(interface),bytes.fromhex(data))

    def set_descriptor(self, interface, data):
        self.descriptors[interface]=ReportDescriptor(data)
        self.interfaces.setdefault(interface,set())

    def consume(self, p):
        endpoint=p['endpoint'];incoming=bool(endpoint&0x80);stage=p['stage'];control=p['transfer']=='control'
        request=None
        if stage=='submit':
            self.pending[p['id']]={'setup':p.get('setup',''),'payload':p['payload'],'endpoint':endpoint,'transfer':p['transfer'],'length':p.get('length',len(p['payload']))}
            if len(self.pending)>4096:self.pending.popitem(last=False)
            request=self.pending[p['id']]
        else:request=self.pending.pop(p['id'],None)
        setup=bytes.fromhex((request or {}).get('setup','') or p.get('setup',''))
        if control and len(setup)==8:
            bm,req,wvalue,index,length=struct.unpack('<BBHHH',setup)
            if stage!='complete' or p['status']!=0:return None
            payload=p['payload'] if bm&0x80 else (request or {}).get('payload',p['payload'])
            if bm&0x80 and req==6 and bm&0x60==0:
                typ=wvalue>>8
                if typ==1 and len(payload)>=12:self.vid,self.pid=struct.unpack_from('<HH',payload,8)
                elif typ==2:self.interfaces.update(interfaces_from_config(payload))
                elif typ==0x22:
                    try:self.set_descriptor(index,payload)
                    except ValueError:pass
                return None
            if bm&0x60!=0x20 or bm&0x1F!=1 or req not in (1,9) or index not in self.interfaces:return None
            kind={1:'Input',2:'Output',3:'Feature'}.get(wvalue>>8)
            if not kind:return None
            incoming=bool(bm&0x80);interface=index
        elif not control and p['transfer']=='interrupt':
            interface=next((i for i,eps in self.interfaces.items() if endpoint in eps),None)
            if interface is None:return None
            # OUT is retained only on successful completion, with its submit data.
            if stage!='complete' or p['status']!=0:return None
            payload=p['payload'] if incoming else (request or {}).get('payload',p['payload'])
            kind='Input' if incoming else 'Output'
        else:return None
        if not payload:return None
        wire_length=p.get('length',len(payload)) if incoming else (request or {}).get('length',len(payload))
        descriptor=self.descriptors.get(interface)
        fields,note=descriptor.decode(payload,kind) if descriptor else ([], 'Report descriptor unavailable; raw bytes retained. Load a descriptor in Analyze.')
        return dict(kind='data',time=p['time'],direction='RX' if incoming else 'TX',
                    peer=f"USB {p['bus']}:{p['device']} · IF {interface} · EP {endpoint:02X}",data=payload,
                    hid=dict(report_type=kind,interface=interface,endpoint=endpoint,fields=fields,note=note,
                             descriptor=descriptor.data.hex().upper() if descriptor else '',
                             vid=self.vid,pid=self.pid,captured_bytes=len(payload),transfer_bytes=wire_length,
                             truncated=len(payload)<wire_length))


def imported_metadata(metadata,data):
    """Validate imported metadata; derive fields again instead of trusting JSON UI rows."""
    if not isinstance(metadata,dict):raise ValueError('Invalid HID metadata.')
    kind=metadata.get('report_type','Input')
    if kind not in ('Input','Output','Feature'):raise ValueError('Invalid HID report type.')
    interface=metadata.get('interface',0);endpoint=metadata.get('endpoint',0)
    if not isinstance(interface,int) or not 0<=interface<=255 or not isinstance(endpoint,int) or not 0<=endpoint<=255:raise ValueError('Invalid HID interface or endpoint.')
    raw=metadata.get('descriptor','')
    if not isinstance(raw,str) or len(raw)>MAX_DESCRIPTOR*2:raise ValueError('Invalid HID report descriptor.')
    descriptor=ReportDescriptor(bytes.fromhex(raw)) if raw else None
    fields,note=descriptor.decode(data,kind) if descriptor else ([], 'Descriptor unavailable; raw report retained.')
    return dict(report_type=kind,interface=interface,endpoint=endpoint,descriptor=raw,fields=fields,note=note,
                truncated=bool(metadata.get('truncated',False)))
