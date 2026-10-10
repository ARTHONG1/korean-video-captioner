"""Stable visual constants shared by caption and tip-card renderers.

Caption look and size live in caption_style.py. caption_margin_v() only resolves an explicit height override,
measured in pixels of a 1080-high frame and scaled to the actual video height.
"""

import os

BOTTOM_CAPTION_MARGIN_V = None  # None = use the caption_style ratio (15% of height for landscape)
MIN_CAPTION_MARGIN_V = 20
MAX_CAPTION_MARGIN_V = 400
TIP_X = 60
TIP_Y = 80
TIP_ALIGNMENT = 7


def caption_margin_v(requested: int | str | None = None) -> int | None:
    """Explicit caption height (px at 1080p): argument, then KVC_CAPTION_MARGIN_V, else None (style default)."""
    value = requested if requested is not None else os.environ.get("KVC_CAPTION_MARGIN_V")
    if value in (None, ""):
        return BOTTOM_CAPTION_MARGIN_V
    margin = int(value)
    if not MIN_CAPTION_MARGIN_V <= margin <= MAX_CAPTION_MARGIN_V:
        raise ValueError(f"caption MarginV must be {MIN_CAPTION_MARGIN_V}-{MAX_CAPTION_MARGIN_V}, got {margin}")
    return margin
