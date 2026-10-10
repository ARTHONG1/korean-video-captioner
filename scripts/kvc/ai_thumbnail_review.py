from __future__ import annotations


class ReviewError(ValueError):
    pass


SCORES = ("click_appeal", "reference_fidelity", "headline_readability", "cleanliness", "composition")
WEIGHTS = {"click_appeal": 30, "reference_fidelity": 25, "headline_readability": 25, "cleanliness": 10, "composition": 10}
GATES = ("references", "headline", "no_extra_text", "no_clipping", "no_watermark", "safe_zone")
TIE_ORDER = {"balanced": 0, "book-led": 1, "character-led": 2}


def validate_thumbnail_review(manifest: dict, review: dict) -> dict:
    known = {item.get("candidate_id"): item for item in manifest.get("calls", [])}
    candidates = review.get("candidates", []) if isinstance(review, dict) else []
    if not candidates or {item.get("candidate_id") for item in candidates} != set(known):
        raise ReviewError("review must contain every registered candidate exactly once")
    headline = review.get("headline")
    for item in candidates:
        if item.get("visible_headline") != headline:
            raise ReviewError("candidate headline does not match request")
        gates = item.get("hard_gates")
        scores = item.get("scores")
        if not isinstance(gates, dict) or any(gates.get(g) is not True for g in GATES):
            continue
        if not isinstance(scores, dict) or any(not isinstance(scores.get(s), (int, float)) or not 0 <= scores[s] <= 100 for s in SCORES):
            raise ReviewError("scores must contain 0-100 values")
        item["computed_score"] = round(sum(float(scores[s]) * WEIGHTS[s] / 100 for s in SCORES), 2)
    return review


def select_candidate(manifest: dict, review: dict) -> dict:
    review = validate_thumbnail_review(manifest, review)
    known = {item["candidate_id"]: item for item in manifest["calls"]}
    passing = [item for item in review["candidates"] if all(item["hard_gates"].get(g) is True for g in GATES) and item["computed_score"] >= 80]
    if not passing:
        raise ReviewError("no candidate passed all hard gates with score 80")
    passing.sort(key=lambda item: (-item["computed_score"], TIE_ORDER.get(known[item["candidate_id"]].get("variant"), 99)))
    winner = passing[0]
    if review.get("selected_candidate_id") != winner["candidate_id"]:
        raise ReviewError("selected candidate is not the highest-scoring passing candidate")
    return known[winner["candidate_id"]]
