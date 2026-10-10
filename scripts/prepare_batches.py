import argparse, json
from pathlib import Path
from kvc.srt import parse_srt
def main():
    p=argparse.ArgumentParser(); p.add_argument('--srt',required=True); p.add_argument('--output',required=True); a=p.parse_args()
    cues=parse_srt(Path(a.srt).read_text(encoding='utf-8-sig')); out=Path(a.output); out.mkdir(parents=True,exist_ok=True)
    for start in range(0,len(cues),20):
        items=cues[start:start+20]; obj={'schema_version':1,'batch_id':f'batch-{start//20+1:04d}','context_before':[],'items':[{'id':c.id,'start_ms':c.start_ms,'end_ms':c.end_ms,'raw_text':c.text} for c in items],'context_after':[]}
        if start: obj['context_before']=[{'id':cues[start-1].id,'raw_text':cues[start-1].text}]
        if start+20<len(cues): obj['context_after']=[{'id':cues[start+20].id,'raw_text':cues[start+20].text}]
        (out/f'{obj["batch_id"]}.json').write_text(json.dumps(obj,ensure_ascii=False,indent=2),encoding='utf-8')
if __name__=='__main__': main()
