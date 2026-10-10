# Caption style

Every burned-in caption uses `scripts/kvc/caption_style.py` through `scripts/render_captions.py` (or `kvc.render.render_captions`). Do not pass `force_style` to the `subtitles` filter: without an ASS header libass lays text out on a 384×288 grid, so a MarginV of 80 lands about 300 px above the bottom of a 1080p frame and the font size ignores the video resolution. The renderer writes an ASS file whose PlayResX/Y equal the video size, so every number below is in real video pixels.

## Default look (`white-box`)

| Item | Value | Why |
| --- | --- | --- |
| Card | one rounded white card per caption, sized to the measured text, with a hairline grey edge and a soft shadow | a solid card reads on any background; one card for two lines looks clean; the edge keeps it visible on white pages |
| Text | near-black, unmodified Noto Sans KR Bold (`font-licenses.md`) | real bold strokes; OFL, no copyright risk |
| Size | 7.5% of the short side (81 px at 1080p) | BBC: about 1/15 of the screen height as a minimum; tutorials are often watched on phones |
| Position | bottom centre, text bottom 15% above the frame bottom (162 px at 1080p); 20% for vertical video | low enough to stay out of the content, above taskbars and player controls |
| Lines | at most 2 lines of 16 units (Hangul 1, Latin/digits/spaces/punctuation 0.5) | Netflix Korean timed-text guide |
| Speed | events over 14 units per second are reported as `fast_events` | Netflix Korean: 12 adult, 14 SDH |

The card is an ASS vector drawing (layer 0) under the text (layer 1). Its size comes from measuring how libass draws the caption font at this size (`kvc.render.measure_layout`), so it fits Korean, English, and numbers. Long cues are split into several events at balanced points, preferring a break after punctuation and never ending a line on a modifier such as 이런, 그, 어떤, 너무. With `words.json` the split time snaps to a real word gap. Caption text is never rewritten by this step.

Other presets: `dark-box` (white text on an 80% black card) and `outline` (white text with a black outline, no card). Use them only when the user asks. Captions stay plain: no per-word colours, emoji, sound-effect text, or animation.

## Personal preferences

`caption_style` in the publish profile (see SKILL.md) overrides the defaults: `preset`, `font_ratio`, `margin_ratio_landscape`, `margin_ratio_portrait`, `max_line_units`, `max_lines`, and `reserved_zones`. A reserved zone is a normalized rectangle `[x0, y0, x1, y1]` that captions must never touch, for example a lower-right avatar or webcam. A one-off height request uses `--margin-v PX` (pixels of a 1080-high frame, 20–400) or `KVC_CAPTION_MARGIN_V`. If the user changes the look for good, update the profile instead of the Skill defaults.

## Checks before a full render

1. `scripts/caption_preview.py --video V --srt S --out sheet.jpg` burns the style into real frames (spread cues plus the widest cue). Look at it with `view_image`; add `--times` for frames with white pages, dark editors, faces, or the avatar.
2. After rendering, `scripts/verify_caption_layout.py --ass OUT.captions.ass --out caption-layout-verify.json` renders the widest and random events alone and fails on a card outside the safe area, more than the planned lines, an unexpected height, text overflowing its card, or contact with a reserved zone. Fix the cause and render again; do not report a FAIL as done.

## Sources

- BBC Subtitle Guidelines: https://bbc.github.io/subtitle-guidelines/ and the size study https://bbc.github.io/gaad/how_big_should_subtitles_be/index.html
- Netflix Korean Timed Text Style Guide: https://partnerhelp.netflixstudios.com/hc/en-us/articles/216001127-Korean-Timed-Text-Style-Guide
- YouTube caption appearance settings (viewer-side box and opacity options): https://support.google.com/youtube/answer/100078
- ASS drawing commands: https://aegisub.org/docs/latest/ass_tags/
