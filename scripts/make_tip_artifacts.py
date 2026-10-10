import json, sys
from pathlib import Path
from kvc.srt import parse_srt, write_srt
from kvc.tips import detect_tip_regions
from kvc.tip_timing import schedule_tip_items
from kvc.tip_validation import validate_tip_proposal
from kvc.ass import write_tip_ass


def main(run, proposals_dir=None):
    run = Path(run)
    cues = parse_srt((run / 'corrected.srt').read_text(encoding='utf-8-sig'))
    regions, cleaned, marker_reviews = detect_tip_regions(cues)
    (run / 'caption-without-markers.srt').write_text(write_srt(cleaned), encoding='utf-8-sig')
    reviews = [r.__dict__ for r in marker_reviews]
    proposal_dir = Path(proposals_dir) if proposals_dir else run / 'tip-proposals'
    proposal_map = {}
    for path in sorted(proposal_dir.glob('*.json')) if proposal_dir.exists() else []:
        data = json.loads(path.read_text(encoding='utf-8'))
        proposal_map[data.get('region_id')] = data
    tips, frames = [], []
    for region in regions:
        proposal = proposal_map.get(region.id, {'region_id': region.id, 'decision': 'review', 'items': []})
        validated = validate_tip_proposal(region, proposal)
        if not validated.accepted:
            reviews.append({'region_id': region.id, 'code': 'proposal_rejected', 'reasons': list(validated.reasons)})
            continue
        items = [dict(item) for item in validated.items]
        tips.append({'region_id': region.id, 'decision': 'accept', 'title': proposal.get('title', '꿀팁!'), 'items': items})
        frames.extend(schedule_tip_items(region, items, cues))
    (run / 'tips.json').write_text(json.dumps(tips, ensure_ascii=False, indent=2), encoding='utf-8')
    (run / 'tip-review.json').write_text(json.dumps(reviews, ensure_ascii=False, indent=2), encoding='utf-8')
    lookup = {item['id']: item['text'] for tip in tips for item in tip['items']}
    (run / 'tips.ass').write_text(write_tip_ass(frames, lookup), encoding='utf-8')


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
