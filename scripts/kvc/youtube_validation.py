from __future__ import annotations

import re
import unicodedata
from copy import deepcopy
from dataclasses import dataclass

URL_RE = re.compile(r"https?://[^\s]+", re.IGNORECASE)
PROTECTED_RE = re.compile(r"[A-Za-z]+[A-Za-z0-9._-]*|\d[\d,.:-]*")
HASHTAG_RE = re.compile(r"#[^\s#]+")


@dataclass(frozen=True)
class ValidatedYoutubeMetadata:
    accepted: bool
    metadata: dict
    reviews: tuple[dict, ...]

    @property
    def reasons(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(review["code"] for review in self.reviews))


def _normalized(value: object) -> str:
    return unicodedata.normalize("NFKC", str(value)).casefold()


def _protected_tokens(text: str) -> tuple[str, ...]:
    return tuple(PROTECTED_RE.findall(URL_RE.sub(" ", unicodedata.normalize("NFKC", text))))


def chapter_times(source: dict, chapters: list) -> list[tuple[int, str]]:
    """Chapter list (ms, title) for the final video: optional intro chapter at 0, then each chapter at the
    final-video time of its first source cue. Without an intro the first chapter is pinned to 0."""
    cues = {cue.get("id"): cue for cue in source.get("cues", []) if isinstance(cue, dict)}
    settings = source.get("chapter_settings", {}) if isinstance(source, dict) else {}
    result: list[tuple[int, str]] = []
    if int(settings.get("intro_ms", 0)) > 0:
        result.append((0, str(settings.get("intro_label") or "미리보기")))
    for item in chapters:
        ids = item.get("source_cue_ids") or []
        cue = cues.get(ids[0]) if ids else None
        if cue is None:
            continue
        result.append((int(cue.get("out_start_ms", cue.get("start_ms", 0))), str(item.get("title", "")).strip()))
    if result and not int(settings.get("intro_ms", 0)) > 0:
        result[0] = (0, result[0][1])
    return result


def validate_youtube_proposal(source: dict, proposal: dict) -> ValidatedYoutubeMetadata:
    reviews: list[dict] = []
    cues = source.get("cues", []) if isinstance(source, dict) else []
    cue_text = {cue.get("id"): str(cue.get("text", "")) for cue in cues if isinstance(cue, dict)}
    cue_ids = set(cue_text)
    profile_facts = source.get("profile_facts", {}) if isinstance(source, dict) else {}
    profile_evidence = " ".join(str(value) for value in profile_facts.values() if value)

    def add(code: str, field: str, value: object, ids: object = None) -> None:
        reviews.append({"code": code, "field": field, "value": value, "source_cue_ids": list(ids) if isinstance(ids, (list, tuple)) else []})

    if not isinstance(proposal, dict):
        add("invalid_proposal", "$", proposal)
        return ValidatedYoutubeMetadata(False, {}, tuple(reviews))
    if proposal.get("schema_version") != 1:
        add("schema_version", "schema_version", proposal.get("schema_version"))
    if proposal.get("decision") != "accept":
        add("review_decision", "decision", proposal.get("decision"))

    def validate_evidence(field: str, text: object, ids: object) -> None:
        if not isinstance(text, str) or not text.strip():
            add("empty_text", field, text, ids)
            return
        if not isinstance(ids, list) or not ids:
            add("missing_source_cue_ids", field, text, ids)
            return
        foreign = [cue_id for cue_id in ids if cue_id not in cue_ids]
        if foreign:
            add("foreign_cue_id", field, foreign, ids)
            return
        evidence = " ".join(cue_text[cue_id] for cue_id in ids) + " " + profile_evidence
        evidence_normalized = _normalized(evidence)
        allowed_url = str(profile_facts.get("book_url", "")).strip()
        if any(url.rstrip(".,)") != allowed_url for url in URL_RE.findall(text)):
            add("unsupported_url", field, text, ids)
        for token in _protected_tokens(text):
            if _normalized(token) not in evidence_normalized:
                add("unsupported_token", field, token, ids)
                break

    title = proposal.get("title", {})
    title = title if isinstance(title, dict) else {}
    title_text = title.get("text", "")
    validate_evidence("title", title_text, title.get("source_cue_ids"))
    if isinstance(title_text, str) and len(title_text) > 70:
        add("title_too_long", "title", title_text, title.get("source_cue_ids"))

    alternatives = proposal.get("alternative_titles", [])
    if not isinstance(alternatives, list) or len(alternatives) != 2:
        add("alternative_title_count", "alternative_titles", alternatives)
        alternatives = alternatives if isinstance(alternatives, list) else []
    all_titles = [title_text]
    for index, alternative in enumerate(alternatives):
        alternative = alternative if isinstance(alternative, dict) else {}
        text = alternative.get("text", "")
        all_titles.append(text)
        validate_evidence(f"alternative_titles[{index}]", text, alternative.get("source_cue_ids"))
        if isinstance(text, str) and len(text) > 70:
            add("title_too_long", f"alternative_titles[{index}]", text, alternative.get("source_cue_ids"))
    normalized_titles = [_normalized(text).replace(" ", "") for text in all_titles if isinstance(text, str) and text]
    if len(normalized_titles) != len(set(normalized_titles)):
        add("duplicate_title", "alternative_titles", all_titles)

    thumbnail = proposal.get("thumbnail", {})
    thumbnail = thumbnail if isinstance(thumbnail, dict) else {}
    lines = thumbnail.get("lines", [])
    if not isinstance(lines, list) or not 1 <= len(lines) <= 2 or any(not isinstance(line, str) or not line.strip() for line in lines):
        add("thumbnail_line_count", "thumbnail.lines", lines, thumbnail.get("source_cue_ids"))
        lines = [line for line in lines if isinstance(line, str)] if isinstance(lines, list) else []
    for index, line in enumerate(lines):
        if len(re.sub(r"\s+", "", line)) > 16:
            add("thumbnail_line_too_long", f"thumbnail.lines[{index}]", line, thumbnail.get("source_cue_ids"))
    validate_evidence("thumbnail", " ".join(lines), thumbnail.get("source_cue_ids"))

    description = proposal.get("description", {})
    description = description if isinstance(description, dict) else {}
    validate_evidence("description.intro", description.get("intro", ""), description.get("source_cue_ids"))

    highlights = proposal.get("highlights", [])
    if not isinstance(highlights, list) or not 1 <= len(highlights) <= 5:
        add("highlight_count", "highlights", highlights)
        highlights = highlights if isinstance(highlights, list) else []
    seen_highlights: set[str] = set()
    for index, highlight in enumerate(highlights):
        highlight = highlight if isinstance(highlight, dict) else {}
        text = highlight.get("text", "")
        validate_evidence(f"highlights[{index}]", text, highlight.get("source_cue_ids"))
        normalized = _normalized(text).replace(" ", "")
        if normalized in seen_highlights:
            add("duplicate_highlight", f"highlights[{index}]", text, highlight.get("source_cue_ids"))
        seen_highlights.add(normalized)

    hashtags = proposal.get("hashtags", [])
    valid_hashtags = isinstance(hashtags, list) and 3 <= len(hashtags) <= 10
    if valid_hashtags:
        folded = [_normalized(tag) for tag in hashtags if isinstance(tag, str)]
        valid_hashtags = len(folded) == len(hashtags) and len(set(folded)) == len(folded) and all(HASHTAG_RE.fullmatch(tag) for tag in hashtags)
    if not valid_hashtags:
        add("invalid_hashtag", "hashtags", hashtags)
    else:
        global_evidence = _normalized(" ".join(cue_text.values()) + " " + profile_evidence)
        for tag in hashtags:
            for token in _protected_tokens(tag):
                if _normalized(token) not in global_evidence:
                    add("unsupported_token", "hashtags", token)
                    break

    chapters = proposal.get("chapters")
    if chapters is not None:
        if not isinstance(chapters, list):
            add("invalid_chapters", "chapters", chapters)
        else:
            for index, chapter in enumerate(chapters):
                chapter = chapter if isinstance(chapter, dict) else {}
                validate_evidence(f"chapters[{index}]", chapter.get("title", ""), chapter.get("source_cue_ids"))
                if isinstance(chapter.get("title"), str) and len(chapter["title"]) > 40:
                    add("chapter_title_too_long", f"chapters[{index}]", chapter["title"], chapter.get("source_cue_ids"))
            if not reviews:
                times = chapter_times(source, chapters)
                if len(times) < 3:
                    add("chapter_count", "chapters", len(times))
                for (t0, title0), (t1, title1) in zip(times, times[1:]):
                    if t1 - t0 < 10000:
                        add("chapter_spacing", "chapters", [title0, title1])
                titles = [_normalized(title).replace(" ", "") for _, title in times]
                if len(titles) != len(set(titles)):
                    add("duplicate_chapter", "chapters", titles)

    accepted = not reviews
    return ValidatedYoutubeMetadata(accepted, deepcopy(proposal) if accepted else {}, tuple(reviews))
