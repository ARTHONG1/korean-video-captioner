from __future__ import annotations

from .absence_models import Action


def classify_absence(*, silence_ratio: float | None, low_activity_ratio: float, screen_active: bool) -> Action:
    if silence_ratio is None or silence_ratio < 0.98:
        return Action.KEEP
    if screen_active or low_activity_ratio < 0.95:
        return Action.SPEED_5X
    return Action.CUT
