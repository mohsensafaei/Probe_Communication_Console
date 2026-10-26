"""Declarative sequence variables and routing. No expressions or code execution."""
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import codecs
import json
import re

from .codec import encode, parse_hex
from .protocol import MAX_DATA, IncompleteMessage, field_number, json_frame, json_value, tlv_fields

NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,47}\Z")
TOKEN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]{0,47})(?::(json|hex))?\}")
SOURCES = ("JSON", "TLV", "BER-TLV", "Bytes")
FORMATS = ("Text", "Hex", "Unsigned LE", "Unsigned BE")
OPERATORS = ("equals", "not equals", "contains", "greater than", "less than")


def variable_name(value):
    if not isinstance(value,str) or not NAME.fullmatch(value):raise ValueError("Variable names use letters, digits and _, starting with a letter or _. Maximum 48 characters.")
    return value


def display_value(value):
    if isinstance(value,bytes):return value.hex(" ").upper()
    if isinstance(value,str):return value
    return json.dumps(value,ensure_ascii=False,allow_nan=False,separators=(",",":"))


def initial_variables(definitions):
    if not isinstance(definitions,dict) or len(definitions)>64:raise ValueError("Use at most 64 initial variables.")
    result={}
    for name,item in definitions.items():
        variable_name(name)
        if not isinstance(item,dict):raise ValueError("Each initial variable needs a format and value.")
        text=str(item.get("value",""));kind=item.get("format","Text")
        if len(text)>65536:raise ValueError("Variable values are limited to 64 KiB.")
        if kind=="Hex":value=parse_hex(text)
        elif kind=="JSON":
            try:value=json.loads(text,parse_constant=lambda _: (_ for _ in ()).throw(ValueError("Use finite JSON values.")))
            except (ValueError,RecursionError):raise ValueError(f"{name}: enter a valid JSON value.") from None
            try:json.dumps(value,allow_nan=False)
            except (ValueError,RecursionError):raise ValueError(f"{name}: use finite JSON values.") from None
        elif kind=="Text":value=text
        else:raise ValueError("Variable format must be Text, Hex or JSON.")
        result[name]=value
    return result


@dataclass(frozen=True)
class SendSpec:
    text: str
    mode: str
    encoding: str
    ending: str
    checksum: str
    prefix: str
    suffix: str
    length_digits: int = 0

    def render(self,variables,preview=False,limit=MAX_DATA):
        def substitute(text,hex_mode=False):
            def replace(match):
                name,kind=match.groups()
                if name not in variables and not preview:raise ValueError(f"Variable '{name}' has no value. Save it from an earlier reply or add it in Variables.")
                value=variables.get(name,"0")
                if kind=="json":
                    if hex_mode:raise ValueError("Use :json in Text/Escaped payloads, not Hex.")
                    if isinstance(value,bytes):raise ValueError(f"{name}: binary values need :hex or text decoding.")
                    encoded=json.dumps(value,ensure_ascii=False,allow_nan=False,separators=(",",":"))
                    if self.mode=="Escaped":return "".join(f"\\x{byte:02x}" for byte in encoded.encode(self.encoding))
                    if self.mode=="Hercules":return "".join(f"${byte:02X}" for byte in encoded.encode(self.encoding))
                    return encoded
                if kind=="hex" or hex_mode:
                    raw=value if isinstance(value,bytes) else display_value(value).encode(self.encoding)
                    return raw.hex(" ").upper()
                if isinstance(value,bytes):raise ValueError(f"{name}: use ${{{name}:hex}} for binary data.")
                rendered=display_value(value)
                # Escaped/Hercules inputs interpret backslashes/tokens. Encode
                # inserted text to byte tokens so it cannot become new escapes.
                if self.mode=="Escaped":return "".join(f"\\x{byte:02x}" for byte in rendered.encode(self.encoding))
                if self.mode=="Hercules":return "".join(f"${byte:02X}" for byte in rendered.encode(self.encoding))
                return rendered
            if "${" in TOKEN.sub("",text):raise ValueError("Use ${name}, ${name:json} or ${name:hex} for variables.")
            return TOKEN.sub(replace,text)
        body=encode(substitute(self.text,self.mode=="Hex"),self.mode,self.encoding,self.ending,self.checksum,
                    substitute(self.prefix,True),substitute(self.suffix,True))
        if not body:raise ValueError("Message has no bytes to send.")
        if len(body)>limit:raise ValueError("A rendered message is limited to 1 MiB (legacy static messages: 8 MiB).")
        if self.length_digits:
            count=str(len(body))
            if len(count)>self.length_digits:raise ValueError("Message length does not fit the ASCII length prefix.")
            body=count.zfill(self.length_digits).encode("ascii")+body
        return body


def send_spec(row):
    spec=SendSpec(str(row.get("text","")),row.get("send_mode","Text"),row.get("encoding","utf-8"),
                  row.get("ending","None"),row.get("checksum","None"),str(row.get("prefix","")),str(row.get("suffix","")),
                  field_number(row.get("length_prefix",0),"Length-prefix digits",12))
    try:codecs.lookup(spec.encoding)
    except LookupError:raise ValueError("Choose a supported text encoding.") from None
    preview=spec.render({},preview=True,limit=8*1024*1024)
    dynamic=any("${" in value for value in (spec.text,spec.prefix,spec.suffix))
    return preview,spec if dynamic or spec.length_digits else None


@dataclass(frozen=True)
class Extraction:
    name: str
    source: str
    selector: str = ""
    offset: int = 0
    length: int = 1
    format: str = "Text"

    def read(self,data):
        if self.source=="JSON":
            _,fields,_=json_frame(data)
            if any(field.status=="Mismatch" for field in fields):raise ValueError("Reply JSON length prefix does not match its body.")
            return json_value(data,self.selector)
        if self.source in ("TLV","BER-TLV"):
            fields=tlv_fields(data,self.source=="BER-TLV")
            matches=[field for field in fields if field.selector==self.selector.upper().replace(" ","")]
            if not matches:raise IncompleteMessage(f"Reply tag {self.selector} has not arrived.")
            field=matches[0];raw=data[field.offset:field.offset+field.size]
        else:
            if len(data)<self.offset+self.length:raise IncompleteMessage(f"Reply needs bytes {self.offset}:{self.offset+self.length}.")
            raw=data[self.offset:self.offset+self.length]
        if self.format=="Hex":return raw
        if self.format.startswith("Unsigned"):
            if len(raw)>8:raise ValueError("An integer extraction supports at most 8 bytes.")
            return int.from_bytes(raw,"little" if self.format.endswith("LE") else "big")
        try:return raw.decode("utf-8")
        except UnicodeDecodeError:raise ValueError(f"{self.name}: reply value is not UTF-8. Choose Hex for binary data.") from None


@dataclass(frozen=True)
class Action:
    action: str = "next"
    target: str = ""


@dataclass(frozen=True)
class Flow:
    extract: tuple = ()
    variable: str = ""
    operator: str = "equals"
    value: str = ""
    on_true: Action = Action()
    on_false: Action = Action("fail")
    on_timeout: Action = Action("fail")

    def matches(self,variables):
        if not self.variable:return True
        if self.variable not in variables:raise ValueError(f"Condition variable '{self.variable}' has no value.")
        actual=display_value(variables[self.variable]);expected=self.value
        if self.operator=="equals":return actual==expected
        if self.operator=="not equals":return actual!=expected
        if self.operator=="contains":return expected in actual
        try:a,b=Decimal(actual),Decimal(expected)
        except InvalidOperation:raise ValueError("Numeric conditions need numeric values.") from None
        if not a.is_finite() or not b.is_finite():raise ValueError("Numeric conditions need finite values.")
        return a>b if self.operator=="greater than" else a<b


def compile_flow(row):
    source=row.get("flow")
    if not source:return None
    if not isinstance(source,dict):raise ValueError("Response rules must be an object.")
    raw=source.get("extract",[])
    if not isinstance(raw,list) or len(raw)>16:raise ValueError("Save at most 16 reply fields per message.")
    definitions=[];names=set()
    for item in raw:
        if not isinstance(item,dict):raise ValueError("Each saved reply field must be an object.")
        name=variable_name(item.get("name"));kind=item.get("source","JSON");fmt=item.get("format","Text")
        if name in names:raise ValueError(f"Duplicate saved variable: {name}")
        names.add(name)
        if kind not in SOURCES or fmt not in FORMATS:raise ValueError("Choose a supported reply format.")
        selector=str(item.get("selector",""))
        if len(selector)>256:raise ValueError("Reply field selectors are limited to 256 characters.")
        if kind=="JSON" and selector not in ("","$") and not selector.startswith("/") and not re.fullmatch(r"[\w-]+(?:\[\d+\]|\.[\w-]+)*",selector.removeprefix("$.")):
            raise ValueError("Use a JSON path such as data.sessionId or /data/sessionId.")
        if kind in ("TLV","BER-TLV") and not re.fullmatch(r"[0-9A-Fa-f]{2,8}(?:/[0-9A-Fa-f]{2,8})*",selector):raise ValueError("Use a hex tag such as C2 or 6F/84.")
        if kind in ("TLV","BER-TLV") and any(len(part)%2 for part in selector.split("/")):raise ValueError("Each TLV tag needs whole hex bytes, for example C2 or 9F02.")
        offset=field_number(item.get("offset",0),"Reply offset");length=field_number(item.get("length",1),"Reply length",65536)
        if not length:raise ValueError("Reply length must be at least 1 byte.")
        definitions.append(Extraction(name,kind,selector,offset,length,fmt))
    condition=source.get("condition") or {}
    if not isinstance(condition,dict):raise ValueError("The reply condition must be an object.")
    var=condition.get("variable","")
    if condition and not var:raise ValueError("Choose a variable for the reply condition.")
    if var:variable_name(var)
    operator=condition.get("operator","equals");value=str(condition.get("value",""))
    if operator not in OPERATORS or len(value)>65536:raise ValueError("Choose a valid condition and a value up to 64 KiB.")
    def action(key,default):
        item=source.get(key,{"action":default})
        if not isinstance(item,dict) or item.get("action") not in ("next","goto","stop","fail"):raise ValueError("Choose Next message, Go to message, Finish or Fail.")
        target=str(item.get("target",""))
        if item["action"]=="goto" and not target:raise ValueError("Choose a destination message for Go to.")
        return Action(item["action"],target)
    return Flow(tuple(definitions),var,operator,value,action("on_true","next"),action("on_false","fail"),action("on_timeout","fail"))


def needs_reply(step):
    return bool(step.wait_for_reply or step.expect or (step.flow and (step.flow.extract or step.flow.variable or step.flow.on_timeout.action!="fail")))
