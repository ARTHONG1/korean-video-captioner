from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from .absence_driver import initialize_preprocess
from .paths import RuntimePaths
from .publish_profile import load_publish_profile


PHASES = (
    "initialized",
    "caption_ready",
    "publishing_source_ready",
    "metadata_validated",
    "thumbnail_request_ready",
    "thumbnail_candidates_ready",
    "thumbnail_reviewed",
    "publishing_finalized",
    "verified",
)
_ACTIONS = {
    "caption_pipeline": "caption_ready",
    "publishing_prepare": "publishing_source_ready",
    "metadata_validate": "metadata_validated",
    "thumbnail_request": "thumbnail_request_ready",
    "thumbnail_review": "thumbnail_reviewed",
    "publishing_finalize": "publishing_finalized",
    "verify": "verified",
}
_VARIANTS = ("book-led", "character-led", "balanced")
# Optional post-caption stages, run in this order before publishing_prepare. They never change the phase.
POST_STAGES = ("compact_edit", "intro_promo", "intro_join")


class WorkflowStateError(ValueError):
    pass


def _read(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise WorkflowStateError(f"invalid workflow state: {path}") from exc
    if not isinstance(value, dict) or value.get("schema_version") != 1:
        raise WorkflowStateError("unsupported workflow state schema")
    if value.get("phase") not in PHASES:
        raise WorkflowStateError("unknown workflow phase")
    return value


def _write(path: Path, value: dict) -> None:
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def plan_post_stages(mode: str, compact: bool | None = None, intro: bool | None = None, profile: dict | None = None) -> dict:
    """Compact edit and intro promo follow the personal publish profile unless the request overrides them."""
    profile = profile or load_publish_profile()
    use_compact = profile["compact_edit"]["enabled"] if compact is None else compact
    use_intro = profile["intro_promo"]["enabled"] if intro is None else intro
    if mode == "caption-only":
        use_compact = use_intro = False
    stages = {
        "compact_edit": {"enabled": bool(use_compact), "status": "PENDING" if use_compact else "SKIPPED"},
        "intro_promo": {"enabled": bool(use_intro), "status": "PENDING" if use_intro else "SKIPPED"},
        "intro_join": {"enabled": bool(use_intro), "status": "PENDING" if use_intro else "SKIPPED"},
    }
    stages["profile_source"] = profile.get("_source", "")
    return stages


def initialize_workflow(input_path: Path, run: Path, mode: str, webcam_preprocess: bool = False,
                        compact: bool | None = None, intro: bool | None = None) -> Path:
    """Create workflow state. Webcam-absence preprocessing runs only when explicitly requested.
    compact/intro: None = personal publish profile, False = the user excluded the stage for this video."""
    run = Path(run).resolve()
    run.mkdir(parents=True, exist_ok=True)
    state_path = run / "workflow-state.json"
    if state_path.exists():
        raise WorkflowStateError(f"refusing to reuse existing workflow: {state_path}")
    if mode not in {"full-publish", "caption-only", "publishing-only"}:
        raise WorkflowStateError(f"unsupported workflow mode: {mode}")
    preprocess = {"status": "SKIPPED", "reason": "publishing_only" if mode == "publishing-only" else "not_requested"}
    if mode != "publishing-only" and webcam_preprocess:
        preprocess_dir = run / "preprocess"
        try:
            preprocess = initialize_preprocess(Path(input_path), preprocess_dir, RuntimePaths.discover().ffprobe)
        except Exception as exc:
            preprocess = {"status": "WARNING", "reason": "preprocess_preflight_failed", "detail": type(exc).__name__}
    _write(
        state_path,
        {
            "schema_version": 1,
            "phase": "initialized",
            "mode": mode,
            "input_path": str(Path(input_path).resolve()),
            "effective_input_path": preprocess.get("effective_input", str(Path(input_path).resolve())),
            "preprocess": preprocess,
            "post_stages": plan_post_stages(mode, compact, intro),
            "run": str(run),
            "transitions": [],
            "generation_calls": [],
            "created_at": datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
        },
    )
    return state_path


def inspect_completed_artifacts(run: Path) -> dict:
    run = Path(run).resolve()
    names = (
        "corrected.srt",
        "final-captioned.mp4",
        "final-captioned-tips.mp4",
        "metadata-source.json",
        "metadata.json",
        "thumbnail-generation-request.json",
        "thumbnail-review.json",
        "thumbnail.png",
        "verify-youtube.json",
    )
    return {name: (run / name).is_file() and (run / name).stat().st_size > 0 for name in names}


def _state_path(value: Path | dict) -> Path:
    if isinstance(value, dict):
        raise WorkflowStateError("next_action requires a workflow-state.json path")
    path = Path(value)
    if path.name != "workflow-state.json":
        raise WorkflowStateError("expected workflow-state.json")
    return path


def next_action(state: Path | dict) -> dict:
    path = _state_path(state)
    value = _read(path)
    phase = value["phase"]
    transitions = value.get("transitions", [])
    stages = value.get("post_stages", {})

    def pending_stage() -> dict | None:
        for name in POST_STAGES:
            item = stages.get(name, {})
            if item.get("enabled") and item.get("status") not in ("DONE", "SKIPPED"):
                return {"action": "run_script", "name": name}
        return None

    if phase == "initialized":
        if value.get("mode") != "publishing-only" and value.get("preprocess", {}).get("status") == "ANALYZE":
            return {"action": "run_script", "name": "webcam_preprocess", "run": str(Path(value["run"]) / "preprocess")}
        artifacts = inspect_completed_artifacts(Path(value["run"]))
        if artifacts["corrected.srt"] and (artifacts["final-captioned.mp4"] or artifacts["final-captioned-tips.mp4"]):
            return pending_stage() or {"action": "run_script", "name": "publishing_prepare"}
        return {"action": "run_script", "name": "caption_pipeline"}
    if phase == "caption_ready":
        return pending_stage() or {"action": "run_script", "name": "publishing_prepare"}
    if phase == "publishing_source_ready":
        return {"action": "run_script", "name": "metadata_validate"}
    if phase == "metadata_validated":
        return {"action": "run_script", "name": "thumbnail_request"}
    if phase in {"thumbnail_request_ready", "thumbnail_candidates_ready"}:
        completed = {item.get("variant") for item in value.get("generation_calls", [])}
        for variant in _VARIANTS:
            if variant not in completed:
                return {"action": "invoke_imagegen", "variant": variant}
        return {"action": "inspect_candidates"}
    if phase == "thumbnail_reviewed":
        return {"action": "run_script", "name": "publishing_finalize"}
    if phase == "publishing_finalized":
        return {"action": "run_script", "name": "verify"}
    return {"action": "complete"}


def record_transition(state_path: Path, action: str, artifacts: dict) -> dict:
    state_path = Path(state_path)
    value = _read(state_path)
    if not isinstance(artifacts, dict) or not artifacts or any(not str(v) for v in artifacts.values()):
        raise WorkflowStateError("transition requires non-empty artifact fingerprints")
    phase = value["phase"]
    if action in POST_STAGES:
        if phase not in ("initialized", "caption_ready"):
            raise WorkflowStateError(f"{action} must run after captions and before publishing")
        stage = value.setdefault("post_stages", {}).setdefault(action, {"enabled": True})
        stage["status"] = "SKIPPED" if str(artifacts.get("status", "")).upper() == "SKIPPED" else "DONE"
        stage["artifacts"] = artifacts
    elif action.startswith("thumbnail_candidate_"):
        if phase != "thumbnail_request_ready":
            raise WorkflowStateError("thumbnail candidate is only valid after thumbnail request")
        variant = artifacts.get("variant") or {"1": "book-led", "2": "character-led", "3": "balanced"}.get(action.rsplit("_", 1)[-1])
        value.setdefault("generation_calls", []).append({"variant": variant, "artifacts": artifacts})
        value["phase"] = "thumbnail_candidates_ready" if len(value["generation_calls"]) >= 3 else "thumbnail_request_ready"
    else:
        target = _ACTIONS.get(action)
        if target is None:
            raise WorkflowStateError(f"unknown workflow action: {action}")
        if PHASES.index(target) != PHASES.index(phase) + 1:
            raise WorkflowStateError(f"invalid transition {phase} -> {target}")
        value["phase"] = target
    value.setdefault("transitions", []).append({"action": action, "artifacts": artifacts})
    _write(state_path, value)
    return value
