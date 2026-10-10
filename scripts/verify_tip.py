import argparse, hashlib, json
from pathlib import Path
from kvc.srt import parse_srt


def verify_run(run, original_sha256='', video_probe=None):
    run = Path(run)
    required = ['raw.srt', 'corrected.srt', 'caption-without-markers.srt', 'tips.json', 'tips.ass', 'tip-review.json']
    present = {name: (run / name).is_file() and (run / name).stat().st_size > 0 for name in required}
    raw = parse_srt((run / 'raw.srt').read_text(encoding='utf-8-sig'))
    corrected = parse_srt((run / 'corrected.srt').read_text(encoding='utf-8-sig'))
    contract = len(raw) == len(corrected) and all((a.id, a.start_ms, a.end_ms) == (b.id, b.start_ms, b.end_ms) for a, b in zip(raw, corrected))
    result = {'schema_version': 1, 'required_files': present, 'raw_corrected_contract': contract,
              'raw_cue_count': len(raw), 'corrected_cue_count': len(corrected),
              'original_sha256': original_sha256, 'video_probe': video_probe or {}}
    (run / 'verify-tip.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    return result


if __name__ == '__main__':
    p = argparse.ArgumentParser(); p.add_argument('run'); p.add_argument('--original-sha256', default=''); a = p.parse_args()
    print(json.dumps(verify_run(a.run, a.original_sha256), ensure_ascii=False, indent=2))
