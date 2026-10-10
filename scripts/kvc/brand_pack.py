from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath

from .youtube_profile import ProfileError, YoutubeProfile, load_youtube_profile


class BrandPackError(ValueError):
    """Raised when a portable private brand pack is invalid."""


@dataclass(frozen=True)
class BrandPack:
    root: Path
    identifier: str
    distribution_scope: str
    profile_path: Path
    profile: YoutubeProfile
    manifest: dict


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def resolve_pack_path(base: Path, value: str, root: Path) -> Path:
    candidate = Path(value)
    if candidate.is_absolute() or bool(PureWindowsPath(value).drive):
        raise BrandPackError(f"brand-pack path must be relative: {value}")
    resolved = (Path(base) / candidate).resolve()
    root = Path(root).resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise BrandPackError(f"brand-pack path escapes root: {value}") from exc
    return resolved


def load_brand_pack(root: Path) -> BrandPack:
    root = Path(root).resolve()
    manifest_path = root / "brand-pack.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise BrandPackError(f"invalid brand-pack manifest: {manifest_path}") from exc
    if manifest.get("schema_version") != 1:
        raise BrandPackError("unsupported brand-pack schema_version")
    identifier = manifest.get("id")
    if not isinstance(identifier, str) or not identifier.strip():
        raise BrandPackError("brand-pack id is required")
    scope = manifest.get("distribution_scope")
    if scope != "private-user-supplied":
        raise BrandPackError("distribution_scope must be private-user-supplied")
    profile_path = resolve_pack_path(root, str(manifest.get("profile", "")), root)
    try:
        profile = load_youtube_profile(profile_path, allowed_root=root, require_relative=True)
    except ProfileError as exc:
        raise BrandPackError(str(exc)) from exc
    assets = manifest.get("assets")
    if not isinstance(assets, dict):
        raise BrandPackError("brand-pack assets object is required")
    actual = {"book": profile.book, "character": profile.character}
    for name, info in actual.items():
        record = assets.get(name)
        if not isinstance(record, dict):
            raise BrandPackError(f"missing {name} asset record")
        manifest_asset = resolve_pack_path(root, str(record.get("path", "")), root)
        if manifest_asset != info.path:
            raise BrandPackError(f"{name} path differs between manifest and profile")
        expected = str(record.get("sha256", "")).lower()
        got = _sha256(info.path)
        if expected != got:
            raise BrandPackError(f"{name} SHA-256 mismatch: expected {expected}, got {got}")
    return BrandPack(root, identifier.strip(), scope, profile_path, profile, manifest)
