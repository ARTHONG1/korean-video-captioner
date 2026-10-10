from __future__ import annotations

import hashlib
import re
from pathlib import Path

from .youtube_validation import _protected_tokens


class AIThumbnailError(ValueError):
    """Raised when an AI thumbnail request cannot be grounded safely."""


VARIANTS = ("book-led", "character-led", "balanced")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _line_length(value: str) -> int:
    return len(re.sub(r"\s+", "", value))


def build_ai_thumbnail_brief(source: dict, validated_metadata: dict) -> dict:
    cues = source.get("cues", []) if isinstance(source, dict) else []
    cue_text = {cue.get("id"): str(cue.get("text", "")) for cue in cues if isinstance(cue, dict)}
    thumbnail = validated_metadata.get("thumbnail", {}) if isinstance(validated_metadata, dict) else {}
    lines = thumbnail.get("lines", []) if isinstance(thumbnail, dict) else []
    ids = thumbnail.get("source_cue_ids", []) if isinstance(thumbnail, dict) else []
    if not isinstance(lines, list) or not 1 <= len(lines) <= 2 or any(not isinstance(line, str) or not line.strip() for line in lines):
        raise AIThumbnailError("thumbnail headline must contain one or two non-empty lines")
    if any(_line_length(line) > 16 for line in lines):
        raise AIThumbnailError("thumbnail headline line exceeds 16 visible characters")
    if not isinstance(ids, list) or not ids or any(item not in cue_text for item in ids):
        raise AIThumbnailError("thumbnail headline requires real source cue IDs")
    evidence = " ".join(cue_text[item] for item in ids)
    headline = " ".join(lines)
    missing = [token for token in _protected_tokens(headline) if token.casefold() not in evidence.casefold()]
    if missing:
        raise AIThumbnailError(f"headline contains unsupported protected token: {missing[0]}")
    return {
        "schema_version": 1,
        "topic": evidence,
        "viewer_benefit": evidence,
        "headline": headline,
        "headline_lines": list(lines),
        "source_cue_ids": list(ids),
        "protected_tokens": list(_protected_tokens(evidence)),
    }


def build_generation_request(brief: dict, profile, scene: dict | None = None) -> dict:
    """scene: optional {"path", "description"} — a frame from the user's own video that the user asked to show
    (for example the app screen the video is about). It is passed as Image 3 after book and character."""
    references = [
        {"role": "book", "path": str(Path(profile.book.path).resolve()), "sha256": profile.book.sha256},
        {"role": "character", "path": str(Path(profile.character.path).resolve()), "sha256": profile.character.sha256},
    ]
    if scene:
        scene_path = Path(scene["path"]).resolve()
        references.append({"role": "scene", "path": str(scene_path), "sha256": _sha256(scene_path),
                           "description": str(scene.get("description", "")).strip()})
    for reference in references:
        path = Path(reference["path"])
        if not path.is_file() or not reference["sha256"]:
            raise AIThumbnailError(f"invalid reference image: {reference['role']}")
    scene_text = references[2]["description"] if scene else None
    return {
        "schema_version": 1,
        "mode": "ai-reference",
        "brief": brief,
        "references": references,
        "canvas": {"width": 1280, "height": 720, "aspect_ratio": "16:9"},
        "variants": [{"id": variant, "prompt": render_imagegen_prompt(brief, variant, scene_text)} for variant in VARIANTS],
        "max_calls": 5,
    }


def render_imagegen_prompt(brief: dict, variant_id: str, scene_description: str | None = None) -> str:
    if variant_id not in VARIANTS:
        raise AIThumbnailError(f"unknown thumbnail variant: {variant_id}")
    headline = str(brief.get("headline", "")).strip()
    topic = str(brief.get("topic", "")).strip()
    benefit = str(brief.get("viewer_benefit", "")).strip()
    directions = {
        "book-led": "make the referenced book the primary focal point and the character the supporting focal point",
        "character-led": "make the referenced character the primary focal point and the book the supporting focal point",
        "balanced": "give the referenced book and character equal visual importance",
    }
    inputs = "Input images: Image 1 is the exact book reference; Image 2 is the exact character reference"
    subject = "Subject: use both referenced subjects as the only main subjects; " + directions[variant_id]
    if scene_description:
        inputs += f"; Image 3 is a visual reference from the video: {scene_description}"
        subject = ("Subject: keep the referenced book and character recognizable and unchanged; add one large element closely following "
                   f"Image 3 ({scene_description}) as the visual hook between them; " + directions[variant_id])
    return "\n".join(
        [
            "Use case: ads-marketing",
            "Asset type: Korean YouTube thumbnail, 16:9 landscape, 1280x720",
            inputs,
            f"Primary request: create a clean, eye-catching thumbnail about {topic} and its viewer benefit {benefit}",
            subject,
            "Composition/framing: protect the lower-right YouTube duration-overlay safe zone; strong mobile readability",
            f'Text (verbatim): "{headline}"',
            "Constraints: preserve recognizable book and character identity; render the headline exactly once; no extra text; no watermark; no unrelated logos",
            "Avoid: altered character identity, unrelated books, gibberish Korean, clutter, tiny text, cropped key subjects",
        ]
    )
