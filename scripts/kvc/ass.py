def _ts(ms):
    cs=round(ms/10); h,cs=divmod(cs,360000); m,cs=divmod(cs,6000); s,cs=divmod(cs,100); return f'{h}:{m:02d}:{s:02d}.{cs:02d}'
def write_tip_ass(frames,tips,font_family='Noto Sans KR'):
    lines=['[Script Info]','ScriptType: v4.00+','PlayResX: 1920','PlayResY: 1080','[V4+ Styles]','Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding',f'Style: TipTitle,{font_family},48,&H0000CCFF,&H0000CCFF,&H00000000,&H80000000,1,0,3,3,0,7,60,60,80,1',f'Style: TipBody,{font_family},34,&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,0,0,3,3,0,7,60,60,150,1','[Events]','Format: Layer, Start, End, Style, Name, MarginL, MarginR, Effect, Text']
    for f in frames:
        body='\\N'.join(f'{i}. {tips[i]}' for i in f.visible_item_ids); lines.append(f'Dialogue: 0,{_ts(f.start_ms)},{_ts(f.end_ms)},TipTitle,,0,0,,{{\\pos(60,80)}}꿀팁!\\N{{\\pos(60,145)}}{body}')
    return '\n'.join(lines)+'\n'
