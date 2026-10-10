"""Contact sheet of real video frames with the caption style burned in, for Codex visual review.

  caption_preview.py --video V --srt S --out sheet.jpg [--times 35,383,...] [--count 6]
                     [--presets white-box,dark-box] [--margin-v PX@1080] [--words words.json]
Without --times, picks cues spread across the video plus the widest cue. One row per preset.
"""
import argparse
import io
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parent))
from kvc.caption_style import caption_style_from_profile, weighted_units  # noqa: E402
from kvc.font import bundled_font  # noqa: E402
from kvc.paths import RuntimePaths  # noqa: E402
from kvc.render import caption_fonts_dir, filter_path, load_words, probe_video, styled_ass  # noqa: E402
from kvc.srt import parse_srt  # noqa: E402
from kvc.style import caption_margin_v  # noqa: E402


def pick_times(cues, count):
    if not cues:
        return []
    step = max(1, len(cues) // count)
    chosen = [cues[i] for i in range(step // 2, len(cues), step)][: count - 1]
    widest = max(cues, key=lambda c: weighted_units(c.text))
    if widest not in chosen:
        chosen.append(widest)
    return sorted((c.start_ms + min(1200, (c.end_ms - c.start_ms) // 3)) / 1000 for c in chosen)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", required=True)
    ap.add_argument("--srt", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--times")
    ap.add_argument("--count", type=int, default=6)
    ap.add_argument("--presets")
    ap.add_argument("--margin-v", type=int)
    ap.add_argument("--words")
    ap.add_argument("--width", type=int, default=640)
    a = ap.parse_args()
    paths = RuntimePaths.discover()
    out = Path(a.out).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    info = probe_video(Path(a.video), paths.ffprobe)
    cues = parse_srt(Path(a.srt).read_text(encoding="utf-8-sig"))
    times = [float(x) for x in a.times.split(",")] if a.times else pick_times(cues, a.count)
    base = caption_style_from_profile(margin_v_px=caption_margin_v(a.margin_v))
    presets = a.presets.split(",") if a.presets else [base.preset]
    font = bundled_font()
    words = load_words(Path(a.words)) if a.words else None
    try:
        label_font = ImageFont.truetype(str(font.path), 22)
    except Exception:
        label_font = ImageFont.load_default()
    rows = []
    for preset in presets:
        style = caption_style_from_profile(preset=preset, margin_v_px=base.margin_v_px)
        text, _ = styled_ass(cues, info["width"], info["height"], style, paths.ffmpeg, out.parent, words)
        ass = out.parent / f"{out.stem}.{preset}.ass"
        ass.write_text(text, encoding="utf-8")
        row = []
        for t in times:
            cmd = [str(paths.ffmpeg), "-v", "error", "-ss", f"{t:.3f}", "-copyts", "-i", str(Path(a.video).resolve()), "-frames:v", "1",
                   "-vf", f"ass={filter_path(ass, out.parent)}:fontsdir={filter_path(caption_fonts_dir(), out.parent)},scale={a.width}:-2",
                   "-f", "image2pipe", "-c:v", "png", "-"]
            r = subprocess.run(cmd, cwd=str(out.parent), capture_output=True)
            if r.returncode != 0 or not r.stdout:
                raise SystemExit(r.stderr.decode("utf-8", "replace")[-1500:])
            im = Image.open(io.BytesIO(r.stdout)).convert("RGB")
            d = ImageDraw.Draw(im)
            s = int(t)
            label = f"{preset}  {s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}"
            d.rectangle([0, 0, 12 + int(d.textlength(label, font=label_font)), 30], fill=(0, 0, 0))
            d.text((6, 3), label, fill=(255, 230, 0), font=label_font)
            row.append(im)
        rows.append(row)
    w, h = rows[0][0].size
    cols = len(times)
    sheet = Image.new("RGB", (cols * w + (cols - 1) * 6, len(rows) * h + (len(rows) - 1) * 6), (30, 30, 30))
    for ri, row in enumerate(rows):
        for ci, im in enumerate(row):
            sheet.paste(im, (ci * (w + 6), ri * (h + 6)))
    sheet.save(out, quality=88)
    print(out, sheet.size, "times", ",".join(f"{t:.1f}" for t in times))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
