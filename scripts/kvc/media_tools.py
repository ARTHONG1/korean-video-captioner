"""Small FFmpeg helpers shared by compact editing and intro joining."""
from __future__ import annotations

import json
import re
import subprocess
import sys
import time
from fractions import Fraction
from pathlib import Path

import numpy as np

# Every segment that will later be joined with stream copy must use exactly these encoder settings,
# otherwise the H.264 parameter sets differ and players can break at the joint.
X264 = ["-c:v", "libx264", "-preset", "medium", "-crf", "20", "-color_range", "tv", "-colorspace", "bt709",
        "-color_primaries", "bt709", "-color_trc", "bt709"]
VIDEO_TAIL = "format=yuv420p,setsar=1,setparams=range=tv:color_primaries=bt709:color_trc=bt709:colorspace=bt709"
SR = 48000


def log(*args) -> None:
    print(time.strftime("%H:%M:%S"), *args, flush=True)


def sh(cmd: list, **kw) -> bytes:
    r = subprocess.run([str(c) for c in cmd], capture_output=True, **kw)
    if r.returncode != 0:
        sys.stderr.write(r.stderr.decode("utf-8", "replace")[-3000:])
        raise SystemExit("FAILED: " + " ".join(map(str, cmd[:8])))
    return r.stdout


def probe(ffprobe: Path, video: Path) -> dict:
    data = json.loads(sh([ffprobe, "-v", "error", "-show_streams", "-show_format", "-of", "json", video]).decode("utf-8", "replace"))
    v = next(s for s in data["streams"] if s["codec_type"] == "video")
    a = next((s for s in data["streams"] if s["codec_type"] == "audio"), None)
    return {"width": int(v["width"]), "height": int(v["height"]), "fps": Fraction(v["r_frame_rate"]),
            "time_base": Fraction(v["time_base"]), "pix_fmt": v.get("pix_fmt"), "has_audio": a is not None,
            "duration": float(data["format"].get("duration", 0))}


def packet_pts(ffprobe: Path, video: Path) -> np.ndarray:
    """Sorted video presentation times in seconds (one per frame)."""
    info = probe(ffprobe, video)
    rows = sh([ffprobe, "-v", "error", "-select_streams", "v:0", "-show_entries", "packet=pts", "-of", "csv=p=0", video]).decode().split()
    return np.array(sorted(int(x) for x in rows if x.strip().lstrip("-").isdigit()), dtype=np.float64) * float(info["time_base"])


def count_frames(ffprobe: Path, video: Path) -> int:
    out = sh([ffprobe, "-v", "error", "-count_packets", "-select_streams", "v:0", "-show_entries", "stream=nb_read_packets",
              "-of", "csv=p=0", video]).decode().strip()
    return int(out or 0)


def stream_duration(ffprobe: Path, video: Path, kind: str) -> float | None:
    out = sh([ffprobe, "-v", "error", "-select_streams", f"{kind}:0", "-show_entries", "stream=duration", "-of", "csv=p=0", video]).decode().strip()
    try:
        return float(out)
    except ValueError:
        return None


def extradata(ffprobe: Path, video: Path) -> str | None:
    out = sh([ffprobe, "-v", "error", "-select_streams", "v:0", "-show_streams", "-show_data", video]).decode("utf-8", "replace")
    m = re.search(r"extradata=\s*\n((?:[0-9a-f]{8}:.*\n)+)", out)
    return m.group(1) if m else None


def silences(ffmpeg: Path, media: Path, noise: str = "-40dB", min_d: float = 1.0) -> list[tuple[float, float]]:
    out = subprocess.run([str(ffmpeg), "-hide_banner", "-nostats", "-vn", "-i", str(media), "-af", f"silencedetect=noise={noise}:d={min_d}",
                          "-f", "null", "-"], capture_output=True).stderr.decode("utf-8", "replace")
    result, s0 = [], None
    for line in out.splitlines():
        m = re.search(r"silence_start: (-?[\d.]+)", line)
        if m:
            s0 = max(0.0, float(m.group(1)))
        m = re.search(r"silence_end: ([\d.]+)", line)
        if m and s0 is not None:
            result.append((s0, float(m.group(1))))
            s0 = None
    if s0 is not None:
        result.append((s0, float("inf")))
    return result


def samples_at(frame: int, fps: Fraction) -> int:
    return int(round(frame * SR / fps))


def fps_expr(fps: Fraction) -> str:
    return f"{fps.numerator}/{fps.denominator}"
