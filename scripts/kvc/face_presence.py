from __future__ import annotations

from .absence_models import NormalizedROI


def accepted_detection(*, score: float, center: tuple[float, float], roi: NormalizedROI, threshold: float = 0.75) -> bool:
    return score >= threshold and roi.x <= center[0] <= roi.x + roi.width and roi.y <= center[1] <= roi.y + roi.height


def calibrate_roi(faces: list[tuple[float, float, float, float, float]], search: NormalizedROI) -> NormalizedROI:
    if len(faces) < 10:
        raise ValueError("at least ten detections are required")
    centers_x = [x + width / 2 for x, y, width, height, score in faces if score >= 0.75]
    centers_y = [y + height / 2 for x, y, width, height, score in faces if score >= 0.75]
    if len(centers_x) < 10:
        raise ValueError("not enough confident detections")
    if max(centers_x) - min(centers_x) > search.width or max(centers_y) - min(centers_y) > search.height:
        raise ValueError("detections are not stable")
    x_min = min(x for x, y, width, height, score in faces if score >= 0.75)
    y_min = min(y for x, y, width, height, score in faces if score >= 0.75)
    x_max = max(x + width for x, y, width, height, score in faces if score >= 0.75)
    y_max = max(y + height for x, y, width, height, score in faces if score >= 0.75)
    pad_x = (x_max - x_min) * 0.75
    pad_y = (y_max - y_min) * 0.75
    left = max(search.x, x_min - pad_x)
    top = max(search.y, y_min - pad_y)
    right = min(search.x + search.width, x_max + pad_x)
    bottom = min(search.y + search.height, y_max + pad_y)
    return NormalizedROI(left, top, right - left, bottom - top)
