import argparse,json
from pathlib import Path
from kvc.thumbnail import render_thumbnail
from kvc.youtube_profile import load_youtube_profile
p=argparse.ArgumentParser(); p.add_argument('metadata'); p.add_argument('profile'); p.add_argument('output'); a=p.parse_args()
render_thumbnail(json.loads(Path(a.metadata).read_text(encoding='utf-8')),load_youtube_profile(Path(a.profile)),Path(a.output))
