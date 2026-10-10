"""Personal publishing preferences stored outside the Skill (like the glossary).

Location: KVC_PUBLISH_PROFILE, else publish-profile.json in the profile folder (kvc.hostenv.profile_dir()).
A missing file means Skill defaults: new caption style on, compact edit and intro promo off.
"""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path

DEFAULTS: dict = {
    "schema_version": 1,
    "caption_style": {
        "preset": "white-box",
        "font_ratio": 0.075,
        "margin_ratio_landscape": 0.15,
        "margin_ratio_portrait": 0.22,
        "side_ratio": 0.12,
        "max_line_units": 16,
        "max_lines": 2,
        "reserved_zones": [],
    },
    "compact_edit": {
        "enabled": False,
        "talk_speed": 1.1,
        "trim_pauses": True,
        "auto_approve_after_codex_review": False,
    },
    "intro_promo": {
        "enabled": False,
        "target_seconds": 32,
        "look_lock_project": "",
        "deliver_shorts": True,
        "deliver_standalone_16x9": True,
    },
    "youtube": {"chapters": True, "intro_chapter_label": "미리보기"},
}


class PublishProfileError(ValueError):
    pass


def profile_path() -> Path:
    value = os.environ.get("KVC_PUBLISH_PROFILE")
    if value:
        return Path(value)
    from .hostenv import profile_dir
    return profile_dir() / "publish-profile.json"


def _merge(base: dict, extra: dict) -> dict:
    out = copy.deepcopy(base)
    for key, value in extra.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


def load_publish_profile(path: Path | None = None) -> dict:
    path = Path(path) if path else profile_path()
    if not path.is_file():
        result = copy.deepcopy(DEFAULTS)
        result["_source"] = "skill-defaults"
        return result
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception as exc:
        raise PublishProfileError(f"invalid publish profile: {path}") from exc
    if not isinstance(data, dict) or data.get("schema_version") != 1:
        raise PublishProfileError("publish profile schema_version must be 1")
    result = _merge(DEFAULTS, data)
    result["_source"] = str(path)
    return result
