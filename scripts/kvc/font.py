from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from fontTools.ttLib import TTFont
from PIL import Image, ImageDraw, ImageFont


class FontError(ValueError):
    """Raised when the distributable Korean font contract is invalid."""


@dataclass(frozen=True)
class FontInfo:
    path: Path
    license_path: Path
    family: str
    sha256: str
    expected_sha256: str
    upstream_version: str
    upstream_commit: str


def skill_root() -> Path:
    return Path(__file__).resolve().parents[2]


def bundled_font() -> FontInfo:
    return resolve_font(skill_root())


def caption_font() -> FontInfo:
    """Unmodified static Noto Sans KR Bold used for burned captions (the variable font ignores ASS Bold)."""
    root = skill_root()
    font_dir = root / "assets" / "fonts"
    manifest = json.loads((font_dir / "font-manifest.json").read_text(encoding="utf-8"))
    entry = manifest.get("caption_font")
    if not entry:
        return bundled_font()
    path = font_dir / entry["file"]
    if not path.is_file():
        raise FontError(f"caption font not found: {path}")
    actual = _sha256(path)
    if actual != entry["sha256"].lower():
        raise FontError(f"caption font SHA-256 mismatch: expected {entry['sha256']}, got {actual}")
    license_path = font_dir / manifest["license_file"]
    return FontInfo(path=path.resolve(), license_path=license_path.resolve(), family=entry["family"], sha256=actual,
                    expected_sha256=actual, upstream_version=entry["upstream_version"], upstream_commit=entry["upstream_commit"])


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def resolve_font(skill_root: Path, override: Path | None = None) -> FontInfo:
    root = Path(skill_root)
    font_dir = root / "assets" / "fonts"
    manifest_path = font_dir / "font-manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise FontError(f"invalid font manifest: {manifest_path}") from exc
    if manifest.get("schema_version") != 1:
        raise FontError("unsupported font manifest schema_version")
    font_path = Path(override) if override else font_dir / manifest["font_file"]
    license_path = font_dir / manifest["license_file"]
    if not font_path.is_file():
        raise FontError(f"font file not found: {font_path}")
    if not license_path.is_file():
        raise FontError(f"font license not found: {license_path}")
    expected = manifest["font_sha256"].lower()
    actual = _sha256(font_path)
    if override is None and actual != expected:
        raise FontError(f"font SHA-256 mismatch: expected {expected}, got {actual}")
    license_hash = _sha256(license_path)
    if license_hash != manifest["license_sha256"].lower():
        raise FontError("font license SHA-256 mismatch")
    license_text = license_path.read_text(encoding="utf-8")
    if "SIL OPEN FONT LICENSE Version 1.1" not in license_text:
        raise FontError("font license is not SIL OFL 1.1")
    return FontInfo(
        path=font_path.resolve(),
        license_path=license_path.resolve(),
        family=manifest["family"],
        sha256=actual,
        expected_sha256=expected if override is None else actual,
        upstream_version=manifest["upstream_version"],
        upstream_commit=manifest["upstream_commit"],
    )


def verify_korean_glyphs(font_path: Path) -> None:
    required = "가나다라마바사 123 AI"
    with TTFont(str(font_path), lazy=True) as font:
        cmap = font.getBestCmap() or {}
        missing = [character for character in required if character != " " and ord(character) not in cmap]
    if missing:
        raise FontError(f"font lacks required glyphs: {''.join(missing)}")
    face = ImageFont.truetype(str(font_path), 48)
    canvas = Image.new("L", (640, 96), 0)
    ImageDraw.Draw(canvas).text((8, 8), required, font=face, fill=255)
    if canvas.getbbox() is None:
        raise FontError("font produced an empty Korean glyph probe")
