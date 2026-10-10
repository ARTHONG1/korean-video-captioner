from __future__ import annotations

from typing import Iterable

from .absence_models import TimelineSegment


def expected_duration(segments: Iterable[TimelineSegment]) -> float:
    return sum(segment.output_duration for segment in segments)


def build_timeline(segments: Iterable[TimelineSegment]) -> list[dict[str, float | str]]:
    output_time = 0.0
    result = []
    for segment in segments:
        duration = segment.output_duration
        result.append({
            "source_start": segment.source_start,
            "source_end": segment.source_end,
            "output_start": output_time,
            "output_end": output_time + duration,
            "action": segment.action.value,
            "speed": segment.speed,
        })
        output_time += duration
    return result
