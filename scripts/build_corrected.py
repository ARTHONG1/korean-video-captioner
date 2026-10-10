import argparse, json
from pathlib import Path
from kvc.srt import parse_srt,write_srt
from kvc.correction import validate_one
from kvc.glossary import load_glossary
from kvc.quality import QualityReport, QualityWarning, write_quality_report

# Later directories win: first-pass proposals, then the editor pass, then the
# final resolution pass. The previous order let stale drafts overwrite resolutions.
PROPOSAL_PRECEDENCE = ('proposals', 'editor-proposals', 'resolution-proposals')


def collect_proposals(run: Path) -> dict:
    by = {}
    for root in PROPOSAL_PRECEDENCE:
        for f in sorted((run/root).glob('batch-*.json')):
            b = json.loads(f.read_text(encoding='utf-8'))
            for x in b.get('items', []):
                by[x['id']] = x
    return by


def main(run, glossary_path=None):
    run=Path(run); cues=parse_srt((run/'raw.srt').read_text(encoding='utf-8-sig'))
    glossary=load_glossary(Path(glossary_path) if glossary_path else None)
    by=collect_proposals(run)
    out=[]; review=[]; warnings=[]; glossary_hits=0
    for c in cues:
        x=by.get(c.id)
        if x:
            v=validate_one(c.text,x.get('corrected_text',''),x.get('decision','review'),glossary)
            text=v.final_text
        else:
            v=None; text=c.text
        if v is None or not v.accepted:
            # Keep raw speech but still apply the user's fixed spellings.
            fixed,hits=glossary.apply(c.text)
            if hits and validate_one(c.text,fixed,'accept',glossary).accepted:
                text=fixed; glossary_hits+=1
        out.append(type(c)(c.id,c.start_ms,c.end_ms,text))
        if v is not None and not v.accepted:
            review.append({'id':c.id,'raw_text':c.text,'proposed_text':x.get('corrected_text',''),'reasons':list(v.reasons)})
            warnings.append(QualityWarning(c.id,'correction_rejected',','.join(v.reasons)))
        elif v is None:
            warnings.append(QualityWarning(c.id,'missing_proposal','no correction proposal; raw text kept'))
    (run/'corrected.srt').write_text(write_srt(out),encoding='utf-8-sig'); (run/'review.json').write_text(json.dumps(review,ensure_ascii=False,indent=2),encoding='utf-8')
    (run/'correction-audit.json').write_text(json.dumps({'schema_version':1,'cue_count':len(out),'review_count':len(review),'missing_count':sum(1 for w in warnings if w.code=='missing_proposal'),'glossary_fallback_count':glossary_hits,'source':'raw.srt'},ensure_ascii=False,indent=2),encoding='utf-8')
    report=QualityReport.from_warnings(warnings,total=len(out))
    write_quality_report(run/'quality-report.json', report)
    return report


if __name__=='__main__':
    p=argparse.ArgumentParser(); p.add_argument('run'); p.add_argument('--glossary'); a=p.parse_args()
    main(a.run,a.glossary)

