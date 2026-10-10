from __future__ import annotations

from dataclasses import dataclass

from .caption_validation import ValidationResult
from .quality import QualityWarning


@dataclass(frozen=True)
class ResolvedItem:
    cue_id: int
    text: str
    source_word_ids: tuple[str, ...]
    selected_source: str
    warning: QualityWarning | None


def validate_critic_proposal(batch: dict, editor: dict, critic: dict) -> ValidationResult:
    reviews: list[dict] = []
    if critic.get("schema_version") != 1 or critic.get("batch_id") != batch.get("batch_id"):
        return ValidationResult(False, (), ({"id": None, "code": "invalid_schema", "detail": "critic batch mismatch"},))
    expected = {item.get("id") for item in batch.get("items", [])}
    items = critic.get("items")
    if not isinstance(items, list) or {item.get("id") for item in items} != expected:
        return ValidationResult(False, (), ({"id": None, "code": "missing_or_duplicate_cue", "detail": "critic must cover every cue"},))
    accepted = []
    for item in items:
        if item.get("decision") not in {"accept", "revise", "needs_asr_retry"}:
            reviews.append({"id": item.get("id"), "code": "invalid_critic_decision", "detail": "unsupported critic decision"})
        elif not isinstance(item.get("reasons"), list) or not item.get("reasons"):
            reviews.append({"id": item.get("id"), "code": "missing_critic_reason", "detail": "critic reason is required"})
        else:
            accepted.append(item)
    return ValidationResult(not reviews, tuple(accepted), tuple(reviews))


def items_requiring_retry(critic: dict) -> tuple[int, ...]:
    return tuple(item["id"] for item in critic.get("items", []) if item.get("decision") == "needs_asr_retry")


def build_retry_span(start_ms: int, end_ms: int, duration_ms: int, padding_ms: int = 1_000) -> tuple[int, int]:
    if start_ms < 0 or end_ms <= start_ms or duration_ms <= 0:
        raise ValueError("invalid retry span")
    return max(0, start_ms - padding_ms), min(duration_ms, end_ms + padding_ms)


def retry_allowed(completed_attempts: int, max_attempts: int = 2) -> bool:
    if completed_attempts < 0 or max_attempts < 0:
        raise ValueError("retry counts must be non-negative")
    return completed_attempts < max_attempts


def resolve_item(
    raw: dict,
    editor: dict,
    critic: dict,
    alternatives: list[dict],
    trusted_terms: list[str],
) -> ResolvedItem:
    cue_id = int(raw["cue_id"])
    source_ids = tuple(raw.get("source_word_ids", ()))
    if critic.get("decision") == "accept":
        return ResolvedItem(cue_id, editor["text"], source_ids, "editor", None)
    ranked = sorted(
        (candidate for candidate in alternatives if candidate.get("text")),
        key=lambda candidate: float(candidate.get("avg_probability", 0.0)),
        reverse=True,
    )
    if ranked and float(ranked[0].get("avg_probability", 0.0)) >= 0.85:
        return ResolvedItem(cue_id, ranked[0]["text"], source_ids, "alternate_asr", None)
    warning = QualityWarning(cue_id, "ambiguous_asr", "근거가 부족해 원문 보존 후보를 자동 선택함")
    return ResolvedItem(cue_id, raw["text"], source_ids, "raw_conservative", warning)
