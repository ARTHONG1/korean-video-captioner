import re, unicodedata
from dataclasses import dataclass
from .models import Cue

@dataclass(frozen=True)
class TipRegion:
    id: str; start_marker_id: int; end_marker_id: int; start_ms: int; end_ms: int; source_cue_ids: tuple[int,...]; source_texts: tuple[str,...]=()

@dataclass(frozen=True)
class TipReview:
    code: str; cue_id: int; message: str

# ASR often splits the word ("꿀 팁") and attaches an ending ("시작하겠습니다").
# The whole marker word is removed; "꿀팁 끝까지" is ordinary speech, not an end marker.
START=re.compile(r'꿀\s*팁\s*(?:을\s*)?시작[가-힣]*')
END=re.compile(r'꿀\s*팁\s*(?:을\s*)?끝(?!\s*까지)[가-힣]*')
def _clean(text):
    stripped=START.sub(' ',END.sub(' ',unicodedata.normalize('NFKC',text)))
    stripped=re.sub(r'\s+([,.!?])',r'\1',stripped)
    return re.sub(r'\s{2,}',' ',stripped).strip(' ,')

def detect_tip_regions(cues):
    regions=[]; reviews=[]; cleaned=[]; open_cue=None; start_idx=0; n=0
    for idx,cue in enumerate(cues):
        text=unicodedata.normalize('NFKC',cue.text); has_start=bool(START.search(text)); has_end=bool(END.search(text))
        if has_start and has_end: reviews.append(TipReview('same_cue_start_end',cue.id,'start and end marker share a cue')); cleaned.append(Cue(cue.id,cue.start_ms,cue.end_ms,_clean(cue.text))); continue
        if has_start:
            if open_cue is not None: reviews.append(TipReview('nested_start',cue.id,'nested start marker'))
            else: open_cue=cue; start_idx=idx
        if has_end:
            if open_cue is None: reviews.append(TipReview('orphan_end',cue.id,'end marker without start'))
            else:
                if cue.start_ms<=open_cue.start_ms: reviews.append(TipReview('invalid_interval',cue.id,'end is not after start'))
                else:
                    n+=1; source=cues[start_idx:idx+1]; ids=tuple(x.id for x in source); regions.append(TipRegion(f'tip-{n:04d}',open_cue.id,cue.id,open_cue.start_ms,cue.end_ms,ids,tuple(x.text for x in source)))
                open_cue=None
        cleaned.append(Cue(cue.id,cue.start_ms,cue.end_ms,_clean(cue.text)))
    if open_cue is not None: reviews.append(TipReview('missing_end',open_cue.id,'start marker has no end'))
    return regions,cleaned,reviews

