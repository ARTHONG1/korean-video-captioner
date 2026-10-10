from __future__ import annotations

from .absence_models import Action, TimelineSegment


def _num(value: float) -> str:
    return f"{value:.6f}".rstrip("0").rstrip(".")


def build_filter_graph(segments: list[TimelineSegment], *, has_audio: bool) -> str:
    kept = [segment for segment in segments if segment.action is not Action.CUT and segment.source_duration > 0]
    if not kept:
        return ""
    video_parts: list[str] = []
    audio_parts: list[str] = []
    for index, segment in enumerate(kept):
        start, end = _num(segment.source_start), _num(segment.source_end)
        video = f"[0:v]trim=start={start}:end={end},setpts=PTS-STARTPTS"
        audio = f"[0:a]atrim=start={start}:end={end},asetpts=PTS-STARTPTS"
        if segment.action is Action.SPEED_5X:
            video += ",setpts=(PTS-STARTPTS)/5"
            audio += ",atempo=2,atempo=2,atempo=1.25"
        video_parts.append(f"{video}[v{index}]")
        if has_audio:
            audio_parts.append(f"{audio}[a{index}]")
    if len(kept) == 1:
        single = video_parts[0].replace("[v0]", "[vout]")
        parts = [single]
        if has_audio:
            parts.append(audio_parts[0].replace("[a0]", "[aout]"))
        return ";".join(parts)
    inputs = "".join(f"[v{i}][a{i}]" for i in range(len(kept))) if has_audio else "".join(f"[v{i}]" for i in range(len(kept)))
    streams = "[vout][aout]" if has_audio else "[vout]"
    concat = f"{inputs}concat=n={len(kept)}:v=1:a={1 if has_audio else 0}{streams}"
    return ";".join(video_parts + audio_parts + [concat])
