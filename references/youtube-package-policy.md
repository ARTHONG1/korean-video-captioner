# YouTube package policy

This is an optional publishing-only stage. It never substitutes for caption verification and never reruns caption work when a completed run is supplied.

## Evidence and proposal

`prepare` records every corrected cue, accepted tip item, approved profile fact, input hash, and brand-asset hash. The current Codex writes `metadata-proposal.json` with one recommended title, exactly two alternatives, one or two thumbnail lines, an intro, one to five highlights, and three to ten hashtags. Every semantic field cites real cue IDs.

## Chapters

`prepare --final-video FINAL` stores each cue's time in the final video (`out_start_ms`) using `FINAL.timeline.json` from compact editing or the intro join. A proposal may add `chapters`: a list of `{"title": "...", "source_cue_ids": [...]}` in viewing order; the first cue ID sets the chapter time. Titles follow the same evidence rules as other fields and are at most 40 characters. With an intro, a `0:00` chapter named by `youtube.intro_chapter_label` is added automatically; without one, the first chapter is pinned to `0:00`. The validator rejects fewer than three chapters, chapters closer than 10 s, and duplicate titles. `description.md` gets a `## 챕터` list with the computed times; never type chapter times by hand.

## Deterministic gates

Reject review decisions, missing or foreign cue IDs, unsupported numbers/URLs/English identifiers, duplicate titles/highlights/hashtags, titles over 70 characters, thumbnail lines over 16 visible characters, or text that cannot fit at 56px. Do not automatically rewrite a rejected proposal. Store structured `code`, `field`, `value`, and `source_cue_ids` records in `youtube-review.json`.

## Thumbnail

Compose an exact 1280×720 RGB PNG with the validated book image, validated transparent character, and Skill-bundled Noto Sans KR. Preserve source hashes. Do not redraw assets, remove attribution embedded in the book art, use the character’s original box, or overwrite an existing image.

Only `finalize` may promote copy-ready files and `thumbnail.png`, and only when `verify-youtube.json` is `PASS`.
