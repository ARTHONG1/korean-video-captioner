"""Source-time -> output-time mapping for compact edits and intro joins.

A timeline file sits next to its video (VIDEO.timeline.json). Pieces are in output frames of the edited
video; offset_frames shifts the whole map (an intro prepended in front).
"""
from __future__ import annotations

import json
import math
from fractions import Fraction
from pathlib import Path


def timeline_path(video: Path) -> Path:
    return Path(video).with_suffix(".timeline.json")


def load_timeline(video: Path) -> dict | None:
    path = timeline_path(video)
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None


def talk_modulus(talk_speed: float) -> int:
    """1.1x drops 1 frame in 11. Returns 0 when speech is not sped up."""
    if talk_speed <= 1.0001:
        return 0
    return int(round(1.0 / (talk_speed - 1.0))) + 1


def kept_count(kind: str, n: int, k: int, modulus: int) -> int:
    if kind == "cut":
        return 0
    if kind == "talk":
        return n - (n // modulus if modulus else 0)
    if kind == "copy":
        return n
    return -(-n // k)


def src_to_out_frames(tl: dict, t: float) -> int:
    fps = Fraction(tl["fps"])
    modulus = int(tl.get("talk_modulus", 0))
    offset = int(tl.get("offset_frames", 0))
    pieces = tl.get("pieces", [])
    if not pieces:
        return offset + int(round(t * fps))
    for p in pieces:
        if p["src_t0"] - 1e-6 <= t < p["src_t1"]:
            f = max(0, int(round((t - p["src_t0"]) * fps)))
            if p["kind"] == "cut":
                return offset + p["out0"]
            if p["kind"] == "talk":
                return offset + p["out0"] + f - (f // modulus if modulus else 0)
            if p["kind"] == "copy":
                return offset + p["out0"] + f
            return offset + p["out0"] + math.ceil(f / p["k"])
    if t < pieces[0]["src_t0"]:
        return offset
    last = pieces[-1]
    return offset + last["out0"] + last["nout"]


def src_to_out_seconds(tl: dict | None, t: float) -> float:
    if tl is None:
        return t
    return float(src_to_out_frames(tl, t) / Fraction(tl["fps"]))
