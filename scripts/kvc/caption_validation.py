from __future__ import annotations

import re
from dataclasses import dataclass

from .correction import validate_one


ALLOWED_OPERATIONS = {
    "unchanged", "remove_filler", "remove_stutter", "remove_repetition",
    "remove_false_start", "spacing", "spelling", "punctuation", "asr_correction",
}
_HANGUL_TOKEN = re.compile(r"[가-힣]{2,}")


@dataclass(frozen=True)
class ValidationResult:
    accepted: bool
    items: tuple[dict, ...]
    reviews: tuple[dict, ...]

    @property
    def codes(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(review["code"] for review in self.reviews))


def _review(item_id: object, code: str, detail: str) -> dict:
    return {"id": item_id, "code": code, "detail": detail}


def _terms(text: str) -> set[str]:
    return set(_HANGUL_TOKEN.findall(text))


def validate_editor_proposal(batch: dict, proposal: dict, context: dict) -> ValidationResult:
    reviews: list[dict] = []
    accepted_items: list[dict] = []
    if proposal.get("schema_version") != 1 or proposal.get("batch_id") != batch.get("batch_id"):
        return ValidationResult(False, (), (_review(None, "invalid_schema", "batch schema or ID mismatch"),))

    batch_items = {item["id"]: item for item in batch.get("items", [])}
    source_word_ids = {word_id for item in batch_items.values() for word_id in item.get("source_word_ids", [])}
    raw_text = " ".join(str(item.get("raw_text", "")) for item in batch_items.values())
    trusted_terms = {
        str(term.get("text", "")) for term in context.get("terms", [])
        if isinstance(term, dict)
    }
    trusted_hangul = set().union(*(_terms(term) for term in trusted_terms)) if trusted_terms else set()
    proposal_items = proposal.get("items")
    if not isinstance(proposal_items, list) or {item.get("id") for item in proposal_items} != set(batch_items):
        return ValidationResult(False, (), (_review(None, "missing_or_duplicate_cue", "exactly one proposal is required per editable cue"),))

    for item in proposal_items:
        item_id = item.get("id")
        source_ids = item.get("source_word_ids")
        corrected = item.get("corrected_text")
        operations = item.get("operations")
        if not isinstance(source_ids, list) or not source_ids:
            reviews.append(_review(item_id, "missing_source_word_id", "source_word_ids is required"))
            continue
        if any(word_id not in source_word_ids for word_id in source_ids):
            reviews.append(_review(item_id, "foreign_source_word_id", "proposal cites a word outside this batch"))
            continue
        if not isinstance(corrected, str) or not corrected.strip():
            reviews.append(_review(item_id, "empty_text", "corrected_text is empty"))
            continue
        if not isinstance(operations, list) or not operations or any(operation not in ALLOWED_OPERATIONS for operation in operations):
            reviews.append(_review(item_id, "invalid_operation", "operation is not in the allowed editor set"))
            continue
        if item.get("decision") != "accept" or item.get("confidence") not in {"high", "medium"}:
            reviews.append(_review(item_id, "editor_not_accepted", "editor decision/confidence does not permit promotion"))
            continue
        if not str(item.get("reason", "")).strip():
            reviews.append(_review(item_id, "missing_reason", "source-grounded reason is required"))
            continue
        base = batch_items[item_id]["raw_text"]
        checked = validate_one(base, corrected, "accept", {})
        if not checked.accepted:
            for code in checked.reasons:
                reviews.append(_review(item_id, code, "deterministic correction check failed"))
            continue
        added_hangul = _terms(corrected) - _terms(raw_text) - trusted_hangul
        if added_hangul:
            reviews.append(_review(item_id, "unsupported_term", "new Korean term lacks source or trusted context evidence"))
            continue
        accepted_items.append(item)
    return ValidationResult(not reviews, tuple(accepted_items), tuple(reviews))
