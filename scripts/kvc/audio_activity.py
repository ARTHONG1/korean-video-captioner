from __future__ import annotations

import re


_START = re.compile(r"silence_start:\s*([0-9]+(?:\.[0-9]+)?)")
_END = re.compile(r"silence_end:\s*([0-9]+(?:\.[0-9]+)?)")


def parse_silencedetect(log: str, *, duration: float) -> list[tuple[float, float]]:
    intervals: list[tuple[float, float]] = []
    start: float | None = None
    for line in log.splitlines():
        found_start = _START.search(line)
        found_end = _END.search(line)
        if found_start:
            start = min(float(found_start.group(1)), duration)
        elif found_end and start is not None:
            end = min(max(float(found_end.group(1)), start), duration)
            intervals.append((start, end))
            start = None
    if start is not None and start < duration:
        intervals.append((start, duration))
    return intervals


def silence_ratio(intervals: list[tuple[float, float]], duration: float) -> float:
    if duration <= 0:
        return 0.0
    covered = 0.0
    for start, end in sorted(intervals):
        covered += max(0.0, min(end, duration) - max(0.0, start))
    return min(1.0, covered / duration)
