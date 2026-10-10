"""Caption look shared by every caption render path.

All sizes are in the video's own pixel grid (ASS PlayResX/Y = video size). Box presets draw one rounded box
per caption event, sized from measured text width, so a two-line caption sits on a single clean card.
Research basis and rules: references/caption-style.md.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

from .publish_profile import load_publish_profile

PRESETS = {
    # white card, near-black bold text, hairline grey edge and a soft shadow so the card stays visible on white pages
    "white-box": {"has_box": True, "text": "&H00141414", "box": "&H00FFFFFF", "box_alpha": "&H00&", "edge": "&H00C8C8C8", "edge_px": 1.5,
                  "shadow_alpha": "&HA8&"},
    "dark-box": {"has_box": True, "text": "&H00FFFFFF", "box": "&H00000000", "box_alpha": "&H30&", "edge": "&H00000000", "edge_px": 0,
                 "shadow_alpha": "&HFF&"},
    "outline": {"has_box": False, "text": "&H00FFFFFF", "box": None, "box_alpha": None, "edge": "&H00000000", "edge_px": 0,
                "shadow_alpha": "&H96&"},
}
MIN_EVENT_MS = 700
# Words that should not end a line: they modify the next word ("이런 | 식으로" reads badly).
NO_LINE_END = {"이런", "그런", "저런", "어떤", "이", "그", "저", "무슨", "새", "각", "몇", "모든", "온갖", "다른", "약간", "좀", "더",
               "아주", "너무", "진짜", "정말", "막", "제", "내", "우리", "이번", "다음", "한", "두", "세", "그냥", "되게", "한번", "또"}


@dataclass(frozen=True)
class CaptionStyle:
    preset: str = "white-box"
    font_ratio: float = 0.075
    margin_ratio_landscape: float = 0.15
    margin_ratio_portrait: float = 0.2
    side_ratio: float = 0.1
    max_line_units: float = 16
    max_lines: int = 2
    reserved_zones: tuple = field(default_factory=tuple)
    margin_v_px: int | None = None  # explicit override in pixels of a 1080-high frame

    def metrics(self, width: int, height: int) -> dict:
        if self.preset not in PRESETS:
            raise ValueError(f"unknown caption preset: {self.preset}")
        short = min(width, height)
        font = max(18, round(short * self.font_ratio))
        portrait = height > width
        if self.margin_v_px is not None:
            margin_v = round(self.margin_v_px * height / 1080)
        else:
            margin_v = round(height * (self.margin_ratio_portrait if portrait else self.margin_ratio_landscape))
        p = PRESETS[self.preset]
        return {"font_size": font, "margin_v": margin_v, "margin_l": round(width * self.side_ratio), "margin_r": round(width * self.side_ratio),
                "pad_x": round(font * 0.42), "pad_y": round(font * 0.24), "radius": round(font * 0.3), "line_gap": round(font * 0.06),
                "shadow": max(2, round(font * 0.05)), "outline": 0 if p["has_box"] else max(2, round(font * 0.06)),
                "portrait": portrait, "preset": self.preset, **{k: v for k, v in p.items()}}


def caption_style_from_profile(profile: dict | None = None, **overrides) -> CaptionStyle:
    data = dict((profile or load_publish_profile()).get("caption_style", {}))
    data.update({k: v for k, v in overrides.items() if v is not None})
    known = set(CaptionStyle.__dataclass_fields__)
    data = {k: v for k, v in data.items() if k in known}
    if "reserved_zones" in data:
        data["reserved_zones"] = tuple(tuple(float(x) for x in z) for z in data["reserved_zones"])
    return CaptionStyle(**data)


def weighted_units(text: str) -> float:
    """Netflix Korean counting: Hangul/CJK = 1, Latin, digits, spaces, punctuation = 0.5."""
    total = 0.0
    for ch in text:
        if "\uac00" <= ch <= "\ud7a3" or "\u3130" <= ch <= "\u318f" or "\u4e00" <= ch <= "\u9fff":
            total += 1.0
        else:
            total += 0.5
    return total


_BREAK_AFTER = re.compile(r"[,.?!…:;]$")


def _end_penalty(token: str) -> float:
    if _BREAK_AFTER.search(token):
        return -3.0
    return 4.0 if token in NO_LINE_END else 0.0


def _split_tokens(tokens: list[str], parts: int) -> list[list[str]]:
    if parts <= 1 or len(tokens) <= 1:
        return [tokens]
    units = [weighted_units(t) + 0.5 for t in tokens]
    total = sum(units)
    groups, start = [], 0
    for g in range(1, parts):
        target = total * g / parts
        best, best_cost = None, None
        for i in range(start, len(tokens) - (parts - g)):
            acc = sum(units[: i + 1])
            cost = abs(acc - target) + _end_penalty(tokens[i]) * total * 0.02
            if best_cost is None or cost < best_cost:
                best, best_cost = i, cost
        if best is None:
            break
        groups.append(tokens[start: best + 1])
        start = best + 1
    groups.append(tokens[start:])
    return [g for g in groups if g]


def _lines_for(tokens: list[str], max_units: float) -> list[str]:
    text = " ".join(tokens)
    if weighted_units(text) <= max_units or len(tokens) == 1:
        return [text]
    best = None
    for i in range(1, len(tokens)):
        a, b = " ".join(tokens[:i]), " ".join(tokens[i:])
        ua, ub = weighted_units(a), weighted_units(b)
        over = max(0.0, ua - max_units) + max(0.0, ub - max_units)
        cost = over * 10 + abs(ua - ub) + _end_penalty(tokens[i - 1])
        if best is None or cost < best[0]:
            best = (cost, [a, b])
    return best[1]


def layout_text(text: str, max_units: float, max_lines: int) -> list[list[str]]:
    tokens = " ".join(text.split()).split(" ") if text.strip() else []
    if not tokens:
        return []
    total = weighted_units(" ".join(tokens))
    parts = max(1, math.ceil(total / (max_units * max_lines * 0.92)))
    while True:
        events = [_lines_for(g, max_units) for g in _split_tokens(tokens, parts)]
        fits = all(len(lines) <= max_lines and all(weighted_units(l) <= max_units or " " not in l for l in lines) for lines in events)
        if fits or parts >= len(tokens):
            return events
        parts += 1


def split_cue(start_ms: int, end_ms: int, text: str, style: CaptionStyle, words: list[tuple[int, int]] | None = None):
    events = layout_text(text, style.max_line_units, style.max_lines)
    if len(events) <= 1:
        return [(start_ms, end_ms, events[0])] if events else []
    weights = [weighted_units(" ".join(lines)) for lines in events]
    total = sum(weights)
    gaps = []
    if words:
        inside = sorted(w for w in words if start_ms <= w[0] < end_ms)
        gaps = [(a[1] + b[0]) // 2 for a, b in zip(inside, inside[1:]) if b[0] >= a[1]]
    bounds, acc = [start_ms], 0.0
    for w in weights[:-1]:
        acc += w
        t = start_ms + round((end_ms - start_ms) * acc / total)
        near = [g for g in gaps if abs(g - t) <= 600 and g - bounds[-1] >= MIN_EVENT_MS and end_ms - g >= MIN_EVENT_MS]
        if near:
            t = min(near, key=lambda g: abs(g - t))
        bounds.append(max(bounds[-1] + 1, t))
    bounds.append(end_ms)
    return [(bounds[i], bounds[i + 1], events[i]) for i in range(len(events))]


def _ass_time(ms: int) -> str:
    cs = round(ms / 10)
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _escape(text: str) -> str:
    return text.replace("\\", "\uff3c").replace("{", "\\{").replace("}", "\\}")


def ass_header(width: int, height: int, style: CaptionStyle, font_family: str) -> list[str]:
    m = style.metrics(width, height)
    shadow = 0 if m["has_box"] else m["shadow"]
    back = "&H96000000"
    return [
        "[Script Info]", "ScriptType: v4.00+", f"PlayResX: {width}", f"PlayResY: {height}", "WrapStyle: 2",
        "ScaledBorderAndShadow: yes", "YCbCr Matrix: TV.709", "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, "
        "StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        f"Style: Caption,{font_family},{m['font_size']},{m['text']},{m['text']},{m['edge']},{back},-1,0,0,0,100,100,0,0,"
        f"1,{m['outline']},{shadow},2,{m['margin_l']},{m['margin_r']},{m['margin_v']},1",
        f"Style: CaptionBox,{font_family},20,&H00FFFFFF,&H00FFFFFF,&H00C8C8C8,&H00000000,0,0,0,0,100,100,0,0,1,0,0,7,0,0,0,1",
        "", "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]


def rounded_rect(w: float, h: float, r: float) -> str:
    r = max(0.0, min(r, w / 2, h / 2))
    k = r * 0.4477  # cubic Bezier approximation of a quarter circle (1 - 0.5523)
    f = lambda v: f"{v:.1f}".rstrip("0").rstrip(".")  # noqa: E731
    return (f"m {f(r)} 0 l {f(w - r)} 0 b {f(w - k)} 0 {f(w)} {f(k)} {f(w)} {f(r)} l {f(w)} {f(h - r)} "
            f"b {f(w)} {f(h - k)} {f(w - k)} {f(h)} {f(w - r)} {f(h)} l {f(r)} {f(h)} b {f(k)} {f(h)} 0 {f(h - k)} 0 {f(h - r)} "
            f"l 0 {f(r)} b 0 {f(k)} {f(k)} 0 {f(r)} 0")


def box_geometry(lines: list[str], width: int, style: CaptionStyle, m: dict, layout) -> tuple[float, float, float, float]:
    """(x0, y0, w, h) of the card around these lines, from measured libass text extents."""
    text_w = max(layout.line_width(l) for l in lines)
    n = len(lines)
    top = layout.top - (n - 1) * layout.line_height
    bottom = layout.bottom
    cx = width / 2 + (m["margin_l"] - m["margin_r"]) / 2
    w = text_w + 2 * m["pad_x"]
    h = (bottom - top) + 2 * m["pad_y"]
    return cx - w / 2, top - m["pad_y"], w, h


def build_caption_ass(cues, width: int, height: int, style: CaptionStyle, font_family: str, words=None, layout=None) -> tuple[str, dict]:
    """cues: start_ms, end_ms, text. layout: measured libass metrics (kvc.render.measure_layout); required for box presets."""
    m = style.metrics(width, height)
    if m["has_box"] and layout is None:
        raise ValueError("box presets need measured text layout (kvc.render.measure_layout)")
    lines = ass_header(width, height, style, font_family)
    report = {"events": 0, "split_cues": 0, "max_lines": 0, "max_line_units": 0.0, "max_box_width": 0, "fast_events": [],
              "metrics": m, "preset": style.preset}
    events = []
    for cue in cues:
        parts = split_cue(cue.start_ms, cue.end_ms, cue.text, style, words)
        if len(parts) > 1:
            report["split_cues"] += 1
        for a, b, text_lines in parts:
            events.append((a, b, text_lines))
            units = weighted_units("".join(text_lines).replace(" ", ""))
            secs = max(0.001, (b - a) / 1000)
            if units / secs > 14:
                report["fast_events"].append({"start_ms": a, "units_per_second": round(units / secs, 1)})
            report["max_lines"] = max(report["max_lines"], len(text_lines))
            report["max_line_units"] = max(report["max_line_units"], max(weighted_units(l) for l in text_lines))
    for a, b, text_lines in events:
        t0, t1 = _ass_time(a), _ass_time(b)
        if m["has_box"]:
            x0, y0, w, h = box_geometry(text_lines, width, style, m, layout)
            report["max_box_width"] = max(report["max_box_width"], round(w))
            edge = f"\\bord{m['edge_px']}\\3c{m['edge'][2:]}&" if m["edge_px"] else "\\bord0"
            tags = (f"{{\\an7\\pos({x0:.1f},{y0:.1f})\\p1\\1c{m['box'][2:]}&\\1a{m['box_alpha']}{edge}"
                    f"\\shad{m['shadow']}\\4c&H000000&\\4a{m['shadow_alpha']}\\blur0.6}}")
            lines.append(f"Dialogue: 0,{t0},{t1},CaptionBox,,0,0,0,,{tags}{rounded_rect(w, h, m['radius'])}{{\\p0}}")
        body = "\\N".join(_escape(l) for l in text_lines)
        lines.append(f"Dialogue: 1,{t0},{t1},Caption,,0,0,0,,{body}")
    report["events"] = len(events)
    report["fast_event_count"] = len(report["fast_events"])
    report["fast_events"] = report["fast_events"][:30]
    return "\n".join(lines) + "\n", report
