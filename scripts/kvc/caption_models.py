from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class WordEvidence:
    id: str
    start_ms: int
    end_ms: int
    text: str
    probability: float
    source_chunk: str
    segment_id: int


@dataclass(frozen=True)
class SegmentEvidence:
    id: int
    start_ms: int
    end_ms: int
    text: str
    avg_logprob: float
    no_speech_prob: float
    compression_ratio: float
    word_ids: tuple[str, ...]


def words_to_json(words: list[WordEvidence]) -> dict:
    return {"schema_version": 1, "words": [asdict(word) for word in words]}


def words_from_json(value: dict) -> list[WordEvidence]:
    if not isinstance(value, dict) or value.get("schema_version") != 1:
        raise ValueError("unsupported words schema")
    items = value.get("words")
    if not isinstance(items, list):
        raise ValueError("words must be a list")
    words = [WordEvidence(**item) for item in items]
    if len({word.id for word in words}) != len(words):
        raise ValueError("duplicate word id")
    previous_end = -1
    for word in words:
        if not word.id or not word.text or word.end_ms <= word.start_ms:
            raise ValueError("invalid word evidence")
        if not 0.0 <= word.probability <= 1.0:
            raise ValueError("invalid word probability")
        if word.start_ms < previous_end:
            raise ValueError("non-monotonic word timing")
        previous_end = word.end_ms
    return words
