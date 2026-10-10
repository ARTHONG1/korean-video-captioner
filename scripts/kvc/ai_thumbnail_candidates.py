from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

from PIL import Image, ImageOps

from .ai_thumbnail import VARIANTS


class CandidateError(ValueError):
    pass


def _sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _load_manifest(attempt: Path) -> dict:
    path = Path(attempt) / "thumbnail-candidates.json"
    if not path.exists():
        return {"schema_version": 1, "max_calls": 5, "calls": []}
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("schema_version") != 1:
        raise CandidateError("invalid candidate manifest")
    return value


def _save_manifest(attempt: Path, value: dict) -> None:
    path = Path(attempt) / "thumbnail-candidates.json"
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def remaining_generation_calls(manifest: dict) -> int:
    return max(0, 5 - len(manifest.get("calls", [])))


def register_candidate(attempt: Path, generated_path: Path, variant_id: str) -> dict:
    attempt = Path(attempt).resolve()
    generated_path = Path(generated_path).resolve()
    if variant_id not in VARIANTS:
        raise CandidateError(f"unknown thumbnail variant: {variant_id}")
    if not generated_path.is_file():
        raise CandidateError(f"generated candidate is missing: {generated_path}")
    manifest = _load_manifest(attempt)
    if remaining_generation_calls(manifest) <= 0:
        raise CandidateError("five image-generation calls are already recorded")
    if any(item.get("variant") == variant_id for item in manifest.get("calls", [])):
        raise CandidateError(f"candidate slot already exists: {variant_id}")
    try:
        with Image.open(generated_path) as image:
            image.load()
            width, height = image.size
            if width <= height or width / height < 1.3:
                raise CandidateError("candidate must be a usable landscape image")
            raw_image = image.convert("RGB")
            normalized = ImageOps.fit(raw_image, (1280, 720), method=Image.Resampling.LANCZOS, centering=(0.5, 0.5))
    except CandidateError:
        raise
    except Exception as exc:
        raise CandidateError(f"candidate is not a readable image: {generated_path}") from exc
    candidates = attempt / "thumbnail-candidates"
    candidates.mkdir(parents=True, exist_ok=True)
    index = len(manifest["calls"]) + 1
    raw_path = candidates / f"candidate-{index:02d}-raw.png"
    normalized_path = candidates / f"candidate-{index:02d}.png"
    if raw_path.exists() or normalized_path.exists():
        raise CandidateError("candidate output already exists")
    shutil.copy2(generated_path, raw_path)
    normalized.save(normalized_path, format="PNG")
    record = {
        "candidate_id": f"candidate-{index:02d}",
        "variant": variant_id,
        "raw_path": str(raw_path),
        "normalized_path": str(normalized_path),
        "raw_sha256": _sha256(raw_path),
        "normalized_sha256": _sha256(normalized_path),
        "raw_size": [width, height],
        "normalized_size": [1280, 720],
        "backend": "codex-built-in-imagegen",
    }
    manifest["calls"].append(record)
    _save_manifest(attempt, manifest)
    return record


def load_candidate_manifest(attempt: Path) -> dict:
    return _load_manifest(Path(attempt))
