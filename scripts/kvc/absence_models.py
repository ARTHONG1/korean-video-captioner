from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Action(str, Enum):
    KEEP = "keep"
    SPEED_5X = "speed_5x"
    CUT = "cut"


@dataclass(frozen=True)
class NormalizedROI:
    x: float
    y: float
    width: float
    height: float

    def __post_init__(self) -> None:
        if not (0 <= self.x <= 1 and 0 <= self.y <= 1 and 0 < self.width <= 1 and 0 < self.height <= 1):
            raise ValueError("ROI values must be normalized and positive")
        if self.x + self.width > 1 or self.y + self.height > 1:
            raise ValueError("ROI must be inside the frame")

    def pixels(self, frame_width: int, frame_height: int) -> tuple[int, int, int, int]:
        if frame_width <= 0 or frame_height <= 0:
            raise ValueError("frame dimensions must be positive")
        return (
            round(self.x * frame_width),
            round(self.y * frame_height),
            round(self.width * frame_width),
            round(self.height * frame_height),
        )


@dataclass(frozen=True)
class AbsenceConfig:
    min_absence_seconds: float = 180.0
    initial_roi: NormalizedROI = NormalizedROI(0.72, 0.58, 0.28, 0.42)
    speed_factor: float = 5.0
    coarse_fps: float = 1.0
    refine_fps: float = 5.0
    refine_window_seconds: float = 15.0
    present_island_merge_seconds: float = 10.0
    absent_island_remove_seconds: float = 15.0
    boundary_padding_seconds: float = 5.0
    silence_ratio: float = 0.98
    low_activity_ratio: float = 0.95
    activity_mad_threshold: float = 0.012
    activity_p95_threshold: float = 0.020


@dataclass(frozen=True)
class TimelineSegment:
    source_start: float
    source_end: float
    action: Action
    speed: float = 1.0

    def __post_init__(self) -> None:
        if self.source_start < 0 or self.source_end < self.source_start:
            raise ValueError("timeline interval must be ordered and nonnegative")
        if self.speed <= 0:
            raise ValueError("speed must be positive")
        if self.action is Action.KEEP and self.speed != 1.0:
            raise ValueError("keep segments must have speed 1")
        if self.action is Action.SPEED_5X and self.speed != 5.0:
            raise ValueError("speed segments must use 5x")

    @property
    def source_duration(self) -> float:
        return self.source_end - self.source_start

    @property
    def output_duration(self) -> float:
        if self.action is Action.CUT:
            return 0.0
        return self.source_duration / self.speed
