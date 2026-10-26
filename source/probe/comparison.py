"""Bounded byte alignment; ignores preserve original offsets and original bytes."""
from dataclasses import asdict, dataclass
from difflib import SequenceMatcher

from .protocol import field_number, json_frame

MAX_COMPARE = 256 * 1024


@dataclass(frozen=True)
class Difference:
    kind: str
    a_start: int
    a_end: int
    b_start: int
    b_end: int


def parse_ranges(text):
    result = []
    for token in text.replace(",", " ").split():
        parts = token.split(":")
        if len(parts) != 2:raise ValueError("Use start:end byte ranges, for example 0:6 12:16 (end excluded).")
        a,b = (field_number(part, "Ignored offset", MAX_COMPARE) for part in parts)
        if b <= a:raise ValueError("Ignored range end must be greater than start.")
        result.append((a,b))
    if len(result) > 128:raise ValueError("Use at most 128 ignored ranges.")
    return result


def tokens(data, ranges, selectors):
    ignored = [(a,min(b,len(data)),("range",i)) for i,(a,b) in enumerate(ranges) if a < len(data)]
    if selectors:
        fields = json_frame(data)[1]
        available = {field.selector for field in fields if field.kind == "JSON"}
        missing = set(selectors)-available
        if missing:raise ValueError("Ignored JSON field not found: "+sorted(missing)[0])
        ignored.extend((field.offset, field.offset+field.size, ("json",field.selector)) for field in fields if field.selector in selectors)
    ignored.sort();last = 0;items = [];spans = []
    for begin,end,key in ignored:
        if begin < last:raise ValueError("Ignored fields/ranges overlap. Choose non-overlapping ranges.")
        for i in range(last,begin):items.append(data[i]);spans.append((i,i+1))
        items.append(key);spans.append((begin,end));last = end
    for i in range(last,len(data)):items.append(data[i]);spans.append((i,i+1))
    return items,spans


def compare_bytes(a, b, ranges=(), selectors=()):
    if not isinstance(a,bytes) or not isinstance(b,bytes):raise ValueError("Choose binary input bytes for A and B.")
    if len(a) > MAX_COMPARE or len(b) > MAX_COMPARE:raise ValueError("Compare supports up to 256 KiB per side. Select fewer chunks.")
    if len(ranges)>128 or len(selectors)>128:raise ValueError("Choose at most 128 ignored ranges/fields.")
    for begin,end in ranges:
        first=field_number(begin,"Ignored offset",MAX_COMPARE);last=field_number(end,"Ignored offset",MAX_COMPARE)
        if last<=first:raise ValueError("Ignored range end must be greater than start.")
    left, amap = tokens(a,ranges,selectors);right,bmap = tokens(b,ranges,selectors)
    def boundary(spans, index, size):return spans[index][0] if index < len(spans) else size
    # Trim exact token prefixes/suffixes before aligning the changing middle.
    first = 0
    while first < min(len(left),len(right)) and left[first] == right[first]:first += 1
    enda,endb = len(left),len(right)
    while enda > first and endb > first and left[enda-1] == right[endb-1]:enda -= 1;endb -= 1
    operations = [("equal",0,first,0,first)] if first else []
    operations += [(kind,i+first,j+first,k+first,l+first) for kind,i,j,k,l in
                   SequenceMatcher(None,left[first:enda],right[first:endb],autojunk=True).get_opcodes()]
    if enda < len(left):operations.append(("equal",enda,len(left),endb,len(right)))
    result = []
    for kind,i,j,k,l in operations:
        if kind == "equal":
            # A masked field is one alignment token even when its length differs.
            for ai,bi in zip(range(i,j),range(k,l)):
                aa,az = amap[ai];ba,bz = bmap[bi]
                label = "ignored" if isinstance(left[ai],tuple) else "equal"
                if result and result[-1].kind == label and result[-1].a_end == aa and result[-1].b_end == ba:
                    old = result[-1];result[-1] = Difference(label,old.a_start,az,old.b_start,bz)
                else:result.append(Difference(label,aa,az,ba,bz))
        else:
            result.append(Difference({"replace":"changed","insert":"added","delete":"removed"}[kind],
                         boundary(amap,i,len(a)),boundary(amap,j,len(a)),boundary(bmap,k,len(b)),boundary(bmap,l,len(b))))
    return tuple(result)


def comparison_report(a,b,differences,ranges=(),selectors=()):
    return dict(format="probe-comparison",version=1,a_hex=a.hex(),b_hex=b.hex(),ignored_ranges=list(ranges),
                ignored_json_fields=list(selectors),differences=[asdict(item) for item in differences])
