import subprocess
from pathlib import Path
from kvc.paths import RuntimePaths
from kvc.render import render_captions


def transcribe(video: Path, output: Path, paths: RuntimePaths):
    script = Path(__file__).with_name('transcribe_faster_whisper.py')
    cmd = [str(paths.python), str(script), str(video), str(output)]
    return subprocess.run(cmd, check=True, capture_output=True, text=True, encoding='utf-8')


def render(video: Path, subtitles: Path, output: Path, paths: RuntimePaths, margin_v: int | None = None):
    # Captions use the shared caption_style (white box, 7% font, video-pixel geometry); margin_v is px at 1080p.
    return render_captions(video, subtitles, output, paths, margin_v=margin_v)
