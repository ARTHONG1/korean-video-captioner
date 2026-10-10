from __future__ import annotations

from dataclasses import dataclass
import re
from pathlib import Path

from .caption_models import WordEvidence
from .srt import _stamp


@dataclass(frozen=True)
class PublicationEvent:
    id: int
    start_ms: int
    end_ms: int
    lines: tuple[str, ...]
    source_cue_ids: tuple[int, ...]
    source_word_ids: tuple[str, ...]

    @property
    def text(self) -> str:
        return "\n".join(self.lines)


def weighted_units(text: str) -> float:
    return sum(1.0 if "가" <= ch <= "힣" else 0.5 for ch in text)


def _wrap(text: str, limit: float) -> list[str]:
    tokens = text.split()
    if not tokens:
        return []
    lines: list[str] = []
    current = ""
    for token in tokens:
        candidate = token if not current else f"{current} {token}"
        if current and weighted_units(candidate) > limit:
            lines.append(current)
            current = token
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines


def build_publication_events(
    words: list[WordEvidence],
    resolved_items: list[dict],
    *,
    max_line_units: float = 16.0,
    max_lines: int = 2,
    min_ms: int = 830,
    max_ms: int = 7000,
) -> list[PublicationEvent]:
    by_id = {word.id: word for word in words}
    events: list[PublicationEvent] = []
    next_id = 1
    for item in resolved_items:
        ids = [str(value) for value in item.get("source_word_ids", [])]
        source = [by_id[value] for value in ids if value in by_id]
        text = str(item.get("corrected_text", "")).strip()
        if not source or not text:
            continue
        lines = _wrap(text, max_line_units)
        for offset in range(0, len(lines), max_lines):
            group = lines[offset:offset + max_lines]
            ratio_a = offset / max(1, len(lines))
            ratio_b = min(1.0, (offset + len(group)) / max(1, len(lines)))
            a = max(0, int(len(source) * ratio_a))
            b = max(a + 1, int(len(source) * ratio_b))
            part = source[a:b]
            start = part[0].start_ms
            end = max(part[-1].end_ms, start + min_ms)
            if end - start > max_ms:
                end = start + max_ms
            events.append(PublicationEvent(next_id, start, end, tuple(group), (int(item["id"]),), tuple(word.id for word in part)))
            next_id += 1
    return events


def write_publication_srt(path: Path, events: list[PublicationEvent]) -> None:
    blocks = []
    for event in events:
        blocks.append(f"{event.id}\n{_stamp(event.start_ms)} --> {_stamp(event.end_ms)}\n{event.text}")
    path.write_text("\n\n".join(blocks) + ("\n\n" if blocks else ""), encoding="utf-8", newline="\n")
