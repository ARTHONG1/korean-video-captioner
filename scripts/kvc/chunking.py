from __future__ import annotations


def plan_chunks(duration_ms: int, chunk_ms: int = 300_000, overlap_ms: int = 2_000) -> list[tuple[int, int]]:
    if duration_ms <= 0:
        raise ValueError("duration must be positive")
    if chunk_ms <= 0:
        raise ValueError("chunk must be positive")
    if overlap_ms < 0 or overlap_ms >= chunk_ms:
        raise ValueError("overlap must be smaller than chunk")
    if duration_ms <= chunk_ms:
        return [(0, duration_ms)]

    step_ms = chunk_ms - overlap_ms
    chunks: list[tuple[int, int]] = []
    start_ms = 0
    while start_ms < duration_ms:
        end_ms = min(start_ms + chunk_ms, duration_ms)
        chunks.append((start_ms, end_ms))
        if end_ms == duration_ms:
            break
        start_ms += step_ms
    return chunks
