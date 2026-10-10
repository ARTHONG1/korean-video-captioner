import json,re,sys
from pathlib import Path
def clean(s):
    s=re.sub(r'^(?:음|어|아|그니까|그러니까)[,、\s]+','',s).strip()
    s=re.sub(r'\b(네)\s+\1\b',r'\1',s)
    s=re.sub(r'\s+([,.!?])',r'\1',s)
    return s
def main(run):
    run=Path(run); out=run/'proposals'; out.mkdir(exist_ok=True)
    for b in sorted((run/'batches').glob('batch-*.json')):
        x=json.loads(b.read_text(encoding='utf-8')); x['items']=[{'id':i['id'],'corrected_text':clean(i['raw_text']),'decision':'requires_codex','reason':'기계적 정규화 제안이며 Codex 의미 교정이 필요함'} for i in x['items']]
        (out/b.name).write_text(json.dumps({'batch_id':x['batch_id'],'items':x['items']},ensure_ascii=False,indent=2),encoding='utf-8')
if __name__=='__main__': main(sys.argv[1])
