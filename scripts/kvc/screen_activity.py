from __future__ import annotations


def low_activity_ratio(
    windows: list[tuple[float, float]], *, mad_threshold: float = 0.012, p95_threshold: float = 0.020
) -> float:
    if not windows:
        return 0.0
    low = sum(1 for mad, p95 in windows if mad < mad_threshold and p95 < p95_threshold)
    return low / len(windows)
