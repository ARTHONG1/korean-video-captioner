from .caption_state import next_caption_action

def action_for_phase(phase: str) -> dict:
    actions = {
        "context_ready": {"action": "codex_semantic_action", "name": "edit_caption_batch"},
        "editor_ready": {"action": "codex_semantic_action", "name": "criticize_caption_batch"},
        "ambiguity_resolved": {"action": "local_action", "name": "build_corrected"},
    }
    if phase not in actions:
        raise ValueError(f"unsupported phase: {phase}")
    return actions[phase]
