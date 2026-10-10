from __future__ import annotations

from .absence_detection import find_absence_candidates, smooth_presence
from .absence_models import AbsenceConfig, Action, TimelineSegment
from .absence_policy import classify_absence
from .timeline_map import build_timeline


def analyze_timeline(
    *,
    duration: float,
    face_samples: list[tuple[float, bool]],
    silence_ratio_by_candidate: list[float | None],
    low_activity_ratio_by_candidate: list[float],
    screen_active_by_candidate: list[bool],
    config: AbsenceConfig | None = None,
) -> dict:
    config = config or AbsenceConfig()
    smoothed = smooth_presence(
        face_samples,
        present_island_merge_seconds=config.present_island_merge_seconds,
        absent_island_remove_seconds=config.absent_island_remove_seconds,
    )
    candidates = find_absence_candidates(smoothed, min_seconds=config.min_absence_seconds)
    decisions: list[dict] = []
    edits: list[TimelineSegment] = []
    cursor = 0.0
    for index, (start, end) in enumerate(candidates):
        keep_start = max(cursor, start)
        keep_end = min(duration, end + 1.0)
        editable_start = min(duration, keep_start + config.boundary_padding_seconds)
        editable_end = max(editable_start, keep_end - config.boundary_padding_seconds)
        if editable_start > cursor:
            edits.append(TimelineSegment(cursor, editable_start, Action.KEEP))
        action = classify_absence(
            silence_ratio=silence_ratio_by_candidate[index] if index < len(silence_ratio_by_candidate) else None,
            low_activity_ratio=low_activity_ratio_by_candidate[index] if index < len(low_activity_ratio_by_candidate) else 0.0,
            screen_active=screen_active_by_candidate[index] if index < len(screen_active_by_candidate) else False,
        )
        decisions.append({
            "candidate_id": index + 1,
            "source_start": start,
            "source_end": end,
            "editable_start": editable_start,
            "editable_end": editable_end,
            "proposed_action": action.value,
            "review_required": action is Action.CUT,
        })
        if editable_start > keep_start:
            edits.append(TimelineSegment(keep_start, editable_start, Action.KEEP))
        if editable_end > editable_start:
            edits.append(TimelineSegment(editable_start, editable_end, action, 5.0 if action is Action.SPEED_5X else 1.0))
        cursor = keep_end
    if cursor < duration:
        edits.append(TimelineSegment(cursor, duration, Action.KEEP))
    return {"candidates": decisions, "segments": build_timeline(edits), "source_duration": duration}
