from __future__ import annotations

import json
import shutil
from pathlib import Path

from .brand_pack import load_brand_pack
from .brand_pack_io import discover_brand_pack
from .thumbnail import render_thumbnail
from .youtube_export import export_youtube_text
from .youtube_source import build_metadata_source
from .youtube_validation import chapter_times, validate_youtube_proposal
from .youtube_verify import verify_youtube_attempt


REQUIRED_YOUTUBE_FILES = (
    "metadata-source.json",
    "metadata-proposal.json",
    "metadata.json",
    "youtube-review.json",
    "title.txt",
    "alternative-titles.txt",
    "description.md",
    "hashtags.txt",
    "thumbnail.png",
    "verify-youtube.json",
)


class YoutubeOrchestratorError(ValueError):
    """Raised when the publishing-only lifecycle cannot proceed safely."""


def _write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def prepare_attempt(run: Path, brand_pack_root: Path | None, final_video: Path | None = None, timestamp: str | None = None) -> Path:
    run = Path(run).resolve()
    pack = load_brand_pack(brand_pack_root) if brand_pack_root else discover_brand_pack()
    corrected = run / "corrected.srt"
    candidates = [run / "final-captioned-tips.mp4", run / "final-captioned.mp4"]
    final = Path(final_video).resolve() if final_video else next((path for path in candidates if path.is_file()), candidates[-1])
    if not corrected.is_file():
        raise YoutubeOrchestratorError(f"completed corrected.srt is missing: {corrected}")
    stamp = timestamp or __import__("datetime").datetime.now().strftime("%Y%m%d-%H%M%S")
    attempt = run / "youtube" / f"attempt-{stamp}"
    if attempt.exists():
        raise YoutubeOrchestratorError(f"refusing to reuse existing attempt: {attempt}")
    attempt.mkdir(parents=True)
    source = build_metadata_source(run, pack.profile, final)
    source["inputs"] = {"corrected_srt": str(corrected), "final_video": str(final)}
    source["brand_pack"] = {
        "id": pack.identifier,
        "assets": {"book": pack.profile.book.sha256, "character": pack.profile.character.sha256},
    }
    _write_json(attempt / "metadata-source.json", source)
    _write_json(attempt / "attempt-manifest.json", {"schema_version": 1, "run": str(run), "brand_pack_id": pack.identifier})
    return attempt


def finalize_attempt(attempt: Path, proposal_path: Path, brand_pack_root: Path | None) -> dict:
    attempt = Path(attempt).resolve()
    pack = load_brand_pack(brand_pack_root) if brand_pack_root else discover_brand_pack()
    source = json.loads((attempt / "metadata-source.json").read_text(encoding="utf-8"))
    proposal = json.loads(Path(proposal_path).read_text(encoding="utf-8"))
    result = validate_youtube_proposal(source, proposal)
    _write_json(attempt / "metadata-proposal.json", proposal)
    review = {"accepted": result.accepted, "reviews": list(result.reviews)}
    _write_json(attempt / "youtube-review.json", review)
    if not result.accepted:
        verify = {"overall": "FAIL", "checks": [{"name": "metadata_validation", "passed": False, "detail": {"reasons": result.reasons}}]}
        _write_json(attempt / "verify-youtube.json", verify)
        return verify

    staging = attempt / ".finalize-staging"
    if staging.exists():
        raise YoutubeOrchestratorError(f"staging path already exists: {staging}")
    staging.mkdir()
    try:
        shutil.copy2(attempt / "metadata-source.json", staging / "metadata-source.json")
        shutil.copy2(attempt / "metadata-proposal.json", staging / "metadata-proposal.json")
        shutil.copy2(attempt / "youtube-review.json", staging / "youtube-review.json")
        metadata = {"accepted": True, "metadata": result.metadata, "reviews": []}
        if result.metadata.get("chapters"):
            metadata["chapter_times"] = chapter_times(source, result.metadata["chapters"])
        _write_json(staging / "metadata.json", metadata)
        export_youtube_text(metadata, pack.profile, staging)
        render_thumbnail(metadata, pack.profile, staging / "thumbnail.png")
        expected = {"book": pack.profile.book.sha256, "character": pack.profile.character.sha256}
        verify = verify_youtube_attempt(staging, expected)
        if verify["overall"] != "PASS":
            _write_json(attempt / "verify-youtube.json", verify)
            return verify
        for name in ("metadata.json", "title.txt", "alternative-titles.txt", "description.md", "hashtags.txt", "thumbnail.png"):
            (staging / name).replace(attempt / name)
        _write_json(attempt / "verify-youtube.json", verify)
        return verify
    finally:
        if staging.exists():
            shutil.rmtree(staging)
