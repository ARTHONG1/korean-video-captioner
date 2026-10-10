from __future__ import annotations

import argparse
import json
from pathlib import Path

from kvc.absence_models import NormalizedROI
from kvc.face_presence import accepted_detection, calibrate_roi


def _scan(video: Path, model: Path, search: NormalizedROI, fps: float) -> tuple[float, list[tuple[float, bool]], NormalizedROI, list[tuple[float, float, float]]]:
    import cv2

    capture = cv2.VideoCapture(str(video))
    if not capture.isOpened():
        raise RuntimeError(f"cannot open video: {video}")
    width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
    duration = float(capture.get(cv2.CAP_PROP_FRAME_COUNT)) / float(capture.get(cv2.CAP_PROP_FPS) or 1.0)
    sx, sy, sw, sh = search.pixels(width, height)
    detector = cv2.FaceDetectorYN.create(str(model), "", (max(sw, 1), max(sh, 1)), 0.75, 0.3, 5000)

    def at(second: float, roi: NormalizedROI) -> tuple[bool, tuple[float, float, float, float, float] | None]:
        capture.set(cv2.CAP_PROP_POS_MSEC, second * 1000.0)
        ok, frame = capture.read()
        if not ok:
            return False, None
        rx, ry, rw, rh = roi.pixels(width, height)
        crop = frame[ry : ry + rh, rx : rx + rw]
        detector.setInputSize((max(rw, 1), max(rh, 1)))
        _, detections = detector.detect(crop)
        if detections is None:
            return False, None
        for row in detections:
            x, y, w, h = map(float, row[:4])
            score = float(row[-1])
            center = ((rx + x + w / 2) / width, (ry + y + h / 2) / height)
            if accepted_detection(score=score, center=center, roi=search):
                return True, ((rx + x) / width, (ry + y) / height, w / width, h / height, score)
        return False, None

    calibration_faces: list[tuple[float, float, float, float, float]] = []
    for second in [i / fps for i in range(int(min(duration, 120.0) * fps))]:
        present, box = at(second, search)
        if present and box:
            calibration_faces.append(box)
    calibrated = calibrate_roi(calibration_faces, search)
    samples = []
    activity = []
    previous = None
    for second in [i / fps for i in range(int(duration * fps))]:
        capture.set(cv2.CAP_PROP_POS_MSEC, second * 1000.0)
        ok, frame = capture.read()
        samples.append((second, at(second, calibrated)[0]) if ok else (second, False))
        if not ok:
            continue
        small = cv2.resize(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), (320, max(1, round(320 * height / width))))
        if previous is not None:
            diff = cv2.absdiff(small, previous) / 255.0
            rx, ry, rw, rh = calibrated.pixels(small.shape[1], small.shape[0])
            mask = diff.copy()
            mask[ry : min(mask.shape[0], ry + rh), rx : min(mask.shape[1], rx + rw)] = 0
            value = float(mask.sum() / max(1, (mask != 0).sum()))
            activity.append((second, value, value))
        previous = small
    capture.release()
    return duration, samples, calibrated, activity


def main() -> int:
    parser = argparse.ArgumentParser(description="Scan lower-right webcam face presence with YuNet")
    parser.add_argument("--input", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--fps", type=float, default=1.0)
    args = parser.parse_args()
    search = NormalizedROI(0.72, 0.58, 0.28, 0.42)
    duration, samples, roi, activity = _scan(Path(args.input), Path(args.model), search, args.fps)
    payload = {"duration": duration, "roi": [roi.x, roi.y, roi.width, roi.height], "samples": samples, "activity": activity}
    Path(args.output).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
