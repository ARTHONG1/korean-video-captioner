import re
from .models import Cue

_TIME = re.compile(r'^(\d+):(\d\d):(\d\d),(\d{3}) --> (\d+):(\d\d):(\d\d),(\d{3})$')
def _ms(h, m, s, ms): return ((int(h)*60+int(m))*60+int(s))*1000+int(ms)
def _stamp(ms):
    h, rem = divmod(ms, 3600000); m, rem = divmod(rem, 60000); s, x = divmod(rem, 1000)
    return f'{h:02d}:{m:02d}:{s:02d},{x:03d}'
def parse_srt(text):
    blocks = re.split(r'\r?\n\r?\n+', text.lstrip('\ufeff').replace('\r\n','\n').strip()) if text.strip() else []
    out=[]; seen=set(); previous=-1
    for block in blocks:
        lines=block.split('\n')
        if len(lines)<3 or not lines[0].strip().isdigit(): raise ValueError('invalid SRT block')
        ident=int(lines[0]); match=_TIME.match(lines[1].strip())
        if not match: raise ValueError('invalid timestamp')
        a=_ms(*match.groups()[:4]); b=_ms(*match.groups()[4:])
        if ident in seen: raise ValueError('duplicate id')
        if b<=a: raise ValueError('non-positive duration')
        if a<previous: raise ValueError('overlap or backward time')
        cue=Cue(ident,a,b,'\n'.join(lines[2:]).strip())
        if not cue.text: raise ValueError('empty text')
        out.append(cue); seen.add(ident); previous=b
    return out
def write_srt(cues):
    # Return platform-neutral text; Path.write_text performs the Windows
    # newline translation once, avoiding CRCRLF and parser-breaking blanks.
    return '\n\n'.join(f'{c.id}\n{_stamp(c.start_ms)} --> {_stamp(c.end_ms)}\n{c.text}' for c in cues) + ('\n\n' if cues else '')
