"""Audio level and low-resolution frame measurements for pause editing."""
from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np

HOP_S = 0.01
FRAME_W = 192
FRAME_H = 108
FRAME_FPS = 10
WEBCAM_ROI = (0.72, 0.58, 0.28, 0.42)
FLOOR_MIN_DB = -85.0
MIN_CONTRAST_DB = 18.0


def envelope_db(pcm, sample_rate: int, hop_s: float = HOP_S, chunk_windows: int = 6000) -> np.ndarray:
    """RMS level in dBFS per hop window; pcm is int16 shaped (samples, channels), memmap friendly."""
    hop = int(round(sample_rate * hop_s))
    total = pcm.shape[0] // hop
    out = np.empty(total, dtype=np.float32)
    for start in range(0, total, chunk_windows):
        stop = min(total, start + chunk_windows)
        block = np.asarray(pcm[start * hop:stop * hop], dtype=np.float32)
        mono = block.mean(axis=1) if block.ndim == 2 else block
        frames = mono.reshape(stop - start, hop)
        rms = np.sqrt(np.mean(frames * frames, axis=1)) / 32768.0
        out[start:stop] = 20.0 * np.log10(np.maximum(rms, 1e-7))
    return out


def speech_mask(length: int, spans: list[tuple[float, float]], hop_s: float = HOP_S) -> np.ndarray:
    mask = np.zeros(length, dtype=bool)
    for start, end in spans:
        a, b = max(0, int(start / hop_s)), min(length, int(end / hop_s) + 1)
        mask[a:b] = True
    return mask


@dataclass(frozen=True)
class Levels:
    floor_db: float
    speech_db: float
    threshold_db: float
    separable: bool

    def as_dict(self) -> dict:
        return {key: (round(value, 2) if isinstance(value, float) else value) for key, value in asdict(self).items()}


def estimate_levels(env: np.ndarray, speech_windows: np.ndarray | None = None) -> Levels:
    """Quiet threshold sits well below speech; if speech and room tone are too close, nothing is cut."""
    floor = max(float(np.percentile(env, 5)), FLOOR_MIN_DB)
    if speech_windows is not None and np.any(speech_windows):
        speech = float(np.median(env[speech_windows]))
    else:
        speech = float(np.percentile(env, 90))
    contrast = speech - floor
    threshold = floor + min(12.0, 0.4 * max(contrast, 0.0))
    return Levels(floor, speech, threshold, contrast >= MIN_CONTRAST_DB)


def region_masks(width: int = FRAME_W, height: int = FRAME_H, roi=WEBCAM_ROI) -> tuple[np.ndarray, np.ndarray]:
    x, y, w, h = roi
    cam = np.zeros((height, width), dtype=bool)
    x0, y0 = int(round(x * width)), int(round(y * height))
    x1, y1 = min(width, int(round((x + w) * width))), min(height, int(round((y + h) * height)))
    cam[y0:y1, x0:x1] = True
    return ~cam, cam


def changed_pixels(a: np.ndarray, b: np.ndarray, mask: np.ndarray, level: int = 12) -> int:
    diff = np.abs(a.astype(np.int16) - b.astype(np.int16)) > level
    return int(np.count_nonzero(diff & mask))

