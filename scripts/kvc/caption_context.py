from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from .caption_models import WordEvidence
from .models import Cue


@dataclass(frozen=True)
class BatchWindow:
    batch_id: str
    edit_start_ms: int
    edit_end_ms: int
    items: tuple[dict, ...]
    context_before: tuple[dict, ...]
    context_after: tuple[dict, ...]


@dataclass(frozen=True)
class ContextValidation:
    accepted: bool
    codes: tuple[str, ...]
    context: dict


def _word_ids(cue: Cue, words: list[WordEvidence]) -> list[str]:
    return [word.id for word in words if word.end_ms > cue.start_ms and word.start_ms < cue.end_ms]


def _risk_flags(word_ids: list[str], words: dict[str, WordEvidence]) -> list[str]:
    return ["low_word_probability" for word_id in word_ids if words[word_id].probability < 0.55]


def build_batch_windows(
    cues: list[Cue],
    words: list[WordEvidence],
    target_ms: int = 60_000,
    max_ms: int = 90_000,
    context_ms: int = 15_000,
) -> list[BatchWindow]:
    if target_ms <= 0 or max_ms < target_ms or context_ms < 0:
        raise ValueError("invalid batch timing limits")
    ordered = sorted(cues, key=lambda cue: (cue.start_ms, cue.id))
    word_map = {word.id: word for word in words}
    groups: list[list[Cue]] = []
    current: list[Cue] = []
    for cue in ordered:
        proposed = current + [cue]
        span = proposed[-1].end_ms - proposed[0].start_ms
        if current and span > target_ms:
            groups.append(current)
            current = [cue]
        else:
            current = proposed
        if current and current[-1].end_ms - current[0].start_ms >= max_ms:
            groups.append(current)
            current = []
    if current:
        groups.append(current)

    batches: list[BatchWindow] = []
    for index, group in enumerate(groups, 1):
        edit_start, edit_end = group[0].start_ms, group[-1].end_ms
        before = tuple(
            {"id": cue.id, "raw_text": cue.text}
            for cue in ordered
            if cue.end_ms > edit_start - context_ms and cue.end_ms <= edit_start
        )
        after = tuple(
            {"id": cue.id, "raw_text": cue.text}
            for cue in ordered
            if cue.start_ms >= edit_end and cue.start_ms < edit_end + context_ms
        )
        items = []
        for cue in group:
            ids = _word_ids(cue, words)
            items.append(
                {
                    "id": cue.id,
                    "start_ms": cue.start_ms,
                    "end_ms": cue.end_ms,
                    "raw_text": cue.text,
                    "source_word_ids": ids,
                    "risk_flags": _risk_flags(ids, word_map),
                }
            )
        batches.append(BatchWindow(f"batch-{index:04d}", edit_start, edit_end, tuple(items), before, after))
    return batches


def write_correction_batches(
    output: Path,
    cues: list[Cue],
    words: list[WordEvidence],
    target_ms: int = 60_000,
    max_ms: int = 90_000,
    context_ms: int = 15_000,
) -> list[Path]:
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    written = []
    for batch in build_batch_windows(cues, words, target_ms, max_ms, context_ms):
        payload = {
            "schema_version": 1,
            "batch_id": batch.batch_id,
            "edit_start_ms": batch.edit_start_ms,
            "edit_end_ms": batch.edit_end_ms,
            "context_before": list(batch.context_before),
            "items": list(batch.items),
            "context_after": list(batch.context_after),
        }
        path = output / f"{batch.batch_id}.json"
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        written.append(path)
    return written


def validate_transcript_context(proposal: dict, source: dict) -> ContextValidation:
    codes: list[str] = []
    source_cues = {int(cue["id"]): str(cue["text"]) for cue in source.get("cues", [])}
    trusted = {str(term) for term in source.get("trusted_terms", [])}
    if proposal.get("schema_version") != 1 or not isinstance(proposal.get("terms"), list):
        return ContextValidation(False, ("invalid_schema",), {})
    accepted_terms = []
    for term in proposal["terms"]:
        text = str(term.get("text", "")).strip()
        ids = term.get("source_cue_ids", [])
        cited_text = " ".join(source_cues.get(int(cue_id), "") for cue_id in ids if str(cue_id).isdigit())
        if not text or not ids or any(int(cue_id) not in source_cues for cue_id in ids):
            codes.append("foreign_source_id")
            continue
        if text not in cited_text and text not in trusted:
            if re.search(r"[A-Za-z0-9]", text):
                codes.append("unsupported_token")
                codes.append("unsupported_term")
            else:
                codes.append("unsupported_term")
            continue
        accepted_terms.append({"text": text, "source_cue_ids": [int(cue_id) for cue_id in ids]})
    context = {"schema_version": 1, "terms": accepted_terms}
    return ContextValidation(not codes, tuple(dict.fromkeys(codes)), context)
