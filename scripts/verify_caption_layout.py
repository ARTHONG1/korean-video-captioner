"""Deterministic caption layout gate: renders sampled caption events alone and measures them.

  verify_caption_layout.py --ass OUT.captions.ass --out caption-layout-verify.json [--samples 16]
Fails when a sampled caption (card included) leaves the frame safe area, uses more than the planned lines,
sits at an unexpected height, the text overflows its card, or it touches a profile reserved zone.
"""
import argparse
import json
import random
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from kvc.caption_style import caption_style_from_profile, weighted_units  # noqa: E402
from kvc.paths import RuntimePaths  # noqa: E402
from kvc.render import ink_box, render_probe  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ass", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--samples", type=int, default=16)
    a = ap.parse_args()
    paths = RuntimePaths.discover()
    ass = Path(a.ass).resolve()
    lines = ass.read_text(encoding="utf-8").splitlines()
    first = next((i for i, l in enumerate(lines) if l.startswith("Dialogue:")), len(lines))
    header = lines[:first]
    dialogues = [l for l in lines[first:] if l.startswith("Dialogue:")]
    texts = [l for l in dialogues if l.split(",", 4)[3] == "Caption"]
    boxes = {}
    for l in dialogues:
        f = l.split(",", 9)
        if f[3] == "CaptionBox":
            boxes[(f[1], f[2])] = l
    head = "\n".join(header)
    W = int(re.search(r"PlayResX: (\d+)", head).group(1))
    H = int(re.search(r"PlayResY: (\d+)", head).group(1))
    st = re.search(r"Style: Caption,([^\n]+)", head).group(1).split(",")
    font_size, margin_v = int(st[1]), int(st[20])
    style = caption_style_from_profile()

    def payload(e):
        return e.split(",", 9)[9]

    def units(e):
        return max(weighted_units(l) for l in payload(e).split("\\N"))

    random.seed(5)
    ranked = sorted(texts, key=units, reverse=True)
    sample = list(dict.fromkeys(ranked[: a.samples // 2] + random.sample(texts, min(len(texts), a.samples - a.samples // 2))))
    results, problems = [], []
    zones = [tuple(z) for z in style.reserved_zones]

    def at_zero(line):
        f = line.split(",", 9)
        f[1], f[2] = "0:00:00.00", "0:00:02.00"
        return ",".join(f)

    for e in sample:
        f = e.split(",", 9)
        box_line = boxes.get((f[1], f[2]))
        evs = ([at_zero(box_line)] if box_line else []) + [at_zero(e)]
        full = ink_box(render_probe(header, evs, W, H, paths.ffmpeg, ass.parent))
        text_only = ink_box(render_probe(header, [at_zero(e)], W, H, paths.ffmpeg, ass.parent, background="0xFF00FF"), (255, 0, 255))
        n_lines = payload(e).count("\\N") + 1
        item = {"text": payload(e), "lines": n_lines, "box": list(full) if full else None}
        issues = []
        if full is None:
            problems.append({**item, "issues": ["empty_render"]})
            continue
        if full[0] < W * 0.03 or full[2] > W * 0.97 or full[1] < H * 0.03 or full[3] > H * 0.99:
            issues.append("outside_safe_area")
        if n_lines > style.max_lines:
            issues.append("too_many_lines")
        if text_only and (text_only[3] - text_only[1]) > n_lines * font_size * 1.35:
            issues.append("wrapped_beyond_planned_lines")
        if abs(full[3] - (H - margin_v)) > font_size * 0.6:
            issues.append("unexpected_height")
        if box_line and text_only and (text_only[0] < full[0] + 4 or text_only[2] > full[2] - 4):
            issues.append("text_overflows_card")
        for z in zones:
            zx0, zy0, zx1, zy1 = z[0] * W, z[1] * H, z[2] * W, z[3] * H
            if full[0] < zx1 and full[2] > zx0 and full[1] < zy1 and full[3] > zy0:
                issues.append(f"overlaps_reserved_zone {list(z)}")
        if issues:
            problems.append({**item, "issues": issues})
        results.append(item)
    report = {"overall": "PASS" if not problems and results else "FAIL", "width": W, "height": H, "font_size": font_size,
              "margin_v": margin_v, "events_total": len(texts), "sampled": len(sample), "problems": problems,
              "widest_box": max(results, key=lambda x: x["box"][2] - x["box"][0]) if results else None}
    Path(a.out).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("overall", "events_total", "sampled", "font_size", "margin_v")}, ensure_ascii=False),
          "problems", len(problems))
    return 0 if report["overall"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
