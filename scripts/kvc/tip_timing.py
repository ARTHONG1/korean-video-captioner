from dataclasses import dataclass
@dataclass(frozen=True)
class TipFrame:
    start_ms:int; end_ms:int; visible_item_ids:tuple[int,...]
def schedule_tip_items(region,items,cues):
    starts={c.id:c.start_ms for c in cues}; ordered=sorted(items,key=lambda x:(min(starts[i] for i in x['source_cue_ids']),x['id']))
    out=[]
    for n,item in enumerate(ordered):
        start=region.start_ms if n==0 else min(starts[i] for i in item['source_cue_ids']); end=region.end_ms if n+1==len(ordered) else min(starts[i] for i in ordered[n+1]['source_cue_ids'])
        if end>start: out.append(TipFrame(start,end,tuple(x['id'] for x in ordered[:n+1])))
    return out
