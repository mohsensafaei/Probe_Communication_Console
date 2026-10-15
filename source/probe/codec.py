"""Payload encoding and display. No transport ever decodes or modifies RX bytes."""
import binascii
import re
import struct

CONTROLS = {0: "NUL", 1: "SOH", 2: "STX", 3: "ETX", 4: "EOT", 5: "ENQ",
            6: "ACK", 7: "BEL", 8: "BS", 9: "TAB", 10: "LF", 11: "VT",
            12: "FF", 13: "CR", 16: "DLE", 21: "NAK", 27: "ESC", 127: "DEL"}

def parse_hex(text):
    # Accept compact hex or bytes separated by whitespace, commas, colons.
    value = re.sub(r"0[xX]", "", text.strip())
    value = re.sub(r"[\s,:_-]", "", value)
    if len(value) % 2:
        raise ValueError("Hex needs two digits per byte (example: 02 48 69 03).")
    if not re.fullmatch(r"[0-9a-fA-F]*", value):
        raise ValueError("Hex accepts only 0–9, A–F and byte separators.")
    return bytes.fromhex(value)

def escaped(text, encoding):
    out = bytearray()
    i = 0
    literal = []
    def flush():
        out.extend("".join(literal).encode(encoding))
        literal.clear()
    table = {"n": 10, "r": 13, "t": 9, "0": 0, "\\": 92}
    while i < len(text):
        if text[i] != "\\":
            literal.append(text[i]); i += 1; continue
        flush()
        i += 1
        if i >= len(text):
            raise ValueError("Trailing backslash. Use \\\\ for a literal backslash.")
        c = text[i]; i += 1
        if c in table:
            out.append(table[c])
        elif c == "x":
            token = text[i:i+2]
            if len(token) != 2 or not re.fullmatch(r"[0-9a-fA-F]{2}", token):
                raise ValueError("Use exactly two hex digits after \\x.")
            out.append(int(token, 16)); i += 2
        else:
            raise ValueError(f"Unknown escape \\{c}. Use \\n, \\r, \\t, \\0, \\xHH or \\\\.")
    flush()
    return bytes(out)

def crc16_modbus(data):
    crc = 0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ (0xA001 if crc & 1 else 0)
    return crc

def hercules_text(text,encoding):
    """Explicit legacy-style byte tokens; text never goes through eval."""
    out=bytearray();literal=[];i=0
    names={name:byte for byte,name in CONTROLS.items()}
    def flush():out.extend("".join(literal).encode(encoding));literal.clear()
    while i<len(text):
        char=text[i]
        if char in "#$<" and i+1<len(text) and text[i+1]==char:
            literal.append(char);i+=2;continue
        if char=="#":
            token=text[i+1:i+4]
            if len(token)!=3 or not token.isascii() or not token.isdigit() or int(token)>255:
                raise ValueError("Use #000–#255 for decimal bytes or ## for a literal #.")
            flush();out.append(int(token));i+=4
        elif char=="$":
            token=text[i+1:i+3]
            if not re.fullmatch(r"[0-9a-fA-F]{2}",token):raise ValueError("Use $HH for a hex byte or $$ for a literal $.")
            flush();out.append(int(token,16));i+=3
        elif char=="<":
            end=text.find(">",i+1);name=text[i+1:end].upper() if end>=0 else ""
            if name not in names:raise ValueError("Use a named control such as <CR>, <LF>, <STX>, or << for a literal <.")
            flush();out.append(names[name]);i=end+1
        else:literal.append(char);i+=1
    flush();return bytes(out)

def checksum(data, name):
    if name == "None": return b""
    if name == "SUM8": return bytes([sum(data) & 255])
    if name == "LRC8": return bytes([-sum(data) & 255])
    if name == "XOR8":
        v = 0
        for b in data: v ^= b
        return bytes([v])
    if name == "CRC16 Modbus": return struct.pack("<H", crc16_modbus(data))
    if name == "CRC16 CCITT": return struct.pack(">H", binascii.crc_hqx(data, 0xFFFF))
    if name == "CRC32": return struct.pack("<I", binascii.crc32(data))
    raise ValueError(f"Unknown checksum: {name}")

def encode(text, mode="Text", encoding="utf-8", ending="None", check="None",
           prefix="", suffix=""):
    if mode == "Hex": data = parse_hex(text)
    elif mode == "Hercules":data=hercules_text(text,encoding)
    elif mode == "Decimal":
        try: data = bytes(int(v) for v in re.split(r"[\s,]+", text.strip()) if v)
        except (ValueError, OverflowError):
            raise ValueError("Decimal bytes must be integers between 0 and 255.") from None
    elif mode == "Escaped": data = escaped(text, encoding)
    else: data = text.encode(encoding)
    body = parse_hex(prefix) + data
    return body + checksum(body, check) + parse_hex(suffix) + {
        "None": b"", "LF": b"\n", "CR": b"\r", "CRLF": b"\r\n"}[ending]

def visible(data, encoding="utf-8"):
    text = data.decode(encoding, errors="replace")
    return "".join(f"⟨{CONTROLS.get(ord(c), f'{ord(c):02X}')}⟩"
                   if ord(c) < 32 or ord(c) == 127 else c for c in text)

def hexdump(data, base=0):
    lines = []
    for offset in range(0, len(data), 16):
        part = data[offset:offset+16]
        h = " ".join(f"{b:02X}" for b in part)
        ascii_ = "".join(chr(b) if 32 <= b < 127 else "." for b in part)
        lines.append(f"{offset+base:08X}  {h:<47}  |{ascii_}|")
    return "\n".join(lines)

class Framer:
    """Display-only grouping. TCP read boundaries are not message boundaries."""
    def __init__(self, mode="Chunks", delimiter=b"\n", size=16, idle=0.05):
        self.mode, self.delimiter, self.size, self.idle = mode, delimiter, size, idle
        self.buffer = bytearray()
        self.last = 0.0
        if mode == "Delimiter" and not delimiter: raise ValueError("Delimiter cannot be empty.")
        if mode == "Fixed length" and size < 1: raise ValueError("Frame size must be positive.")

    def feed(self, data, now):
        self.last = now
        if self.mode == "Chunks": return [data]
        self.buffer.extend(data)
        result = []
        if self.mode == "Delimiter":
            while True:
                idx = self.buffer.find(self.delimiter)
                if idx < 0: break
                end = idx + len(self.delimiter)
                result.append(bytes(self.buffer[:end])); del self.buffer[:end]
        elif self.mode == "Fixed length":
            while len(self.buffer) >= self.size:
                result.append(bytes(self.buffer[:self.size])); del self.buffer[:self.size]
        # Keep incomplete or hostile streams bounded; marked partial by the caller.
        if len(self.buffer) >= 65536: result.extend(self.flush())
        return result

    def tick(self, now):
        return self.flush() if self.mode == "Idle gap" and now - self.last >= self.idle else []

    def flush(self):
        if not self.buffer: return []
        data = bytes(self.buffer); self.buffer.clear(); return [data]
