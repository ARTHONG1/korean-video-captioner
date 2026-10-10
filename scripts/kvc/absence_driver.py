from __future__ import annotations

import json
import subprocess
from pathlib import Path

from .absence_models import AbsenceConfig
from .absence_analysis import analyze_timeline


def probe_duration(input_path: Path, ffprobe: Path) -> float:
    result = subprocess.run(
        [str(ffprobe), "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(input_path)],
        check=True, capture_output=True, text=True,
    )
    return float(result.stdout.strip())

def decide_preprocess(*, duration: float, min_absence_seconds: float = 180.0) -> dict[str, str]:
    if duration < min_absence_seconds:
        return {"status": "NO_OP", "reason": "below_minimum_absence_duration"}
    return {"status": "ANALYZE", "reason": "duration_meets_candidate_threshold"}


def initialize_preprocess(input_path: Path, run_dir: Path, ffprobe: Path, config: AbsenceConfig | None = None) -> dict:
    config = config or AbsenceConfig()
    duration = probe_duration(input_path, ffprobe)
    run_dir.mkdir(parents=True, exist_ok=True)
    decision = decide_preprocess(duration=duration, min_absence_seconds=config.min_absence_seconds)
    result = {
        "schema_version": 1,
        "source": str(input_path.resolve()),
        "duration": duration,
        "status": decision["status"],
        "reason": decision["reason"],
        "effective_input": str(input_path.resolve()),
        "config": {
            "minimum_absence_seconds": config.min_absence_seconds,
            "initial_roi": [config.initial_roi.x, config.initial_roi.y, config.initial_roi.width, config.initial_roi.height],
        },
    }
    (run_dir / "effective-input.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    (run_dir / "absence-workflow-state.json").write_text(json.dumps({"state": "no_op" if result["status"] == "NO_OP" else "probed", "source": result["source"]}, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def write_analysis(run_dir: Path, analysis: dict) -> None:
    (run_dir / "webcam-candidates.json").write_text(json.dumps(analysis["candidates"], ensure_ascii=False, indent=2), encoding="utf-8")
    (run_dir / "timeline-map.json").write_text(json.dumps(analysis["segments"], ensure_ascii=False, indent=2), encoding="utf-8")
