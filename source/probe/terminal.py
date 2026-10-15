"""Bounded ANSI/VT screen and incremental decoding, independent of the GUI."""
import codecs
import copy

try:
    import pyte
except ImportError:
    pyte = None

if pyte:
    class TerminalScreen(pyte.HistoryScreen):
        def __init__(self, columns, lines, **kwargs):
            self.alternate = None
            self.responses = []
            super().__init__(columns, lines, **kwargs)

        def write_process_input(self, text):
            # DSR/DA replies are sent only if interactive keyboard input is enabled.
            if len(self.responses) < 32:
                self.responses.append(text.encode("ascii"))

        def set_mode(self, *modes, **kwargs):
            if kwargs.get("private") and any(m in (47, 1047, 1049) for m in modes):
                if self.alternate is None:
                    fields=("buffer","cursor","margins","mode","savepoints","history",
                            "charset","g0_charset","g1_charset","tabstops")
                    self.alternate={name:copy.deepcopy(getattr(self,name)) for name in fields if hasattr(self,name)}
                    self.reset()
                modes=tuple(m for m in modes if m not in (47,1047,1049))
            if modes:super().set_mode(*modes,**kwargs)

        def reset_mode(self, *modes, **kwargs):
            if kwargs.get("private") and any(m in (47,1047,1049) for m in modes):
                if self.alternate is not None:
                    for name,value in self.alternate.items():setattr(self,name,value)
                    self.alternate=None
                    self.dirty.update(range(self.lines))
                modes=tuple(m for m in modes if m not in (47,1047,1049))
            if modes:super().reset_mode(*modes,**kwargs)

class EscapeFilter:
    """Bound unfinished terminal control strings before passing them to pyte."""
    def __init__(self):
        self.state="text";self.buffer=[];self.discard=False;self.string_kind=""

    def feed(self,text):
        out=[]
        def finish():
            if not self.discard:out.extend(self.buffer)
            self.state="text";self.buffer=[];self.discard=False
        for char in text:
            if self.state=="text":
                if char=="\x1b":self.state="escape";self.buffer=[char]
                elif char=="\x9b":self.state="csi";self.buffer=["\x1b","["]
                elif char=="\x9d":self.state="string";self.string_kind="]";self.buffer=["\x1b","]"]
                elif char in "\x90\x98\x9e\x9f":self.state="string";self.string_kind="P";self.discard=True;self.buffer=[]
                else:out.append(char)
            elif self.state=="escape":
                self.buffer.append(char)
                if char=="[":self.state="csi"
                elif char in "]PX^_":
                    self.state="string";self.string_kind=char
                    if char!="]":self.discard=True;self.buffer=[]
                else:finish()
            elif self.state=="csi":
                if not self.discard:self.buffer.append(char)
                if len(self.buffer)>256:self.discard=True;self.buffer=[]
                if "@"<=char<="~":finish()
                elif char=="\x1b":self.state="escape";self.buffer=[char];self.discard=False
            else:
                was_escape=self.state=="string_escape"
                if not self.discard:self.buffer.extend(["\x1b","\\"] if char=="\x9c" else [char])
                if len(self.buffer)>4096:self.discard=True;self.buffer=[]
                if char=="\x9c" or was_escape and char=="\\" or self.string_kind=="]" and char=="\x07":finish()
                else:self.state="string_escape" if char=="\x1b" else "string"
        return "".join(out)

class TerminalModel:
    def __init__(self, columns=100, lines=24, encoding="utf-8"):
        if pyte is None:raise RuntimeError("Live terminal requires pyte. Install requirements.txt.")
        self.screen=TerminalScreen(columns,lines,history=1000,ratio=.5)
        self.stream=pyte.Stream(self.screen)
        self.encoding=encoding
        self.decoder=codecs.getincrementaldecoder(encoding)(errors="replace")
        self.revision=0
        self.filter=EscapeFilter()

    def feed(self,data):
        # An unfinished UTF-8 character or escape sequence survives the next read.
        self.stream.feed(self.filter.feed(self.decoder.decode(data)))
        self.revision+=1
        replies=self.screen.responses[:];self.screen.responses.clear()
        return replies

    def reset(self,encoding=None):
        self.encoding=encoding or self.encoding
        self.decoder=codecs.getincrementaldecoder(self.encoding)(errors="replace")
        self.screen.alternate=None
        self.screen.reset();self.screen.responses.clear()
        self.stream=pyte.Stream(self.screen)
        self.filter=EscapeFilter()
        self.revision+=1

    def resize(self,columns,lines):
        self.screen.resize(lines=max(4,min(80,lines)),columns=max(20,min(240,columns)))

def key_bytes(keysym,char="",control=False,encoding="utf-8",enter="CR",backspace="DEL",application_cursor=False):
    if control and len(keysym)==1:
        code=ord(keysym.upper())
        if 64<=code<=95:return bytes([code&31])
        if keysym==" ":return b"\x00"
    arrows={"Up":"A","Down":"B","Right":"C","Left":"D"}
    if keysym in arrows:return ("\x1bO" if application_cursor else "\x1b[").encode()+arrows[keysym].encode()
    special={"Return":{"CR":b"\r","LF":b"\n","CRLF":b"\r\n"}[enter],
             "BackSpace":b"\x08" if backspace=="BS" else b"\x7f","Tab":b"\t","Escape":b"\x1b",
             "Home":b"\x1b[H","End":b"\x1b[F","Delete":b"\x1b[3~","Insert":b"\x1b[2~",
             "Prior":b"\x1b[5~","Next":b"\x1b[6~","F1":b"\x1bOP","F2":b"\x1bOQ",
             "F3":b"\x1bOR","F4":b"\x1bOS","F5":b"\x1b[15~","F6":b"\x1b[17~",
             "F7":b"\x1b[18~","F8":b"\x1b[19~","F9":b"\x1b[20~","F10":b"\x1b[21~",
             "F11":b"\x1b[23~","F12":b"\x1b[24~"}
    if keysym in special:return special[keysym]
    return char.encode(encoding) if char and char.isprintable() else b""
