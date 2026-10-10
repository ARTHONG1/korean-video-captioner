"""Burn the Skill caption style (and optional tip cards) into a video.

  render_captions.py --video V --srt S --out OUT.mp4 [--tips tips.ass] [--words words.json]
                     [--preset white-box|dark-box|outline] [--margin-v PX@1080] [--start S --duration D]
                     [--progress FILE] [--threads N] [--dry-run]
Writes OUT.captions.ass, OUT.caption-layout.json, and OUT.render-command.txt next to OUT. Never overwrites.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from kvc.caption_style import caption_style_from_profile  # noqa: E402
from kvc.paths import RuntimePaths  # noqa: E402
from kvc.render import render_captions  # noqa: E402
from kvc.style import caption_margin_v  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", required=True)
    ap.add_argument("--srt", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--tips")
    ap.add_argument("--words")
    ap.add_argument("--preset")
    ap.add_argument("--font-ratio", type=float)
    ap.add_argument("--margin-v", type=int, help="caption bottom margin in pixels of a 1080-high frame")
    ap.add_argument("--start", type=float)
    ap.add_argument("--duration", type=float)
    ap.add_argument("--progress")
    ap.add_argument("--threads", type=int)
    ap.add_argument("--crf", type=int, default=20)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    style = caption_style_from_profile(preset=a.preset, font_ratio=a.font_ratio, margin_v_px=caption_margin_v(a.margin_v))
    result = render_captions(a.video, a.srt, a.out, RuntimePaths.discover(), tip_ass=a.tips, words=a.words, style=style,
                             start=a.start, duration=a.duration, crf=a.crf, threads=a.threads, progress=a.progress, run=not a.dry_run)
    layout = result["layout"]
    print(json.dumps({"output": result["output"], "ass": result["ass"], "events": layout["events"], "split_cues": layout["split_cues"],
                      "max_lines": layout["max_lines"], "fast_events": layout["fast_event_count"], "metrics": layout["metrics"]},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
