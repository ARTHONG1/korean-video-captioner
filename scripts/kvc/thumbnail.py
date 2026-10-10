from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from .font import FontInfo, bundled_font


TEXT_REGION = (64, 78, 620, 330)
BOOK_REGION = (690, 48, 1050, 672)
CHARACTER_REGION = (960, 190, 1245, 676)


@dataclass(frozen=True)
class ThumbnailResult:
    path: Path
    width: int
    height: int
    font_size: int
    font_path: Path
    book_box: tuple[int, int, int, int]
    character_box: tuple[int, int, int, int]
    text_box: tuple[int, int, int, int]
    book_sha256: str
    character_sha256: str


class ThumbnailError(ValueError):
    """Raised when a deterministic thumbnail cannot be rendered safely."""


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def boxes_overlap(first: tuple[int, int, int, int], second: tuple[int, int, int, int]) -> bool:
    return not (first[2] <= second[0] or second[2] <= first[0] or first[3] <= second[1] or second[3] <= first[1])


def _font(info: FontInfo, size: int) -> ImageFont.FreeTypeFont:
    face = ImageFont.truetype(str(info.path), size)
    if hasattr(face, "set_variation_by_axes"):
        face.set_variation_by_axes([700])
    return face


def _fit_title(draw: ImageDraw.ImageDraw, lines: list[str], font_info: FontInfo) -> tuple[ImageFont.FreeTypeFont, int, list[tuple[int, int]]]:
    width = TEXT_REGION[2] - TEXT_REGION[0]
    height = TEXT_REGION[3] - TEXT_REGION[1]
    for size in range(82, 55, -2):
        face = _font(font_info, size)
        dimensions: list[tuple[int, int]] = []
        for line in lines:
            box = draw.textbbox((0, 0), line, font=face, stroke_width=1)
            dimensions.append((box[2] - box[0], box[3] - box[1]))
        total_height = sum(item[1] for item in dimensions) + max(0, len(lines) - 1) * 16
        if max(item[0] for item in dimensions) <= width and total_height <= height:
            return face, size, dimensions
    raise ThumbnailError("thumbnail text cannot fit at the 56px minimum font size")


def _fit_image(image: Image.Image, region: tuple[int, int, int, int]) -> tuple[Image.Image, tuple[int, int, int, int]]:
    maximum = (region[2] - region[0], region[3] - region[1])
    resized = image.copy()
    resized.thumbnail(maximum, Image.Resampling.LANCZOS)
    x = region[0] + (maximum[0] - resized.width) // 2
    y = region[1] + (maximum[1] - resized.height) // 2
    return resized, (x, y, x + resized.width, y + resized.height)


def _paste_shadow(canvas: Image.Image, image: Image.Image, box: tuple[int, int, int, int], offset: int = 10) -> None:
    alpha = image.getchannel("A")
    shadow = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    shadow_alpha = Image.new("L", canvas.size, 0)
    shadow_alpha.paste(alpha, (box[0] + offset, box[1] + offset))
    shadow_alpha = shadow_alpha.filter(ImageFilter.GaussianBlur(12))
    shadow.putalpha(shadow_alpha.point(lambda value: value * 80 // 255))
    canvas.alpha_composite(shadow)
    canvas.alpha_composite(image, (box[0], box[1]))


def render_thumbnail(metadata: dict, profile, output: Path, font_info: FontInfo | None = None) -> ThumbnailResult:
    accepted = metadata.get("metadata", metadata)
    thumbnail = accepted.get("thumbnail", {}) if isinstance(accepted, dict) else {}
    lines = thumbnail.get("lines", []) if isinstance(thumbnail, dict) else []
    if not isinstance(lines, list) or not 1 <= len(lines) <= 2 or any(not isinstance(line, str) or not line.strip() for line in lines):
        raise ThumbnailError("thumbnail requires one or two non-empty lines")
    if any(len(re.sub(r"\s+", "", line)) > 16 for line in lines):
        raise ThumbnailError("thumbnail line exceeds 16 visible characters")

    output = Path(output).resolve()
    book_path = Path(profile.book.path).resolve()
    character_path = Path(profile.character.path).resolve()
    if output in {book_path, character_path}:
        raise ThumbnailError("output path equals a source asset")
    if output.exists():
        raise ThumbnailError(f"refusing to overwrite existing thumbnail: {output}")
    before_book = _sha256(book_path)
    before_character = _sha256(character_path)
    if before_book != profile.book.sha256 or before_character != profile.character.sha256:
        raise ThumbnailError("source asset SHA-256 differs from the validated profile")

    with Image.open(book_path) as source_book, Image.open(character_path) as source_character:
        book = source_book.convert("RGBA")
        character = source_character.convert("RGBA")
    if character.getchannel("A").getextrema()[0] == 255:
        raise ThumbnailError("character requires transparent alpha pixels")

    canvas = Image.new("RGBA", (1280, 720), (246, 241, 229, 255))
    draw = ImageDraw.Draw(canvas)
    draw.rounded_rectangle((36, 36, 642, 684), radius=36, fill=(255, 252, 245, 235), outline=(223, 209, 184, 255), width=3)
    draw.ellipse((1010, -110, 1370, 250), fill=(225, 241, 245, 255))
    draw.ellipse((-100, 565, 260, 870), fill=(255, 225, 180, 180))

    font_info = font_info or bundled_font()
    face, font_size, dimensions = _fit_title(draw, [line.strip() for line in lines], font_info)
    y = TEXT_REGION[1]
    actual_text_boxes: list[tuple[int, int, int, int]] = []
    for line, (line_width, line_height) in zip(lines, dimensions):
        x = TEXT_REGION[0]
        draw.text((x, y), line.strip(), font=face, fill=(26, 34, 48, 255), stroke_width=1, stroke_fill=(26, 34, 48, 255))
        actual_text_boxes.append((x, y, x + line_width, y + line_height))
        y += line_height + 16
    text_box = (
        min(item[0] for item in actual_text_boxes),
        min(item[1] for item in actual_text_boxes),
        max(item[2] for item in actual_text_boxes),
        max(item[3] for item in actual_text_boxes),
    )

    fitted_book, book_box = _fit_image(book, BOOK_REGION)
    fitted_character, character_box = _fit_image(character, CHARACTER_REGION)
    if boxes_overlap(text_box, character_box):
        raise ThumbnailError("thumbnail text collides with the character")
    _paste_shadow(canvas, fitted_book, book_box)
    _paste_shadow(canvas, fitted_character, character_box, offset=7)

    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + ".tmp.png")
    canvas.convert("RGB").save(temporary, format="PNG", optimize=True)
    with Image.open(temporary) as rendered:
        if rendered.size != (1280, 720) or rendered.mode != "RGB":
            temporary.unlink(missing_ok=True)
            raise ThumbnailError("rendered thumbnail contract mismatch")
    temporary.replace(output)
    if before_book != _sha256(book_path) or before_character != _sha256(character_path):
        raise ThumbnailError("source asset changed during thumbnail rendering")
    return ThumbnailResult(
        output,
        1280,
        720,
        font_size,
        font_info.path,
        book_box,
        character_box,
        text_box,
        before_book,
        before_character,
    )
