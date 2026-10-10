"""Natural pause and filler editing plan.

Only silence is removed. A cut is accepted only when every check passes:
audio is quiet across the cut and its edges, no kept word is touched, the
screen is still, the webcam does not jump, and the cadence limits hold.
Anything uncertain is skipped and recorded with a reason.
"""
from __future__ import annotations

import math
import re
import unicodedata
from dataclasses import dataclass, field
from fractions import Fraction
from typing import Protocol

import numpy as np

from .models import Cue
from .pause_signal import HOP_S, Levels
from .tips import END as TIP_END, START as TIP_START

FILLER_TOKENS = {"어", "음", "으", "엄", "아", "어어", "음음", "어음", "흠", "에"}
FILLER_ONSET_TOLERANCE_S = 0.15
SPEECH_MARGIN_S = 0.06
EDGE_QUIET_MARGIN_DB = 3.0


@dataclass(frozen=True)
class Rule:
    min_gap_s: float
    keep_s: float


@dataclass(frozen=True)
class PauseConfig:
    strength: str = "normal"
    within: Rule = Rule(0.8, 0.35)
    sentence: Rule = Rule(1.0, 0.6)
    topic: Rule = Rule(1.5, 1.0)
    topic_gap_s: float = 3.0
    tip_context_s: float = 1.5
    min_cut_s: float = 0.25
    min_piece_s: float = 1.2
    density_window_s: float = 10.0
    max_cuts_per_window: int = 3
    max_reduction: float = 0.15
    edge_guard_s: float = 1.0
    # Measured on 192x108 gray frames (18k screen pixels): cursor blink and codec noise
    # change 5-20 pixels, real scrolling/typing/window changes hundreds to thousands.
    screen_activity_px: int = 60
    screen_jump_px: int = 60
    webcam_jump_fraction: float = 0.12
    snap_search_s: float = 0.04

    @classmethod
    def for_strength(cls, strength: str) -> "PauseConfig":
        if strength == "normal":
            return cls()
        if strength == "gentle":
            return cls(strength="gentle", within=Rule(1.2, 0.5), sentence=Rule(1.5, 0.8), topic=Rule(2.0, 1.2))
        raise ValueError(f"unknown pause strength: {strength}")

    def as_dict(self) -> dict:
        return {
            "strength": self.strength,
            "within": vars(self.within), "sentence": vars(self.sentence), "topic": vars(self.topic),
            "min_cut_s": self.min_cut_s, "min_piece_s": self.min_piece_s,
            "density": f"<= {self.max_cuts_per_window} cuts per {self.density_window_s:g}s",
            "max_reduction": self.max_reduction, "edge_guard_s": self.edge_guard_s,
            "screen_activity_px": self.screen_activity_px, "screen_jump_px": self.screen_jump_px,
            "webcam_jump_fraction": self.webcam_jump_fraction,
        }


class ActivityProbe(Protocol):
    def activity_between(self, start_s: float, end_s: float) -> int: ...
    def jump(self, start_s: float, end_s: float) -> tuple[int, float]: ...


def normalize_token(text: str) -> str:
    return re.sub(r"[\s,.?!…~·\-]+", "", unicodedata.normalize("NFKC", str(text))).casefold()


# ---------------------------------------------------------------- candidates

def filler_candidates(words: list[dict], cues: list[Cue]) -> list[dict]:
    """Deterministic prefilter for Codex review: isolated filler words and immediate repeats."""
    ordered = sorted(words, key=lambda w: (w["start_ms"], w["end_ms"]))
    cue_at = _cue_lookup(cues)
    result: list[dict] = []
    for index, word in enumerate(ordered):
        token = normalize_token(word["text"])
        if token not in FILLER_TOKENS:
            continue
        before = word["start_ms"] - ordered[index - 1]["end_ms"] if index else 10_000
        after = ordered[index + 1]["start_ms"] - word["end_ms"] if index + 1 < len(ordered) else 10_000
        if before < 150 or after < 150 or word["end_ms"] - word["start_ms"] > 1200:
            continue
        cue = cue_at(word["start_ms"])
        result.append({"id": f"f-{len(result) + 1:04d}", "kind": "filler", "word_ids": [word["id"]],
                       "text": word["text"].strip(), "start_ms": word["start_ms"], "end_ms": word["end_ms"],
                       "cue_id": cue.id if cue else None, "cue_text": cue.text if cue else ""})
    used: set[str] = {wid for item in result for wid in item["word_ids"]}
    for size in (3, 2, 1):
        for index in range(len(ordered) - 2 * size + 1):
            first = ordered[index:index + size]
            second = ordered[index + size:index + 2 * size]
            if any(w["id"] in used for w in first + second):
                continue
            a = [normalize_token(w["text"]) for w in first]
            b = [normalize_token(w["text"]) for w in second]
            if a != b or not all(a) or sum(len(t) for t in a) < 1:
                continue
            if second[0]["start_ms"] - first[-1]["end_ms"] < 100:
                continue
            cue = cue_at(first[0]["start_ms"])
            result.append({"id": f"r-{len(result) + 1:04d}", "kind": "repetition", "word_ids": [w["id"] for w in first],
                           "text": " ".join(w["text"].strip() for w in first),
                           "repeated_by": [w["id"] for w in second],
                           "start_ms": first[0]["start_ms"], "end_ms": first[-1]["end_ms"],
                           "cue_id": cue.id if cue else None, "cue_text": cue.text if cue else ""})
            used.update(w["id"] for w in first + second)
    return sorted(result, key=lambda item: item["start_ms"])


def validate_filler_review(candidates: list[dict], review: dict | None) -> tuple[list[dict], list[dict]]:
    """Accept only reviewed candidates marked remove with a reason; anything else is kept."""
    if not review:
        return [], [{"code": "missing_filler_review", "detail": "no filler removal without a Codex review"}]
    by_id = {item["id"]: item for item in candidates}
    accepted, problems = [], []
    if review.get("schema_version") != 1 or not isinstance(review.get("items"), list):
        return [], [{"code": "invalid_filler_review", "detail": "schema_version 1 with items[] required"}]
    for item in review["items"]:
        candidate = by_id.get(item.get("id"))
        if candidate is None:
            problems.append({"code": "unknown_candidate", "id": item.get("id")})
            continue
        if item.get("decision") != "remove":
            continue
        if list(item.get("word_ids", candidate["word_ids"])) != candidate["word_ids"]:
            problems.append({"code": "word_ids_changed", "id": candidate["id"]})
            continue
        if not str(item.get("reason", "")).strip():
            problems.append({"code": "missing_reason", "id": candidate["id"]})
            continue
        accepted.append(candidate)
    return accepted, problems


# ---------------------------------------------------------------- planning

@dataclass
class Cut:
    kind: str
    context: str
    start_s: float
    end_s: float
    start_frame: int
    end_frame: int
    gap_s: float
    kept_s: float
    word_ids: tuple[str, ...] = ()
    candidate_id: str | None = None

    @property
    def removed_s(self) -> float:
        return self.end_s - self.start_s


@dataclass
class PlanResult:
    status: str
    cuts: list[Cut]
    skipped: list[dict] = field(default_factory=list)
    problems: list[dict] = field(default_factory=list)
    removed_s: float = 0.0
    ratio: float = 0.0


def _cue_lookup(cues: list[Cue]):
    ordered = sorted(cues, key=lambda c: c.start_ms)

    def find(ms: int) -> Cue | None:
        best = None
        for cue in ordered:
            if cue.start_ms <= ms < cue.end_ms:
                return cue
            if cue.start_ms <= ms:
                best = cue
        return best
    return find


def _tip_marker_spans(cues: list[Cue]) -> list[tuple[float, float]]:
    spans = []
    for cue in cues:
        text = unicodedata.normalize("NFKC", cue.text)
        if TIP_START.search(text) or TIP_END.search(text):
            spans.append((cue.start_ms / 1000, cue.end_ms / 1000))
    return spans


def _index(seconds: float) -> int:
    return int(math.floor(seconds / HOP_S + 1e-9))


class _Audio:
    def __init__(self, env: np.ndarray, levels: Levels):
        self.env = env
        self.quiet_db = levels.threshold_db
        self.edge_db = levels.threshold_db - EDGE_QUIET_MARGIN_DB

    def windows(self, start_s: float, end_s: float) -> np.ndarray:
        a, b = max(0, _index(start_s)), min(len(self.env), _index(end_s) + 1)
        return self.env[a:b] if b > a else self.env[0:0]

    def quiet(self, start_s: float, end_s: float, level: float | None = None) -> bool:
        values = self.windows(start_s, end_s)
        return values.size > 0 and bool(np.all(values <= (self.quiet_db if level is None else level)))

    def longest_quiet_run(self, start_s: float, end_s: float) -> tuple[float, float] | None:
        a = max(0, _index(start_s))
        values = self.windows(start_s, end_s)
        best, run_start = None, None
        for offset, value in enumerate(list(values) + [np.inf]):
            if value <= self.quiet_db:
                if run_start is None:
                    run_start = offset
            elif run_start is not None:
                if best is None or offset - run_start > best[1] - best[0]:
                    best = (run_start, offset)
                run_start = None
        if best is None:
            return None
        return (a + best[0]) * HOP_S, (a + best[1]) * HOP_S

    def snap(self, target_s: float, low_s: float, high_s: float, search_s: float) -> float:
        low, high = max(low_s, target_s - search_s), min(high_s, target_s + search_s)
        if high <= low:
            return target_s
        a, b = _index(low), _index(high) + 1
        values = self.env[a:b]
        if values.size == 0:
            return target_s
        return min(max((a + int(np.argmin(values))) * HOP_S + HOP_S / 2, low), high)


def plan_pause_edits(
    *,
    words: list[dict],
    cues: list[Cue],
    env: np.ndarray,
    levels: Levels,
    activity: ActivityProbe,
    fps,
    total_frames: int,
    config: PauseConfig = PauseConfig(),
    removals: list[dict] | None = None,
    review_problems: list[dict] | None = None,
) -> PlanResult:
    fps = Fraction(fps)
    duration = total_frames / float(fps)
    problems = list(review_problems or [])
    if not levels.separable:
        return PlanResult("NOT_SEPARABLE", [], [], problems + [{"code": "speech_not_separable_from_room_tone", "detail": levels.as_dict()}])

    audio = _Audio(env, levels)
    ordered = sorted((w for w in words if str(w.get("text", "")).strip()), key=lambda w: (w["start_ms"], w["end_ms"]))
    removal_ids = {wid for item in (removals or []) for wid in item["word_ids"]}
    removal_by_word = {wid: item for item in (removals or []) for wid in item["word_ids"]}
    kept = [w for w in ordered if w["id"] not in removal_ids]
    kept_spans = [(w["start_ms"] / 1000, w["end_ms"] / 1000) for w in kept]
    cue_at = _cue_lookup(cues)
    tips = _tip_marker_spans(cues)
    skipped: list[dict] = []
    proposals: list[Cut] = []

    def near_tip(a: float, b: float) -> bool:
        return any(a - config.tip_context_s <= te and ts <= b + config.tip_context_s for ts, te in tips)

    def touches_kept_word(a: float, b: float) -> bool:
        return any(ws < b + 0.05 and we > a - 0.05 for ws, we in kept_spans)

    def screen_ok(a: float, b: float, record: dict) -> bool:
        if activity.activity_between(a, b) > config.screen_activity_px:
            skipped.append({**record, "reason": "screen_activity"})
            return False
        screen_px, cam_fraction = activity.jump(a, b)
        if screen_px > config.screen_jump_px:
            skipped.append({**record, "reason": "screen_jump"})
            return False
        if cam_fraction > config.webcam_jump_fraction:
            skipped.append({**record, "reason": "webcam_jump"})
            return False
        return True

    def frame_align(a: float, b: float) -> tuple[int, int, float, float]:
        start_frame = math.ceil(a * float(fps) - 1e-9)
        end_frame = math.floor(b * float(fps) + 1e-9)
        return start_frame, end_frame, start_frame / float(fps), end_frame / float(fps)

    for prev, nxt in zip(kept, kept[1:]):
        ps, ne = prev["end_ms"] / 1000, nxt["start_ms"] / 1000
        gap = ne - ps
        if gap <= 0:
            continue
        inside = [w for w in ordered if w["id"] in removal_ids and w["start_ms"] / 1000 >= ps - 1e-6 and w["end_ms"] / 1000 <= ne + 1e-6]
        prev_cue, next_cue = cue_at(prev["start_ms"]), cue_at(nxt["start_ms"])
        crosses = prev_cue is not None and next_cue is not None and prev_cue.id != next_cue.id
        if near_tip(ps, ne) or (crosses and gap >= config.topic_gap_s):
            context, rule = "topic", config.topic
        elif crosses:
            context, rule = "sentence", config.sentence
        else:
            context, rule = "within", config.within
        record = {"at_s": round(ps, 3), "gap_s": round(gap, 3), "context": context}
        if ps < config.edge_guard_s or ne > duration - config.edge_guard_s:
            if gap > rule.min_gap_s or inside:
                skipped.append({**record, "reason": "edge_guard"})
            continue

        if inside:
            item = removal_by_word[inside[0]["id"]]
            record.update({"kind": item["kind"], "candidate_id": item["id"]})
            rs, re_ = inside[0]["start_ms"] / 1000, inside[-1]["end_ms"] / 1000
            bmax = (rs - FILLER_ONSET_TOLERANCE_S) - ps
            amax = ne - (re_ + FILLER_ONSET_TOLERANCE_S)
            if bmax < SPEECH_MARGIN_S or amax < SPEECH_MARGIN_S:
                skipped.append({**record, "reason": "filler_not_isolated"})
                continue
            keep = min(rule.keep_s, gap)
            before = min(keep * 0.6, bmax)
            after = min(max(keep - before, SPEECH_MARGIN_S), amax)
            if before + after < min(0.25, keep):
                skipped.append({**record, "reason": "filler_gap_too_tight"})
                continue
            a = audio.snap(ps + before, ps + SPEECH_MARGIN_S, rs - FILLER_ONSET_TOLERANCE_S, config.snap_search_s)
            b = audio.snap(ne - after, re_ + FILLER_ONSET_TOLERANCE_S, ne - SPEECH_MARGIN_S, config.snap_search_s)
            start_frame, end_frame, a, b = frame_align(a, b)
            loud_ok = audio.quiet(a, rs - FILLER_ONSET_TOLERANCE_S) and audio.quiet(re_ + FILLER_ONSET_TOLERANCE_S, b)
            edges_ok = audio.quiet(a - 0.03, a + 0.03, audio.edge_db) and audio.quiet(b - 0.03, b + 0.03, audio.edge_db)
            if not (loud_ok and edges_ok):
                skipped.append({**record, "reason": "filler_edges_not_quiet"})
                continue
            if b - a < config.min_cut_s or touches_kept_word(a, b):
                skipped.append({**record, "reason": "filler_cut_unsafe"})
                continue
            if not screen_ok(a, b, record):
                continue
            proposals.append(Cut(item["kind"], context, a, b, start_frame, end_frame, gap, gap - (b - a),
                                 tuple(w["id"] for w in inside), item["id"]))
            continue

        if gap <= rule.min_gap_s:
            continue
        record["kind"] = "pause"
        run = audio.longest_quiet_run(ps, ne)
        if run is None:
            skipped.append({**record, "reason": "no_quiet_audio"})
            continue
        qs, qe = run
        a = max(ps + rule.keep_s * 0.6, qs + SPEECH_MARGIN_S)
        b = min(ne - rule.keep_s * 0.4, qe - SPEECH_MARGIN_S)
        if b - a < config.min_cut_s:
            skipped.append({**record, "reason": "quiet_run_too_short"})
            continue
        a = audio.snap(a, qs + SPEECH_MARGIN_S, b, config.snap_search_s)
        b = audio.snap(b, a, qe - SPEECH_MARGIN_S, config.snap_search_s)
        start_frame, end_frame, a, b = frame_align(a, b)
        if b - a < config.min_cut_s:
            skipped.append({**record, "reason": "quiet_run_too_short"})
            continue
        if not (audio.quiet(a - 0.03, b + 0.03) and audio.quiet(a - 0.03, a + 0.03, audio.edge_db)
                and audio.quiet(b - 0.03, b + 0.03, audio.edge_db)):
            skipped.append({**record, "reason": "edges_not_quiet"})
            continue
        if touches_kept_word(a, b):
            skipped.append({**record, "reason": "touches_word"})
            continue
        if not screen_ok(a, b, record):
            continue
        proposals.append(Cut("pause", context, a, b, start_frame, end_frame, gap, gap - (b - a)))

    # Cadence: keep the most valuable cuts that respect spacing and density.
    accepted: list[Cut] = []
    for cut in sorted(proposals, key=lambda c: (c.kind == "pause", -c.removed_s)):
        record = {"at_s": round(cut.start_s, 3), "gap_s": round(cut.gap_s, 3), "context": cut.context, "kind": cut.kind}
        if cut.candidate_id:
            record["candidate_id"] = cut.candidate_id
        spaced = all(cut.start_s - other.end_s >= config.min_piece_s or other.start_s - cut.end_s >= config.min_piece_s
                     for other in accepted)
        if not spaced:
            skipped.append({**record, "reason": "piece_too_short"})
            continue
        trial = sorted([other.start_s for other in accepted] + [cut.start_s])
        crowded = any(sum(1 for t in trial if s <= t < s + config.density_window_s) > config.max_cuts_per_window
                      for s in trial)
        if crowded:
            skipped.append({**record, "reason": "density_limit"})
            continue
        accepted.append(cut)
    accepted.sort(key=lambda c: c.start_s)
    removed = sum(c.removed_s for c in accepted)
    ratio = removed / duration if duration else 0.0
    if ratio > config.max_reduction:
        status = "LIMIT_EXCEEDED"
        problems.append({"code": "reduction_limit", "detail": f"{ratio:.1%} > {config.max_reduction:.0%}"})
    else:
        status = "PASS" if accepted else "NO_CUTS"
    return PlanResult(status, accepted, skipped, problems, removed, ratio)


def validate_plan(plan: dict, words: list[dict], env: np.ndarray, levels: Levels, config: PauseConfig) -> list[str]:
    """Independent re-check of a saved plan before rendering."""
    errors: list[str] = []
    audio = _Audio(env, levels)
    fps = Fraction(plan["fps"])
    removed_ids = {wid for cut in plan["cuts"] for wid in cut.get("word_ids", [])}
    kept = [(w["start_ms"] / 1000, w["end_ms"] / 1000) for w in words if w["id"] not in removed_ids and str(w.get("text", "")).strip()]
    previous_end = -1.0
    for cut in plan["cuts"]:
        a, b = cut["start_frame"] / float(fps), cut["end_frame"] / float(fps)
        if cut["end_frame"] <= cut["start_frame"] or a < previous_end:
            errors.append(f"{cut['id']}: frames out of order")
        if b - a < config.min_cut_s - 1e-6:
            errors.append(f"{cut['id']}: shorter than minimum cut")
        if any(ws < b + 0.05 and we > a - 0.05 for ws, we in kept):
            errors.append(f"{cut['id']}: overlaps a kept word")
        if not (audio.quiet(a - 0.03, a + 0.03, audio.edge_db) and audio.quiet(b - 0.03, b + 0.03, audio.edge_db)):
            errors.append(f"{cut['id']}: cut edge is not quiet")
        if cut["kind"] == "pause" and not audio.quiet(a, b):
            errors.append(f"{cut['id']}: pause cut contains sound")
        if previous_end >= 0 and a - previous_end < config.min_piece_s - 1e-6:
            errors.append(f"{cut['id']}: kept piece shorter than {config.min_piece_s}s")
        previous_end = b
    total = plan["total_frames"] / float(fps)
    if sum((c["end_frame"] - c["start_frame"]) / float(fps) for c in plan["cuts"]) / total > config.max_reduction + 1e-9:
        errors.append("reduction above limit")
    return errors


def plan_to_json(result: PlanResult, *, fps, total_frames: int, config: PauseConfig, levels: Levels, source: dict,
                 candidates: list[dict], filler_accepted: list[dict]) -> dict:
    fps = Fraction(fps)
    cuts = []
    for index, cut in enumerate(result.cuts, 1):
        cuts.append({
            "id": f"c-{index:04d}", "kind": cut.kind, "context": cut.context,
            "start_frame": cut.start_frame, "end_frame": cut.end_frame,
            "start_s": round(cut.start_s, 4), "end_s": round(cut.end_s, 4), "removed_s": round(cut.removed_s, 4),
            "gap_s": round(cut.gap_s, 4), "kept_pause_s": round(cut.kept_s, 4),
            "word_ids": list(cut.word_ids), "candidate_id": cut.candidate_id,
        })
    counts: dict[str, int] = {}
    for cut in result.cuts:
        counts[cut.kind] = counts.get(cut.kind, 0) + 1
    skipped_counts: dict[str, int] = {}
    for item in result.skipped:
        skipped_counts[item["reason"]] = skipped_counts.get(item["reason"], 0) + 1
    return {
        "schema_version": 1, "status": result.status, "source": source,
        "fps": f"{fps.numerator}/{fps.denominator}", "total_frames": total_frames,
        "duration_s": round(total_frames / float(fps), 3),
        "config": config.as_dict(), "levels": levels.as_dict(),
        "summary": {"cuts": len(cuts), "by_kind": counts, "removed_s": round(result.removed_s, 3),
                    "reduction_ratio": round(result.ratio, 4), "skipped": skipped_counts,
                    "filler_candidates": len(candidates), "filler_accepted": len(filler_accepted)},
        "cuts": cuts, "skipped": result.skipped, "problems": result.problems,
    }
