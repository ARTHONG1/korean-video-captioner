import re
from dataclasses import dataclass
from difflib import SequenceMatcher


@dataclass(frozen=True)
class ValidatedTip:
    accepted: bool
    items: tuple[dict, ...]
    reasons: tuple[str, ...]


def _tokens(s):
    return re.findall(r'https?://[^\s]+|[A-Za-z]+[A-Za-z0-9._-]*|\d[\d,.:-]*', s)


def validate_tip_proposal(region, proposal):
    reasons = []
    items = proposal.get('items', []) if isinstance(proposal, dict) else []
    if proposal.get('region_id') != region.id:
        reasons.append('region_id')
    if proposal.get('decision') != 'accept':
        reasons.append('review')
    if not 1 <= len(items) <= 5:
        reasons.append('item_count')
    seen = set()
    good = []
    source_by_id = dict(zip(region.source_cue_ids, region.source_texts))
    for item in items:
        text = item.get('text', '')
        ids = item.get('source_cue_ids', [])
        if item.get('id') in seen or not text or len(text) > 32 or not ids or not set(ids).issubset(region.source_cue_ids):
            reasons.append('invalid_item')
            continue
        item_source = ' '.join(source_by_id.get(i, '') for i in ids)
        if any(t not in _tokens(text) for t in set(_tokens(item_source))):
            reasons.append('protected_token')
            continue
        if SequenceMatcher(None, item_source.replace(' ', ''), text.replace(' ', '')).ratio() < .30:
            reasons.append('ungrounded')
            continue
        seen.add(item.get('id'))
        good.append(item)
    return ValidatedTip(not reasons and bool(good), tuple(good), tuple(reasons))
