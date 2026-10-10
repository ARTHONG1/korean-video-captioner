# Natural pause and filler editing

Pause editing shortens long silences and removes reviewed fillers so a lecture flows better. Every accepted cut must be inaudible: silence is shortened, never removed completely, and anything uncertain is left alone. Video speed never changes.

## When to run

Run it when the user asks to tighten pauses, remove fillers, or turn on "공백 정리", including a previously enabled preference. Explicit instructions to preserve cuts or speed take priority. Within this mode, filler analysis starts enabled; removals still require the contextual review below. It runs after transcription and correction and before caption/tip rendering, on the original video. Never transcribe the edited video again; words and subtitles are remapped through `timeline-map.json`.

## Commands

```text
scripts/pause_edit.py analyze --video VIDEO --run RUN
scripts/pause_edit.py plan    --attempt RUN/pause-edit/attempt-* --filler-review REVIEW.json [--strength normal|gentle]
scripts/pause_edit.py preview --attempt ATTEMPT [--count 3] [--length 60]
scripts/pause_edit.py render  --attempt ATTEMPT
```

`analyze` needs `RUN/words.json` and `RUN/corrected.srt`. Each run creates a new attempt directory; earlier attempts are kept.

## Filler review

`analyze` writes `filler-candidates.json` (isolated 어/음/으 and immediate repeats such as "이게, 이게", each with six words of context) and `filler-review.template.json`. The current Codex reads each candidate with its context and writes the review:

```json
{"schema_version": 1, "items": [{"id": "f-0001", "word_ids": ["w-000123"], "decision": "remove", "reason": "문장 앞 망설임, 의미 없음"}]}
```

Mark `remove` only when the filler carries no meaning. Keep it (`decision: "keep"`) when it is an answer or agreement (아, 네), part of a word, an emphasis, or when the context is unclear. Connectives such as 그러니까, 그래서, 이제 are never candidates. `--no-fillers` plans pauses only; filler removal never runs without a review file.

## What the plan guarantees

| Gap | Cut when longer than | Pause kept |
| --- | --- | --- |
| within a sentence | 0.8 s (gentle 1.2 s) | 0.35 s (0.5 s) |
| between cues | 1.0 s (1.5 s) | 0.6 s (0.8 s) |
| topic change, 3 s+ gap, or next to a 꿀팁 marker | 1.5 s (2.0 s) | 1.0 s (1.2 s) |

A cut is dropped and recorded in `skipped` with a reason when:

- audio inside the cut or at either edge is above the room-tone threshold (`no_quiet_audio`, `edges_not_quiet`)
- it comes within 50 ms of a kept word (`touches_word`)
- the screen changes during the pause (typing, scrolling, loading) or differs across the joint (`screen_activity`, `screen_jump`)
- the webcam area changes across the joint by more than 12% (`webcam_jump`)
- the kept piece between cuts would be under 1.2 s, or more than 3 cuts would fall in 10 s (`piece_too_short`, `density_limit`)
- it is within 1 s of the start or end of the video (`edge_guard`)

Cuts are frame-aligned and snapped to the quietest audio point nearby. The whole plan is blocked when total reduction would exceed 15% (`LIMIT_EXCEEDED`) or when speech is not at least 18 dB louder than room tone (`NOT_SEPARABLE`). Report these statuses; do not loosen thresholds without the user's request. A saved plan is re-validated independently before rendering (`INVALID` blocks it).

## Preview and approval

`preview` renders before/after pairs around the densest cuts and `preview-notes.md` listing each cut in the after clip. Codex cannot hear audio, so send the preview paths and the cut list to the user and render only after they approve that exact plan. `render` refuses a plan whose previews were not generated from the current `pause-plan.json`. `--skip-preview` is for tests only.

## Render and verification

Audio is rebuilt sample-exact with a 24 ms equal-power crossfade at each joint, inside the silence, and padded at the end when the source audio is shorter than the video. Video is re-encoded in 5-minute segments (x264 CRF 16) and joined without re-encoding. `edited.mp4` is promoted only when `pause-verify.json` passes all checks: exact frame count, duration, audio length, quiet audio at every joint in the rendered file, per-piece loudness match with the source (drift), sampled joint frames identical to the source frames, and unchanged source fingerprint. A failure keeps `edited.partial.mp4` for inspection and reports the failed check.

After a pass, `remapped/` holds `corrected.srt`, `caption-without-markers.srt`, `publication.srt`, `tips.ass`, and `words.json` on the edited timeline. Removed fillers are deleted from caption text only when they appear as whole words; otherwise the cue text is left unchanged and listed in `remap-report.json`. Burn captions and tip cards onto `edited.mp4` using the remapped files, then run the normal caption verification.

## Reporting

Report cuts by kind, seconds removed and percentage, the main skip reasons, preview paths, and the verification result. To restore one cut, remove it from `pause-plan.json` in a new attempt, then preview and render again.
