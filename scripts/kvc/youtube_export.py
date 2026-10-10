from __future__ import annotations

from pathlib import Path


class YoutubeExportError(ValueError):
    """Raised when copy-ready YouTube text cannot be exported safely."""


def _clock(ms: int) -> str:
    s = int(ms) // 1000
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    return f"{h}:{m:02d}:{sec:02d}" if h else f"{m}:{sec:02d}"


def _merge_hashtags(defaults: tuple[str, ...], proposed: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for tag in (*defaults, *proposed):
        folded = tag.casefold()
        if folded not in seen:
            result.append(tag)
            seen.add(folded)
    return result


def export_youtube_text(metadata: dict, profile, output: Path) -> dict[str, Path]:
    if metadata.get("accepted") is not True:
        raise YoutubeExportError("metadata must be accepted before export")
    accepted = metadata.get("metadata")
    if not isinstance(accepted, dict):
        raise YoutubeExportError("accepted metadata object is missing")
    output = Path(output)
    names = {"title": "title.txt", "alternative_titles": "alternative-titles.txt", "description": "description.md", "hashtags": "hashtags.txt"}
    paths = {key: output / name for key, name in names.items()}
    existing = [path for path in paths.values() if path.exists()]
    if existing:
        raise YoutubeExportError(f"refusing to overwrite existing output: {existing[0]}")

    hashtags = _merge_hashtags(tuple(profile.default_hashtags), list(accepted.get("hashtags", [])))
    lines = [accepted["description"]["intro"].strip(), "", "## 영상에서 다루는 내용"]
    lines.extend(f"- {item['text'].strip()}" for item in accepted.get("highlights", []))
    if accepted.get("chapters"):
        lines.extend(["", "## 챕터"])
        lines.extend(f"{_clock(ms)} {title}" for ms, title in metadata.get("chapter_times", []))
    if profile.book_title:
        lines.extend(["", "## 소개한 책", f"- 도서명: {profile.book_title}"])
        if profile.publisher:
            lines.append(f"- 출판사: {profile.publisher}")
        if profile.book_url:
            lines.append(f"- 도서 링크: {profile.book_url}")
    if profile.footer_lines:
        lines.extend(["", *profile.footer_lines])
    lines.extend(["", " ".join(hashtags)])
    contents = {
        "title": accepted["title"]["text"].strip() + "\n",
        "alternative_titles": "\n".join(item["text"].strip() for item in accepted["alternative_titles"]) + "\n",
        "description": "\n".join(lines).rstrip() + "\n",
        "hashtags": " ".join(hashtags) + "\n",
    }
    output.mkdir(parents=True, exist_ok=True)
    for key, content in contents.items():
        paths[key].write_text(content, encoding="utf-8")
    return paths
