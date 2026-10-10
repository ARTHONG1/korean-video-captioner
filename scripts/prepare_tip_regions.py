import argparse, json
from pathlib import Path
from kvc.srt import parse_srt, write_srt
from kvc.tips import detect_tip_regions


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument('--srt', required=True)
    p.add_argument('--output', required=True)
    a = p.parse_args(argv)
    out = Path(a.output); out.mkdir(parents=True, exist_ok=True)
    cues = parse_srt(Path(a.srt).read_text(encoding='utf-8-sig'))
    regions, cleaned, reviews = detect_tip_regions(cues)
    (out / 'caption-without-markers.srt').write_text(write_srt(cleaned), encoding='utf-8-sig')
    payload = {'schema_version': 1, 'regions': [r.__dict__ | {'source_cue_ids': list(r.source_cue_ids), 'source_texts': list(r.source_texts)} for r in regions]}
    (out / 'markers.json').write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    (out / 'tip-review.json').write_text(json.dumps([r.__dict__ for r in reviews], ensure_ascii=False, indent=2), encoding='utf-8')
    batch_dir = out / 'tip-source-batches'; batch_dir.mkdir(exist_ok=True)
    for region in regions:
        lookup = {c.id: c for c in cues}
        obj = {'schema_version': 1, 'region_id': region.id, 'start_ms': region.start_ms, 'end_ms': region.end_ms,
               'cues': [{'id': i, 'start_ms': lookup[i].start_ms, 'end_ms': lookup[i].end_ms, 'text': lookup[i].text} for i in region.source_cue_ids]}
        (batch_dir / f'{region.id}.json').write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding='utf-8')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
