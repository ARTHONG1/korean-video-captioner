from __future__ import annotations

import json
from pathlib import Path

from .full_publish_state import next_action


def run_until_tool_action(workflow: Path) -> dict:
    action = next_action(Path(workflow))
    if action.get("name") == "caption_pipeline":
        run = Path(workflow).parent
        subtitle = run / "publication.srt"
        if subtitle.is_file() and subtitle.stat().st_size:
            return {"action": "caption_pipeline", "name": "caption_pipeline", "subtitle": str(subtitle)}
    if action.get("action") != "invoke_imagegen":
        return action
    request_path = Path(workflow).parent / "thumbnail-generation-request.json"
    if not request_path.is_file():
        return {"action": "blocked", "reason": "thumbnail-generation-request.json is missing"}
    request = json.loads(request_path.read_text(encoding="utf-8"))
    references = request.get("references", [])
    variants = {item.get("id"): item for item in request.get("variants", [])}
    variant = action["variant"]
    roles = [item.get("role") for item in references]
    if roles not in (["book", "character"], ["book", "character", "scene"]):
        return {"action": "blocked", "reason": "book and character references (optionally followed by one scene) are required"}
    if variant not in variants:
        return {"action": "blocked", "reason": f"missing prompt for variant: {variant}"}
    return {
        "action": "invoke_imagegen",
        "variant": variant,
        "prompt": variants[variant]["prompt"],
        "referenced_image_paths": [item["path"] for item in references],
        "save_under": str(Path(workflow).parent / "thumbnail-candidates"),
    }
