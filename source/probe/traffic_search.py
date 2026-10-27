"""Read-only payload filters. Hex matches complete bytes, never half-nibbles."""
import json
import re
from .codec import parse_hex, visible

MODES=("Text","Hex bytes","JSON field")


def json_body(data):
    text=data.decode('utf-8').lstrip()
    prefix=re.match(r'[0-9]{1,12}(?=\s*[\[{])',text)
    if prefix:text=text[prefix.end():].lstrip()
    if not text.startswith(('{','[')):raise ValueError('Not a JSON message')
    value,_=json.JSONDecoder().raw_decode(text)
    return value


def field_keys(path):
    if path.startswith('/'):
        return [part.replace('~1','/').replace('~0','~') for part in path[1:].split('/')]
    if path=='$':return []
    path=path.removeprefix('$.')
    if not re.fullmatch(r'[\w-]+(?:\[\d+\]|\.[\w-]+)*',path):raise ValueError('Enter a JSON field, e.g. data.amount or /data/amount.')
    return re.findall(r'[\w-]+',path)


def leaf_text(value):
    if isinstance(value,str):return value
    return json.dumps(value,ensure_ascii=False,separators=(',',':'))


class TrafficSearch:
    def __init__(self,query='',mode='Text',field='',encoding='utf-8'):
        self.error='';self.query=query.strip();self.mode=mode;self.encoding=encoding;self.keys=[];self.needle=None
        try:
            if mode not in MODES:raise ValueError('Choose Text, Hex bytes or JSON field.')
            if len(query)>4096 or len(field)>256:raise ValueError('Search is limited to 4096 characters; field paths to 256.')
            # Preserve existing saved/typed hex: queries in Text mode.
            if mode=='Text' and self.query.lower().startswith('hex:'):
                self.mode='Hex bytes';self.query=self.query[4:].strip()
                if not self.query:raise ValueError('Enter bytes after hex:, e.g. A4 FF.')
            if self.mode=='Hex bytes' and self.query:
                self.needle=parse_hex(self.query)
                if not self.needle:raise ValueError('Enter complete hex bytes, e.g. A4 FF.')
            if self.mode=='JSON field':self.keys=field_keys(field.strip())
        except ValueError as exc:self.error=str(exc)
        self.term=self.query.casefold()

    def matches(self,event):
        if self.error:return False
        if not self.query and self.mode!='JSON field':return True
        data=event['data']
        if self.mode=='Hex bytes':return self.needle in data
        if self.mode=='JSON field':
            try:
                value=json_body(data)
                for key in self.keys:value=value[int(key)] if isinstance(value,list) else value[key]
                return self.term in leaf_text(value).casefold()
            except (ValueError,TypeError,KeyError,IndexError,RecursionError):return False
        text=data.decode(self.encoding,errors='replace')
        if self.term in text.casefold() or self.term in visible(data,self.encoding).casefold() or self.term in str(event.get('peer','')).casefold():return True
        # A JSON escape may hide the actual field value in the raw text.
        if b'\\' not in data:return False
        try:
            stack=[json_body(data)]
            while stack:
                value=stack.pop()
                if isinstance(value,dict):stack.extend(value.values())
                elif isinstance(value,list):stack.extend(value)
                elif self.term in leaf_text(value).casefold():return True
        except (ValueError,TypeError,RecursionError):pass
        return False
