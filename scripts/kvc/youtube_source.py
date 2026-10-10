import hashlib, json
from pathlib import Path
from .srt import parse_srt
from .compact_timeline import load_timeline, src_to_out_seconds
from .publish_profile import load_publish_profile

class SourceBundleError(ValueError): pass
def _sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def build_metadata_source(run, profile, final_video):
    run=Path(run); final_video=Path(final_video)
    if not final_video.is_file() or final_video.stat().st_size==0: raise SourceBundleError('final video missing or empty')
    srt=run/'corrected.srt'
    if not srt.is_file(): raise SourceBundleError('corrected transcript missing')
    cues=parse_srt(srt.read_text(encoding='utf-8'))
    # Chapter times: source cue time mapped through the final video's compact/intro timeline, if any.
    timeline=load_timeline(final_video)
    data={'schema_version':1,'cues':[{'id':c.id,'start_ms':c.start_ms,'end_ms':c.end_ms,'text':c.text,
                                      'out_start_ms':int(round(src_to_out_seconds(timeline,c.start_ms/1000)*1000))} for c in cues],
          'profile_facts':{k:getattr(profile,k,'') for k in ('channel_name','book_title','publisher','book_url')},
          'hashes':{'corrected_srt':_sha(srt),'final_video':_sha(final_video)}}
    intro=(timeline or {}).get('intro') or {}
    try:
        label=load_publish_profile().get('youtube',{}).get('intro_chapter_label','미리보기')
    except Exception:
        label='미리보기'
    data['chapter_settings']={'intro_ms':int(round(float(intro.get('seconds',0))*1000)),'intro_label':label,
                              'timeline':'compact+intro' if timeline and timeline.get('pieces') else ('intro' if intro else 'identity')}
    tips=run/'tips.json'
    if tips.is_file(): data['tips']=json.loads(tips.read_text(encoding='utf-8'))
    return data
