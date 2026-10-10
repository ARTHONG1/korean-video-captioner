import argparse,json
from pathlib import Path
from kvc.youtube_validation import validate_youtube_proposal
def main():
    p=argparse.ArgumentParser(); p.add_argument('source'); p.add_argument('proposal'); p.add_argument('output'); a=p.parse_args()
    s=json.loads(Path(a.source).read_text(encoding='utf-8')); q=json.loads(Path(a.proposal).read_text(encoding='utf-8')); r=validate_youtube_proposal(s,q)
    Path(a.output).write_text(json.dumps({'accepted':r.accepted,'metadata':r.metadata,'reviews':r.reviews},ensure_ascii=False,indent=2),encoding='utf-8'); return 0 if r.accepted else 2
if __name__=='__main__': raise SystemExit(main())
