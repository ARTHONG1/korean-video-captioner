from __future__ import annotations
import hashlib, json, os
from pathlib import Path

PHASES = ["initialized", "primary_asr_ready", "context_ready", "editor_ready", "critic_ready", "ambiguity_resolved", "corrected_ready", "publication_ready", "caption_rendered", "caption_verified"]

def _fingerprint(path: Path) -> dict:
    data = path.read_bytes()
    return {"path": str(path), "size": len(data), "sha256": hashlib.sha256(data).hexdigest()}

def _write(path: Path, value: dict) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)

def initialize_caption_workflow(input_path: Path, run: Path) -> Path:
    run.mkdir(parents=True, exist_ok=True)
    state = run / "caption-workflow-state.json"
    _write(state, {"schema_version": 1, "input": str(input_path), "phase": "initialized", "warnings": 0, "artifacts": {}})
    return state

def record_caption_transition(state_path: Path, action: str, artifacts: dict[str, Path]) -> dict:
    state = json.loads(state_path.read_text(encoding="utf-8"))
    if action not in PHASES or PHASES.index(action) < PHASES.index(state["phase"]):
        raise ValueError("invalid phase transition")
    state["phase"] = action
    for name, path in artifacts.items():
        if not path.exists() or not path.is_file():
            raise FileNotFoundError(path)
        state["artifacts"][name] = _fingerprint(path)
    _write(state_path, state)
    return state

def next_caption_action(state_path: Path) -> dict:
    state = json.loads(state_path.read_text(encoding="utf-8"))
    phase = state["phase"]
    actions = {
        "initialized": ("local_action", "primary_asr"),
        "primary_asr_ready": ("local_action", "build_transcript_context"),
        "context_ready": ("codex_semantic_action", "edit_caption_batch"),
        "editor_ready": ("codex_semantic_action", "criticize_caption_batch"),
        "critic_ready": ("local_action", "retry_caption_asr"),
        "ambiguity_resolved": ("local_action", "build_corrected"),
        "corrected_ready": ("local_action", "build_publication"),
        "publication_ready": ("local_action", "render_caption"),
        "caption_rendered": ("local_action", "verify_caption"),
        "caption_verified": ("done", "verified"),
    }
    kind, name = actions[phase]
    return {"action": kind, "name": name, "phase": phase}
