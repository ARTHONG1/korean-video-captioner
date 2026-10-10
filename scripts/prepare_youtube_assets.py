import argparse, json
from pathlib import Path
from kvc.youtube_profile import copy_personal_assets
def main():
    p=argparse.ArgumentParser(); p.add_argument('--book',required=True); p.add_argument('--character',required=True); p.add_argument('--destination',required=True); a=p.parse_args()
    d=Path(a.destination); manifest=copy_personal_assets(Path(a.book),Path(a.character),d)
    profile={'schema_version':1,'channel_name':'','language':'ko','book':{'title':'','publisher':'','url':''},'assets':{'book_image':'book-ai-agent.png','character_cutout':'character-cj-cutout.png'},'thumbnail':{'width':1280,'height':720},'default_hashtags':[],'description_footer_lines':[]}
    (d/'youtube-profile.template.json').write_text(json.dumps(profile,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(manifest,ensure_ascii=False,indent=2))
if __name__=='__main__': main()
