from __future__ import annotations

import hashlib
import json
from pathlib import Path

from PIL import Image

from .youtube_validation import validate_youtube_proposal


VERIFY_REQUIRED_FILES = (
    "metadata-source.json",
    "metadata-proposal.json",
    "metadata.json",
    "youtube-review.json",
    "title.txt",
    "alternative-titles.txt",
    "description.md",
    "hashtags.txt",
    "thumbnail.png",
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_youtube_attempt(attempt: Path, expected_asset_hashes: dict[str, str]) -> dict:
    attempt = Path(attempt)
    checks: list[dict] = []

    def check(name: str, passed: bool, detail: object) -> None:
        checks.append({"name": name, "passed": bool(passed), "detail": detail})

    missing = [name for name in VERIFY_REQUIRED_FILES if not (attempt / name).is_file() or (attempt / name).stat().st_size == 0]
    check("required_files", not missing, {"missing": missing})
    if missing:
        return {"overall": "FAIL", "checks": checks}
    try:
        source = json.loads((attempt / "metadata-source.json").read_text(encoding="utf-8"))
        proposal = json.loads((attempt / "metadata-proposal.json").read_text(encoding="utf-8"))
        metadata = json.loads((attempt / "metadata.json").read_text(encoding="utf-8"))
        review = json.loads((attempt / "youtube-review.json").read_text(encoding="utf-8"))
        check("json_utf8", True, "all JSON files decoded")
    except Exception as exc:
        check("json_utf8", False, str(exc))
        return {"overall": "FAIL", "checks": checks}

    validated = validate_youtube_proposal(source, proposal)
    accepted = validated.accepted and metadata.get("accepted") is True and metadata.get("metadata") == validated.metadata and review.get("accepted") is True
    check("metadata_validation", accepted, {"reasons": validated.reasons})

    text_status = {}
    for name in ("title.txt", "alternative-titles.txt", "description.md", "hashtags.txt"):
        try:
            text_status[name] = bool((attempt / name).read_text(encoding="utf-8").strip())
        except UnicodeError:
            text_status[name] = False
    check("copy_ready_utf8", all(text_status.values()), text_status)

    try:
        with Image.open(attempt / "thumbnail.png") as image:
            contract = image.size == (1280, 720) and image.mode == "RGB"
            detail = {"size": image.size, "mode": image.mode}
    except Exception as exc:
        contract = False
        detail = str(exc)
    check("thumbnail_contract", contract, detail)

    source_assets = source.get("brand_pack", {}).get("assets", {})
    asset_match = all(str(source_assets.get(name, "")).lower() == value.lower() for name, value in expected_asset_hashes.items())
    check("brand_asset_hashes", asset_match, source_assets)

    input_status = {}
    for label, path_value in source.get("inputs", {}).items():
        path = Path(path_value)
        expected = source.get("hashes", {}).get(label)
        input_status[label] = path.is_file() and expected == _sha256(path)
    check("input_hashes", bool(input_status) and all(input_status.values()), input_status)
    return {"overall": "PASS" if all(item["passed"] for item in checks) else "FAIL", "checks": checks}
