"""Burn styled captions (and optional tip-card ASS) into a video.

Every path handed to FFmpeg is relative to the working directory, so drive letters never reach the filter
parser. Box sizes come from measuring how libass actually draws the caption font at this size.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path

import numpy as np
from PIL import ImageFont

from .caption_style import CaptionStyle, ass_header, build_caption_ass, caption_style_from_profile
from .font import bundled_font, caption_font
from .srt import parse_srt
from .style import caption_margin_v


def _quote(value: str) -> str:
    return "'" + value.replace("'", "'\\''") + "'"


def filter_path(path: Path, cwd: Path) -> str:
    """Relative, forward-slash, quoted path for a filter argument. Copies the file next to cwd across drives."""
    path, cwd = Path(path).resolve(), Path(cwd).resolve()
    try:
        rel = os.path.relpath(path, cwd)
    except ValueError:
        local = cwd / ("_kvc_" + path.name)
        if path.is_dir():
            if not local.exists():
                shutil.copytree(path, local)
        elif not local.exists():
            shutil.copy2(path, local)
        rel = local.name
    return _quote(rel.replace("\\", "/"))


def caption_fonts_dir() -> Path:
    return caption_font().path.parent


def probe_video(video: Path, ffprobe: Path) -> dict:
    out = subprocess.run([str(ffprobe), "-v", "error", "-select_streams", "v:0", "-show_entries",
                          "stream=width,height,r_frame_rate,time_base,pix_fmt", "-show_entries", "format=duration",
                          "-of", "json", str(video)], capture_output=True, check=True).stdout
    data = json.loads(out.decode("utf-8", "replace"))
    s = data["streams"][0]
    return {"width": int(s["width"]), "height": int(s["height"]), "fps": str(Fraction(s["r_frame_rate"])),
            "time_base": s.get("time_base"), "pix_fmt": s.get("pix_fmt"), "duration": float(data["format"].get("duration", 0))}


def load_words(path: Path | None) -> list[tuple[int, int]] | None:
    if not path or not Path(path).is_file():
        return None
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    items = data.get("words", data) if isinstance(data, dict) else data
    words = []
    for w in items:
        try:
            words.append((int(w["start_ms"]), int(w["end_ms"])))
        except (KeyError, TypeError, ValueError):
            continue
    return words or None


def render_probe(header: list[str], events: list[str], width: int, height: int, ffmpeg: Path, workdir: Path,
                 background: str = "0x00FF00") -> np.ndarray:
    """Render ASS events alone on a flat background and return the RGB frame."""
    workdir = Path(workdir)
    probe = workdir / f"_kvc_probe_{os.getpid()}.ass"
    probe.write_text("\n".join(header) + "\n" + "\n".join(events) + "\n", encoding="utf-8")
    try:
        cmd = [str(ffmpeg), "-v", "error", "-f", "lavfi", "-i", f"color=c={background}:s={width}x{height}:d=1:r=1", "-vf",
               f"ass={filter_path(probe, workdir)}:fontsdir={filter_path(caption_fonts_dir(), workdir)}", "-frames:v", "1",
               "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
        r = subprocess.run(cmd, cwd=str(workdir), capture_output=True)
        img = np.frombuffer(r.stdout, np.uint8)
        if img.size != width * height * 3:
            raise RuntimeError("probe render failed: " + r.stderr.decode("utf-8", "replace")[-500:])
        return img.reshape(height, width, 3)
    finally:
        probe.unlink(missing_ok=True)


def ink_box(img: np.ndarray, background=(0, 255, 0)) -> tuple[int, int, int, int] | None:
    mask = np.abs(img.astype(np.int16) - np.array(background)).sum(axis=2) > 60
    ys, xs = np.nonzero(mask)
    if not len(xs):
        return None
    return int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())


@dataclass(frozen=True)
class MeasuredLayout:
    ratio: float
    top: float
    bottom: float
    line_height: float
    font_path: str
    font_size: int

    def line_width(self, text: str) -> float:
        font = ImageFont.truetype(self.font_path, self.font_size)
        left, _, right, _ = font.getbbox(text)
        return (right - left) * self.ratio


_LAYOUTS: dict = {}


def measure_layout(width: int, height: int, style: CaptionStyle, ffmpeg: Path, workdir: Path) -> MeasuredLayout:
    font = caption_font()
    m = style.metrics(width, height)
    key = (width, height, m["font_size"], m["margin_v"], m["margin_l"], m["margin_r"], str(font.path))
    if key in _LAYOUTS:
        return _LAYOUTS[key]
    header = ass_header(width, height, style, font.family)

    def ink(text):
        box = ink_box(render_probe(header, [f"Dialogue: 1,0:00:00.00,0:00:02.00,Caption,,0,0,0,,{text}"], width, height, ffmpeg, workdir))
        if box is None:
            raise RuntimeError("caption font rendered nothing; check the caption font directory")
        return box

    sample = "가나다라마바사아자차카타파하 AI Kiro 123"
    x0, _, x1, _ = ink(sample)
    pil = ImageFont.truetype(str(font.path), m["font_size"])
    left, _, right, _ = pil.getbbox(sample)
    _, top1, _, bottom1 = ink("가힣각뷁")
    _, top2, _, _ = ink("가힣각뷁\\N가힣각뷁")
    layout = MeasuredLayout((x1 - x0) / max(1, right - left), top1, bottom1, top1 - top2, str(font.path), m["font_size"])
    _LAYOUTS[key] = layout
    return layout


def styled_ass(cues, width: int, height: int, style: CaptionStyle, ffmpeg: Path, workdir: Path, words=None) -> tuple[str, dict]:
    m = style.metrics(width, height)
    layout = measure_layout(width, height, style, ffmpeg, workdir) if m["has_box"] else None
    text, report = build_caption_ass(cues, width, height, style, caption_font().family, words, layout)
    if layout:
        report["measured"] = {"width_ratio": round(layout.ratio, 4), "line_height": layout.line_height, "text_bottom": layout.bottom}
    return text, report


def write_caption_ass(srt: Path, video: Path, out_ass: Path, paths, style: CaptionStyle | None = None,
                      words_path: Path | None = None, margin_v: int | None = None) -> dict:
    info = probe_video(video, paths.ffprobe)
    style = style or caption_style_from_profile(margin_v_px=caption_margin_v(margin_v))
    cues = parse_srt(Path(srt).read_text(encoding="utf-8-sig"))
    text, report = styled_ass(cues, info["width"], info["height"], style, paths.ffmpeg, Path(out_ass).parent, load_words(words_path))
    Path(out_ass).write_text(text, encoding="utf-8")
    report.update({"video": str(video), "srt": str(srt), "ass": str(out_ass), "width": info["width"], "height": info["height"],
                   "style": dict(style.__dict__), "font": str(caption_font().path)})
    return report


def build_render_command(video: Path, caption_ass: Path, output: Path, ffmpeg: Path, cwd: Path, tip_ass: Path | None = None,
                         start: float | None = None, duration: float | None = None, crf: int = 20, threads: int | None = None,
                         progress: Path | None = None) -> list[str]:
    chain = [f"ass={filter_path(caption_ass, cwd)}:fontsdir={filter_path(caption_fonts_dir(), cwd)}"]
    if tip_ass:
        chain.append(f"ass={filter_path(tip_ass, cwd)}:fontsdir={filter_path(bundled_font().path.parent, cwd)}")
    pre, af = [], []
    if start is not None:
        # Input seek keeps absolute timestamps (copyts) so captions stay in sync, then rebase to zero.
        pre = ["-ss", f"{start:.3f}", "-copyts"] + (["-t", f"{duration:.3f}"] if duration else [])
        chain.append("setpts=PTS-STARTPTS")
        af = ["-af", "asetpts=PTS-STARTPTS"]
    cmd = [str(ffmpeg), "-y", "-hide_banner"] + (["-threads", str(threads)] if threads else []) + pre + ["-i", str(video),
           "-vf", ",".join(chain), "-map", "0:v:0", "-map", "0:a?"] + af + [
           "-c:v", "libx264", "-crf", str(crf), "-preset", "medium", "-pix_fmt", "yuv420p",
           "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart"]
    if progress:
        cmd += ["-nostats", "-progress", str(progress)]
    return cmd + [str(output)]


def render_captions(video, srt, output, paths, *, tip_ass=None, words=None, style: CaptionStyle | None = None, margin_v=None,
                    start=None, duration=None, crf=20, threads=None, progress=None, run=True) -> dict:
    video, srt, output = Path(video).resolve(), Path(srt).resolve(), Path(output).resolve()
    if output == video:
        raise ValueError("refusing to overwrite source video")
    if output.exists():
        raise FileExistsError(f"refusing to overwrite existing output: {output}")
    cwd = output.parent
    cwd.mkdir(parents=True, exist_ok=True)
    ass = cwd / (output.stem + ".captions.ass")
    report = write_caption_ass(srt, video, ass, paths, style, words, margin_v)
    (cwd / (output.stem + ".caption-layout.json")).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    cmd = build_render_command(video, ass, output, paths.ffmpeg, cwd, Path(tip_ass).resolve() if tip_ass else None, start, duration, crf,
                               threads, progress)
    (cwd / (output.stem + ".render-command.txt")).write_text(subprocess.list2cmdline(cmd), encoding="utf-8")
    if run:
        result = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True, encoding="utf-8", errors="replace")
        if result.returncode != 0:
            raise RuntimeError(result.stderr[-3000:])
    return {"output": str(output), "ass": str(ass), "command": cmd, "cwd": str(cwd), "layout": report}


# Backward-compatible entry points used by older per-run scripts.
def build_tip_render_command(video, bottom_srt, tip_ass, output, ffmpeg='ffmpeg', margin_v=None):
    from .paths import RuntimePaths
    paths = RuntimePaths.discover()
    out = Path(output).resolve()
    ass = out.parent / (out.stem + ".captions.ass")
    write_caption_ass(Path(bottom_srt), Path(video), ass, paths, None, None, margin_v)
    return build_render_command(Path(video), ass, out, Path(ffmpeg), out.parent, Path(tip_ass) if tip_ass else None)


def render_with_tips(video, bottom_srt, tip_ass, output, paths, margin_v=None):
    return render_captions(video, bottom_srt, output, paths, tip_ass=tip_ass, margin_v=margin_v)
