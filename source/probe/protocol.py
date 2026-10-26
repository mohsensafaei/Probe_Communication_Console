"""Bounded, read-only protocol interpretation with exact source byte ranges."""
from dataclasses import dataclass
import json
import re
import struct

from .codec import checksum, visible

MAX_DATA = 1024 * 1024
MAX_FIELDS = 2000
CHECKSUMS = ("SUM8", "XOR8", "LRC8", "CRC16 Modbus", "CRC16 CCITT", "CRC32")
FIELD_TYPES = ("Hex", "Text", "Unsigned LE", "Unsigned BE", "Signed LE", "Signed BE",
               "Float LE", "Float BE", "Length ASCII", "Length LE", "Length BE", "Checksum")


class IncompleteMessage(ValueError):
    """More bytes may complete the message or requested field."""


@dataclass(frozen=True)
class Field:
    name: str
    offset: int
    size: int
    value: str
    kind: str = ""
    status: str = "Info"
    selector: str = ""


def bounded(data):
    if not isinstance(data, bytes):raise ValueError("Choose binary payload bytes.")
    if len(data) > MAX_DATA:raise ValueError("Protocol analysis is limited to 1 MiB. Choose fewer chunks.")
    if not data:raise IncompleteMessage("No bytes selected.")


def pointer_part(key):
    return str(key).replace("~", "~0").replace("/", "~1")


def json_frame(data, strict_length=True):
    """Return the first JSON object/array, its exact byte fields and frame end.

    Accept plain UTF-8 JSON or an ASCII decimal body-length prefix (1–12 digits).
    Trailing bytes are displayed separately; they are never silently discarded.
    """
    bounded(data)
    try:text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        if exc.end == len(data):raise IncompleteMessage("Incomplete UTF-8 JSON reply.") from None
        raise ValueError("JSON payload must be UTF-8.") from None
    start = len(text)-len(text.lstrip());prefix = None
    if start < len(text) and text[start] in "0123456789":
        begin=start
        while start < len(text) and text[start] in "0123456789":start += 1
        if start-begin > 12:raise ValueError("ASCII length prefixes support at most 12 digits.")
        prefix=(begin,start)
        while start < len(text) and text[start].isspace():start += 1
    if start >= len(text) or text[start] not in "{[":raise IncompleteMessage("Expected JSON object/array, optionally after an ASCII length prefix.")
    decoder = json.JSONDecoder(parse_constant=lambda value: (_ for _ in ()).throw(ValueError("Non-finite JSON number.")))
    try:value, end = decoder.raw_decode(text, start)
    except json.JSONDecodeError:raise IncompleteMessage("JSON is incomplete or invalid. Select all reply chunks.") from None
    except RecursionError:raise ValueError("JSON nesting is too deep.") from None
    offsets = [0]
    for char in text:offsets.append(offsets[-1] + len(char.encode("utf-8")))
    fields = []
    if prefix is not None:
        a, b = prefix;declared = int(text[a:b]);actual = offsets[end] - offsets[start]
        fields.append(Field("Body length", offsets[a], offsets[b]-offsets[a], f"{declared} (JSON bytes: {actual})",
                            "ASCII length", "Valid" if declared == actual else "Mismatch"))
        if strict_length and offsets[start] + declared > len(data):raise IncompleteMessage("Length-prefixed JSON body is incomplete.")
    def skip(i):
        while i < len(text) and text[i].isspace():i += 1
        return i
    def walk(i, path, depth):
        if depth > 32:raise ValueError("JSON supports at most 32 nested levels.")
        if len(fields) >= MAX_FIELDS:raise ValueError("JSON exceeds 2000 fields.")
        i = skip(i);first = i;char = text[i]
        if char in "{[":
            close = "}" if char == "{" else "]";i = skip(i+1);index = 0
            while text[i] != close:
                if char == "{":
                    key, keyend = decoder.raw_decode(text, i);i = skip(keyend)+1
                else:key = index
                i = walk(i, path+"/"+pointer_part(key), depth+1);i = skip(i);index += 1
                if text[i] == ",":i = skip(i+1)
            return i+1
        item, last = decoder.raw_decode(text, i)
        display = json.dumps(item, ensure_ascii=False, allow_nan=False)
        fields.append(Field(path or "/", offsets[first], offsets[last]-offsets[first], display,
                            "JSON", "Info", path))
        return last
    walk(start, "", 0)
    if end < len(text) and text[end:].strip():
        fields.append(Field("Trailing bytes", offsets[end], len(data)-offsets[end], visible(data[offsets[end]:])[:160], "Raw"))
    return value, tuple(fields), offsets[end]


def json_value(data, selector):
    value, _, _ = json_frame(data)
    # RFC 6901 pointers are exact even when a key contains dots, / or ~.
    # Dot paths are accepted for convenient manual entry.
    if selector.startswith("/"):
        keys = [key.replace("~1", "/").replace("~0", "~") for key in selector[1:].split("/")]
    elif selector in ("", "$"):keys = []
    else:
        path = selector.removeprefix("$.")
        if not re.fullmatch(r"[\w-]+(?:\[\d+\]|\.[\w-]+)*", path):raise ValueError("Use a JSON path such as data.sessionId or /data/sessionId.")
        keys = re.findall(r"[\w-]+", path)
    try:
        for key in keys:value = value[int(key)] if isinstance(value, list) else value[key]
    except (KeyError, IndexError, TypeError, ValueError):raise ValueError(f"JSON field not found: {selector}") from None
    return value


def tlv_fields(data, ber=False):
    """Explicit one-byte tag/length TLV or definite-length BER-TLV."""
    bounded(data);result = []
    def parse(begin, end, prefix="", depth=0):
        if depth > 16:raise ValueError("TLV nesting exceeds 16 levels.")
        pos = begin
        while pos < end:
            if len(result) >= MAX_FIELDS:raise ValueError("TLV exceeds 2000 fields.")
            first = pos;tagend = pos+1
            if ber and data[pos] & 31 == 31:
                while True:
                    if tagend >= end:raise IncompleteMessage("TLV tag is incomplete.")
                    part = data[tagend];tagend += 1
                    if tagend-first > 4:raise ValueError("BER tag exceeds 4 bytes.")
                    if not part & 128:break
            if tagend >= end:raise IncompleteMessage("TLV length is missing.")
            size = data[tagend];pos = tagend+1
            if ber and size & 128:
                count = size & 127
                if not 1 <= count <= 4:raise ValueError("Use definite BER lengths of 1–4 bytes.")
                if pos+count > end:raise IncompleteMessage("BER length is incomplete.")
                size = int.from_bytes(data[pos:pos+count], "big");pos += count
            if pos+size > end:raise IncompleteMessage(f"TLV value at offset {first} is incomplete (needs {size} bytes).")
            tag = data[first:tagend].hex().upper();path = prefix+tag
            payload = data[pos:pos+size]
            result.append(Field(f"Tag {path}", pos, size, f"{payload.hex(' ').upper()}  ·  {visible(payload)}"[:320], "BER-TLV" if ber else "TLV", "Info", path))
            if ber and data[first] & 32 and size:parse(pos, pos+size, path+"/", depth+1)
            pos += size
    parse(0, len(data));return tuple(result)


def field_number(value, label, maximum=MAX_DATA):
    if isinstance(value, bool):raise ValueError(f"{label} must be a whole number.")
    try:number = int(value)
    except (ValueError, TypeError, OverflowError):raise ValueError(f"{label} must be a whole number.") from None
    if str(number) != str(value).strip() or not 0 <= number <= maximum:raise ValueError(f"{label} must be 0–{maximum}.")
    return number


def validate_fields(fields):
    if not isinstance(fields, list) or len(fields) > 128:raise ValueError("A custom profile supports at most 128 fields.")
    for field in fields:
        if not isinstance(field, dict):raise ValueError("Each field must be an object.")
        if field.get("kind", "Hex") not in FIELD_TYPES:raise ValueError("Unknown field format.")
        field_number(field.get("offset", 0), "Offset");field_number(field.get("length", 1), "Length")
        for key in ("start", "end"):
            if field.get(key) not in (None, ""):field_number(field[key], "Range "+key)
        if field.get("kind") == "Checksum" and field.get("algorithm", "SUM8") not in CHECKSUMS:raise ValueError("Unknown checksum algorithm.")
    return fields


def custom_fields(data, definitions):
    bounded(data);validate_fields(definitions);result = []
    for index, definition in enumerate(definitions):
        offset = int(definition.get("offset", 0));size = int(definition.get("length", 1)) or max(0,len(data)-offset)
        name = str(definition.get("name", f"Field {index+1}"));kind = definition.get("kind", "Hex")
        if offset+size > len(data) or offset >= len(data):
            result.append(Field(name, offset, size, "Not enough bytes", kind, "Truncated"));continue
        raw = data[offset:offset+size];status = "Info"
        if kind in ("Text", "Hex"):value = visible(raw) if kind == "Text" else raw.hex(" ").upper()
        elif kind.startswith("Float"):
            if size not in (4, 8):raise ValueError("Float fields need 4 or 8 bytes.")
            value = str(struct.unpack(("<" if kind.endswith("LE") else ">")+("f" if size == 4 else "d"), raw)[0])
        elif kind.startswith(("Length", "Checksum")):
            start_value=definition.get("start")
            if start_value in (None,""):start_value=offset+size if kind.startswith("Length") else 0
            start = field_number(start_value, "Range start")
            end_value = definition.get("end")
            end = len(data) if kind.startswith("Length") else offset
            if end_value not in (None, ""):end = field_number(end_value, "Range end")
            if not 0 <= start <= end <= len(data):raise ValueError(f"{name}: validation range is outside the payload.")
            expected = checksum(data[start:end], definition.get("algorithm", "SUM8")) if kind == "Checksum" else end-start
            if kind == "Checksum":actual = raw;value = f"{raw.hex(' ').upper()} · expected {expected.hex(' ').upper()}"
            else:
                try:actual = int(raw.decode("ascii")) if kind == "Length ASCII" else int.from_bytes(raw, "little" if kind.endswith("LE") else "big")
                except (ValueError, UnicodeDecodeError):actual = None
                value = f"{actual if actual is not None else 'not a number'} · expected {expected}"
            status = "Valid" if actual == expected else "Mismatch"
        else:
            if size > 8:raise ValueError("Integer fields support 1–8 bytes.")
            value = str(int.from_bytes(raw, "little" if kind.endswith("LE") else "big", signed=kind.startswith("Signed")))
        result.append(Field(name, offset, size, value[:1024], kind, status))
    return tuple(result)


def inspect_payload(data, mode="Auto", definitions=()):
    bounded(data)
    if mode == "Auto":
        mode = "JSON" if re.match(rb"\s*(?:\d{1,12}\s*)?[{\[]", data) else "Raw bytes"
    if mode == "JSON":return mode, json_frame(data,strict_length=False)[1]
    if mode in ("TLV (1-byte)", "BER-TLV"):return mode, tlv_fields(data, mode == "BER-TLV")
    if mode == "Custom fields":return mode, custom_fields(data, list(definitions))
    if mode != "Raw bytes":raise ValueError("Choose JSON, TLV, custom fields or raw bytes.")
    return mode, (Field("Payload", 0, len(data), visible(data[:160]), "Raw"),)
