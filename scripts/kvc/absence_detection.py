from __future__ import annotations

from typing import Iterable


Sample = tuple[float, bool]
Interval = tuple[float, float]


def _runs(samples: list[Sample]) -> list[tuple[int, int, bool]]:
    if not samples:
        return []
    runs: list[tuple[int, int, bool]] = []
    start = 0
    value = samples[0][1]
    for index in range(1, len(samples)):
        if samples[index][1] != value:
            runs.append((start, index, value))
            start, value = index, samples[index][1]
    runs.append((start, len(samples), value))
    return runs


def _step(samples: list[Sample]) -> float:
    gaps = [b[0] - a[0] for a, b in zip(samples, samples[1:]) if b[0] > a[0]]
    return min(gaps) if gaps else 1.0


def smooth_presence(
    samples: Iterable[Sample],
    *,
    present_island_merge_seconds: float = 10.0,
    absent_island_remove_seconds: float = 15.0,
) -> list[Sample]:
    result = list(samples)
    if not result:
        return []
    step = _step(result)
    changed = True
    while changed:
        changed = False
        for start, end, present in _runs(result):
            duration = (end - start) * step
            if present and start > 0 and end < len(result) and duration <= present_island_merge_seconds:
                result[start:end] = [(t, False) for t, _ in result[start:end]]
                changed = True
                break
            if not present and start > 0 and end < len(result) and duration <= absent_island_remove_seconds:
                result[start:end] = [(t, True) for t, _ in result[start:end]]
                changed = True
                break
    return result


def find_absence_candidates(samples: Iterable[Sample], *, min_seconds: float = 180.0) -> list[Interval]:
    values = list(samples)
    if not values:
        return []
    step = _step(values)
    candidates: list[Interval] = []
    for start, end, present in _runs(values):
        if present:
            continue
        duration = (end - start) * step
        if duration >= min_seconds:
            candidates.append((values[start][0], values[end - 1][0]))
    return candidates
