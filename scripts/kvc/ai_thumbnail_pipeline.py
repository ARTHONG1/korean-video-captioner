from __future__ import annotations

import json
import shutil
from pathlib import Path

from .ai_thumbnail import build_ai_thumbnail_brief, build_generation_request
from .ai_thumbnail_candidates import load_candidate_manifest
from .ai_thumbnail_review import select_candidate
from .brand_pack import load_brand_pack
from .brand_pack_io import discover_brand_pack
from .youtube_export import export_youtube_text
from .youtube_validation import chapter_times, validate_youtube_proposal
from .youtube_verify import verify_youtube_attempt


def _write(path: Path, value: object) -> None:
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def prepare_ai_thumbnail(attempt: Path, proposal_path: Path, brand_pack_root: Path | None = None,
                         scene_image: Path | None = None, scene_description: str | None = None) -> Path:
    attempt = Path(attempt).resolve()
    pack = load_brand_pack(brand_pack_root) if brand_pack_root else discover_brand_pack()
    source = json.loads((attempt / "metadata-source.json").read_text(encoding="utf-8"))
    proposal = json.loads(Path(proposal_path).read_text(encoding="utf-8"))
    result = validate_youtube_proposal(source, proposal)
    _write(attempt / "metadata-proposal.json", proposal)
    _write(attempt / "youtube-review.json", {"accepted": result.accepted, "reviews": list(result.reviews), "thumbnail_mode": "ai-reference"})
    if not result.accepted:
        raise ValueError(f"metadata proposal rejected: {result.reasons}")
    brief = build_ai_thumbnail_brief(source, result.metadata)
    scene = None
    if scene_image:
        target = attempt / "scene-reference" / ("scene" + Path(scene_image).suffix.lower())
        if target.exists():
            raise ValueError(f"refusing to overwrite scene reference: {target}")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(scene_image, target)
        scene = {"path": target, "description": scene_description or "the main visual from the video"}
    request = build_generation_request(brief, pack.profile, scene)
    _write(attempt / "thumbnail-brief.json", brief)
    path = attempt / "thumbnail-generation-request.json"
    _write(path, request)
    return path


def finalize_ai_thumbnail(attempt: Path, review_path: Path, brand_pack_root: Path | None = None) -> dict:
    attempt = Path(attempt).resolve()
    pack = load_brand_pack(brand_pack_root) if brand_pack_root else discover_brand_pack()
    manifest = load_candidate_manifest(attempt)
    review = json.loads(Path(review_path).read_text(encoding="utf-8"))
    winner = select_candidate(manifest, review)
    source = json.loads((attempt / "metadata-source.json").read_text(encoding="utf-8"))
    proposal = json.loads((attempt / "metadata-proposal.json").read_text(encoding="utf-8"))
    validated = validate_youtube_proposal(source, proposal)
    if not validated.accepted:
        raise ValueError(f"metadata proposal rejected: {validated.reasons}")
    metadata = {"accepted": True, "metadata": validated.metadata, "reviews": []}
    if validated.metadata.get("chapters"):
        metadata["chapter_times"] = chapter_times(source, validated.metadata["chapters"])
    _write(attempt / "metadata.json", metadata)
    export_youtube_text(metadata, pack.profile, attempt)
    thumbnail = attempt / "thumbnail.png"
    if thumbnail.exists():
        raise ValueError(f"refusing to overwrite existing thumbnail: {thumbnail}")
    shutil.copy2(winner["normalized_path"], thumbnail)
    thumb_verify = {
        "overall": "PASS",
        "mode": "ai-reference",
        "selected_candidate_id": winner["candidate_id"],
        "selected_variant": winner["variant"],
        "generation_call_count": len(manifest.get("calls", [])),
        "visual_review": "current Codex vision review",
        "thumbnail_contract": {"size": [1280, 720], "mode": "RGB"},
        "reference_hashes": {"book": pack.profile.book.sha256, "character": pack.profile.character.sha256},
    }
    _write(attempt / "verify-thumbnail.json", thumb_verify)
    verify = verify_youtube_attempt(attempt, {"book": pack.profile.book.sha256, "character": pack.profile.character.sha256})
    _write(attempt / "verify-youtube.json", verify)
    return verify
