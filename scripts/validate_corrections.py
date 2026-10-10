import argparse,json
from pathlib import Path
from kvc.correction import validate_one
def main():
 p=argparse.ArgumentParser(); p.add_argument('--batch',required=True); p.add_argument('--proposal',required=True); p.add_argument('--review',required=True); a=p.parse_args(); batch=json.loads(Path(a.batch).read_text(encoding='utf-8')); prop=json.loads(Path(a.proposal).read_text(encoding='utf-8')); raw={x['id']:x['raw_text'] for x in batch['items']}; results=[]
 for x in prop.get('items',[]):
  if x.get('id') in raw:
   v=validate_one(raw[x['id']],x.get('corrected_text',''),x.get('decision'),{}); results.append({'id':x['id'],'raw_text':raw[x['id']],'proposed_text':x.get('corrected_text',''),'accepted':v.accepted,'reasons':list(v.reasons)})
 Path(a.review).write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
if __name__=='__main__': main()
