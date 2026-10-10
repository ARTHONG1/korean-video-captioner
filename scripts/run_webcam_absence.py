from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

from kvc.absence_analysis import analyze_timeline
from kvc.absence_driver import initialize_preprocess
from kvc.absence_models import AbsenceConfig
from kvc.audio_activity import parse_silencedetect, silence_ratio
from kvc.paths import RuntimePaths


def _audio_evidence(input_path: Path, ffmpeg: Path, duration: float, start: float, end: float) -> float | None:
    command = [str(ffmpeg), "-v", "error", "-ss", str(start), "-to", str(end), "-i", str(input_path), "-af", "silencedetect=noise=-40dB:d=1.0", "-f", "null", "-"]
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode not in (0, 1):
        return None
    return silence_ratio(parse_silencedetect(result.stderr, duration=end - start), end - start)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run webcam absence analysis and render an effective input")
    parser.add_argument("--input", required=True)
    parser.add_argument("--run", required=True)
    parser.add_argument("--model", default=None)
    parser.add_argument("--vision-python", default=None)
    parser.add_argument("--local-only", action="store_true")
    parser.add_argument("--allow-reviewed-cuts", action="store_true")
    args = parser.parse_args()
    runtime = RuntimePaths.discover()
    run = Path(args.run)
    run.mkdir(parents=True, exist_ok=True)
    initial = initialize_preprocess(Path(args.input), run, runtime.ffprobe)
    if initial["status"] == "NO_OP":
        return 0
    model = Path(args.model) if args.model else runtime.yunet_model
    vision_python = Path(args.vision_python) if args.vision_python else runtime.vision_python
    scan_path = run / "webcam-scan.json"
    subprocess.run([str(vision_python), str(Path(__file__).with_name("scan_webcam_presence.py")), "--input", args.input, "--model", str(model), "--output", str(scan_path)], check=True)
    scan = json.loads(scan_path.read_text(encoding="utf-8"))
    candidates = []
    for i, (start, end) in enumerate(__import__("kvc.absence_detection", fromlist=["find_absence_candidates"]).find_absence_candidates(scan["samples"])):
        start = max(0.0, start + 5.0)
        end = min(initial["duration"], end + 1.0 - 5.0)
        silence = _audio_evidence(Path(args.input), runtime.ffmpeg, initial["duration"], start, end)
        windows = [(float(mad), float(p95)) for timestamp, mad, p95 in scan.get("activity", []) if start <= timestamp <= end]
        low = __import__("kvc.screen_activity", fromlist=["low_activity_ratio"]).low_activity_ratio(windows)
        candidates.append((silence, low, low < 0.95))
    analysis = analyze_timeline(duration=initial["duration"], face_samples=scan["samples"], silence_ratio_by_candidate=[x[0] for x in candidates], low_activity_ratio_by_candidate=[x[1] for x in candidates], screen_active_by_candidate=[x[2] for x in candidates])
    (run / "webcam-analysis.json").write_text(json.dumps(scan, ensure_ascii=False, indent=2), encoding="utf-8")
    (run / "webcam-candidates.json").write_text(json.dumps(analysis["candidates"], ensure_ascii=False, indent=2), encoding="utf-8")
    if args.local_only or not args.allow_reviewed_cuts:
        for segment in analysis["segments"]:
            if segment["action"] == "cut":
                segment["action"], segment["speed"] = "speed_5x", 5.0
        (run / "webcam-review.json").write_text(json.dumps({"mode": "local-only" if args.local_only else "automatic-safe-default", "downgraded_cuts": True}, ensure_ascii=False, indent=2), encoding="utf-8")
    (run / "timeline-map.json").write_text(json.dumps(analysis["segments"], ensure_ascii=False, indent=2), encoding="utf-8")
    if any(segment["action"] != "keep" for segment in analysis["segments"]):
        subprocess.run([str(__import__('sys').executable), str(Path(__file__).with_name("render_webcam_edits.py")), "--input", args.input, "--timeline", str(run / "timeline-map.json"), "--output", str(run / "preprocessed.mp4"), "--ffmpeg", str(runtime.ffmpeg)], check=True)
        initial["effective_input"] = str((run / "preprocessed.mp4").resolve())
        (run / "effective-input.json").write_text(json.dumps(initial, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
