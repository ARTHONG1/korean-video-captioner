import re, unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher

from .glossary import Glossary

@dataclass(frozen=True)
class ValidatedItem:
    accepted: bool
    final_text: str
    reasons: tuple[str,...]

def _norm(s): return re.sub(r'\s+','',unicodedata.normalize('NFKC',s)).lower()
def _tokens(s): return re.findall(r'https?://[^\s]+|[A-Za-z]+[A-Za-z0-9._-]*|\d[\d,.:-]*', unicodedata.normalize('NFKC',s))

def _as_glossary(glossary):
    if isinstance(glossary, Glossary):
        return glossary
    if isinstance(glossary, dict) and glossary:
        return Glossary(tuple((str(v), (str(k),)) for k, v in glossary.items()))
    return Glossary()

def validate_one(raw_text, corrected_text, decision, glossary):
    """Accept a correction only if it keeps protected tokens and most of the raw text.

    Protected tokens (URLs, English identifiers, numbers) must survive, but ASCII
    case-only changes (kiro -> Kiro) and glossary canonical replacements are allowed.
    The similarity gates are measured against the glossary-normalised raw text so a
    whole-phrase glossary fix is not rejected as a rewrite.
    """
    reasons=[]
    if decision != 'accept': reasons.append('review_decision')
    if not isinstance(corrected_text,str) or not corrected_text.strip(): reasons.append('empty_text')
    if reasons: return ValidatedItem(False,raw_text,tuple(reasons))
    terms=_as_glossary(glossary)
    baseline,_=terms.apply(raw_text)
    new_tokens=_tokens(corrected_text); new_folded={t.casefold() for t in new_tokens}
    canon_folded={_norm(c) for c in terms.canonicals}
    corrected_norm=_norm(corrected_text)
    for t in _tokens(raw_text):
        if t.casefold() in new_folded:
            continue
        canonical=terms.canonical_for(t)
        if canonical and _norm(canonical) in corrected_norm:
            continue
        if any(t.casefold() in c for c in canon_folded if c in corrected_norm):
            continue
        reasons.append('protected_token_changed'); break
    similarity=SequenceMatcher(None,_norm(baseline),corrected_norm).ratio()
    if similarity < .55: reasons.append('similarity_below_threshold')
    deletion=max(0,len(_norm(baseline))-len(corrected_norm))/max(1,len(_norm(baseline)))
    if deletion > .35: reasons.append('deletion_ratio_exceeded')
    return ValidatedItem(not reasons, corrected_text if not reasons else raw_text, tuple(reasons))

