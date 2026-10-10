from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath

from PIL import Image


class ProfileError(ValueError):
    """Raised when a YouTube profile or its assets are unsafe to use."""


@dataclass(frozen=True)
class AssetInfo:
    path: Path
    sha256: str
    width: int
    height: int
    has_alpha: bool


@dataclass(frozen=True)
class YoutubeProfile:
    channel_name: str
    language: str
    book_title: str
    publisher: str
    book_url: str
    book: AssetInfo
    character: AssetInfo
    footer_lines: tuple[str, ...]
    default_hashtags: tuple[str, ...]
    thumbnail: dict


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def inspect_asset(path: Path, require_alpha: bool = False) -> AssetInfo:
    path = Path(path)
    if not path.is_file():
        raise ProfileError(f"asset not found: {path}")
    try:
        with Image.open(path) as image:
            width, height = image.size
            has_alpha = "A" in image.getbands() and image.getchannel("A").getextrema()[0] < 255
            if require_alpha and not has_alpha:
                raise ProfileError(f"character_cutout requires transparent alpha pixels: {path}")
            if width < 2 or height < 2:
                raise ProfileError(f"asset dimensions are too small: {path}")
    except ProfileError:
        raise
    except Exception as exc:
        raise ProfileError(f"unreadable image asset: {path}") from exc
    return AssetInfo(path, _sha256(path), width, height, has_alpha)


def _require_string(data: dict, key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ProfileError(f"missing profile field: {key}")
    return value.strip()


def _resolve_asset_path(raw: str, profile_path: Path, allowed_root: Path | None, require_relative: bool) -> Path:
    candidate = Path(raw)
    if require_relative and (candidate.is_absolute() or bool(PureWindowsPath(raw).drive)):
        raise ProfileError(f"portable asset path must be relative: {raw}")
    resolved = (profile_path.parent / candidate).resolve() if not candidate.is_absolute() else candidate.resolve()
    if allowed_root is not None:
        root = Path(allowed_root).resolve()
        try:
            resolved.relative_to(root)
        except ValueError as exc:
            raise ProfileError(f"asset path escapes brand pack: {raw}") from exc
    return resolved


def load_youtube_profile(
    path: Path,
    *,
    allowed_root: Path | None = None,
    require_relative: bool = False,
) -> YoutubeProfile:
    path = Path(path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ProfileError(f"invalid profile JSON: {path}") from exc
    if data.get("schema_version") != 1:
        raise ProfileError("unsupported profile schema_version")
    assets = data.get("assets")
    book = data.get("book")
    thumbnail = data.get("thumbnail")
    if not isinstance(assets, dict) or not isinstance(book, dict) or not isinstance(thumbnail, dict):
        raise ProfileError("profile assets, book, and thumbnail objects are required")
    book_path = _resolve_asset_path(_require_string(assets, "book_image"), path, allowed_root, require_relative)
    character_path = _resolve_asset_path(_require_string(assets, "character_cutout"), path, allowed_root, require_relative)
    try:
        book_info = inspect_asset(book_path)
    except ProfileError as exc:
        raise ProfileError(f"book_image: {exc}") from exc
    try:
        character_info = inspect_asset(character_path, require_alpha=True)
    except ProfileError as exc:
        raise ProfileError(f"character_cutout: {exc}") from exc
    font_value = thumbnail.get("font")
    if font_value:
        font = _resolve_asset_path(str(font_value), path, allowed_root, require_relative)
        if not font.is_file():
            raise ProfileError(f"thumbnail font not found: {font}")
    if thumbnail.get("width") != 1280 or thumbnail.get("height") != 720:
        raise ProfileError("thumbnail canvas must be exactly 1280x720")
    defaults = data.get("default_hashtags", [])
    if not isinstance(defaults, list) or any(not isinstance(tag, str) or not tag.startswith("#") or " " in tag for tag in defaults):
        raise ProfileError("default_hashtags must be unique space-free strings beginning with #")
    if len(set(defaults)) != len(defaults):
        raise ProfileError("duplicate default hashtag")
    footer = data.get("description_footer_lines", [])
    if not isinstance(footer, list) or any(not isinstance(line, str) for line in footer):
        raise ProfileError("description_footer_lines must be a list of strings")
    return YoutubeProfile(
        channel_name=_require_string(data, "channel_name"),
        language=_require_string(data, "language"),
        book_title=_require_string(book, "title"),
        publisher=str(book.get("publisher", "")).strip(),
        book_url=str(book.get("url", "")).strip(),
        book=book_info,
        character=character_info,
        footer_lines=tuple(footer),
        default_hashtags=tuple(defaults),
        thumbnail=thumbnail,
    )


def _copy_once(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        if _sha256(source) == _sha256(destination):
            return
        raise ProfileError(f"refusing to overwrite different asset: {destination}")
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    shutil.copy2(source, temporary)
    if _sha256(source) != _sha256(temporary):
        temporary.unlink(missing_ok=True)
        raise ProfileError(f"asset copy hash mismatch: {source}")
    temporary.replace(destination)


def copy_personal_assets(book: Path, character: Path, destination: Path) -> dict:
    book_info = inspect_asset(Path(book))
    character_info = inspect_asset(Path(character), require_alpha=True)
    destination = Path(destination)
    book_target = destination / "book-ai-agent.png"
    character_target = destination / "character-cj-cutout.png"
    _copy_once(book_info.path, book_target)
    _copy_once(character_info.path, character_target)
    manifest = {
        "schema_version": 1,
        "book": {**book_info.__dict__, "path": str(book_target), "sha256": _sha256(book_target)},
        "character": {**character_info.__dict__, "path": str(character_target), "sha256": _sha256(character_target)},
    }
    manifest["book"]["path"] = str(book_target)
    manifest["character"]["path"] = str(character_target)
    manifest_path = destination / "asset-manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return manifest
