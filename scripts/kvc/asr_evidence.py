from __future__ import annotations

import json
import re
from dataclasses import asdict
from pathlib import Path

from .caption_models import SegmentEvidence, WordEvidence, words_to_json


def _normalized(text: str) -> str:
    return re.sub(r"\s+", "", text).casefold()


def _overlap_ratio(left: WordEvidence, right: WordEvidence) -> float:
    overlap = max(0, min(left.end_ms, right.end_ms) - max(left.start_ms, right.start_ms))
    shorter = min(left.end_ms - left.start_ms, right.end_ms - right.start_ms)
    return overlap / shorter if shorter else 0.0


def merge_overlap_words(left: list[WordEvidence], right: list[WordEvidence]) -> list[WordEvidence]:
    merged = list(left)
    for candidate in right:
        matches = [
            index
            for index, existing in enumerate(merged)
            if _normalized(existing.text) == _normalized(candidate.text)
            and _overlap_ratio(existing, candidate) > 0.5
        ]
        if not matches:
            merged.append(candidate)
            continue
        index = matches[0]
        if candidate.probability > merged[index].probability:
            merged[index] = candidate
    return sorted(merged, key=lambda word: (word.start_ms, word.end_ms, word.id))


def segments_to_evidence(
    segments: list[object], chunk_start_ms: int, source_chunk: str, first_word_id: int = 1
) -> tuple[list[WordEvidence], list[SegmentEvidence]]:
    words: list[WordEvidence] = []
    segment_evidence: list[SegmentEvidence] = []
    next_word_id = first_word_id
    for segment_id, segment in enumerate(segments, 1):
        segment_word_ids: list[str] = []
        for word in getattr(segment, "words", ()) or ():
            if word.start is None or word.end is None:
                continue
            word_id = f"w-{next_word_id:06d}"
            words.append(
                WordEvidence(
                    id=word_id,
                    start_ms=chunk_start_ms + round(float(word.start) * 1000),
                    end_ms=chunk_start_ms + round(float(word.end) * 1000),
                    text=str(word.word).strip(),
                    probability=float(word.probability),
                    source_chunk=source_chunk,
                    segment_id=segment_id,
                )
            )
            segment_word_ids.append(word_id)
            next_word_id += 1
        segment_evidence.append(
            SegmentEvidence(
                id=segment_id,
                start_ms=chunk_start_ms + round(float(segment.start) * 1000),
                end_ms=chunk_start_ms + round(float(segment.end) * 1000),
                text=str(segment.text).strip(),
                avg_logprob=float(segment.avg_logprob),
                no_speech_prob=float(segment.no_speech_prob),
                compression_ratio=float(segment.compression_ratio),
                word_ids=tuple(segment_word_ids),
            )
        )
    return words, segment_evidence


def write_evidence(
    path: Path, words: list[WordEvidence], segments: list[SegmentEvidence], profile: dict
) -> None:
    payload = words_to_json(words)
    payload.update({"profile": profile, "segments": [asdict(segment) for segment in segments]})
    Path(path).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
