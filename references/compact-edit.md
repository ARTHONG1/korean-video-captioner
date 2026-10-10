# Compact edit

Compact editing shortens a finished captioned lecture so it does not drag: long stretches where the screen works silently are fast-forwarded with a "▶▶ N배속" badge, pauses are trimmed, and speech plays at 1.1x with its pitch kept. It runs on `final-captioned.mp4` (or `final-captioned-tips.mp4`) after caption verification, so captions and tip cards are already burned in and move with the picture.

Run it when the publish profile enables `compact_edit` or the user asks to speed up silent parts or shorten the video. "컷/속도 변경 없음" or a request to keep the original pace disables it for that video. Do not combine it with natural pause editing (`pause-editing.md`) unless the user asks for both.

## Commands

```text
scripts/compact_edit.py detect  --video RUN/final-captioned.mp4 --run RUN [--srt RUN/publication.srt] [--words RUN/words.json]
scripts/compact_edit.py approve --attempt A [--blur START,END,X,Y,W,H]... [--drop I]... [--set I=SPEED]... --note "..."
scripts/compact_edit.py build   --attempt A
scripts/compact_edit.py map     --timeline A/compact.timeline.json --times 95,760
```

Start long steps (`detect` on a long video, `build`) as background processes at below-normal priority and check free memory first; each step logs to stdout and can be rerun.

## What detect proposes

A fast-forward segment needs 20 s or more with no word and no caption (0.4 s margin on both sides) and at least 80% silent audio (-40 dB). Speed: 4x under 1 min, 8x under 5 min, 16x from 5 min. Segments whose audio is not silent are listed as `audio_not_silent` and left alone. `review/segment-NN.jpg` shows eight frames per segment.

## Review before build

The current Codex opens every `review/segment-NN.jpg` with `view_image` and checks for personal information (faces of other people, messages, account details, addresses) and for screens the viewer must read at normal speed. Blur a region with `--blur` in source seconds and source pixels, drop a segment with `--drop`, or change a speed with `--set`. When the profile sets `auto_approve_after_codex_review`, approve after this review without asking the user; otherwise show the sheets and the plan to the user first. `build` refuses an unreviewed plan.

## What build guarantees

- Pauses: inside normal parts, silences keep 0.2 s at each side; 0.6–3.6 s left over is cut, longer is played at 4x. Every word (±0.08 s) and each caption's reading time (10 characters per second, at least 1.2 s) are protected.
- Speech at 1.1x drops 1 frame in 11 and time-stretches the audio of each speech piece to exactly its video length, so sync cannot drift.
- Video is encoded in chunks with the shared encoder settings (`kvc/media_tools.X264`) and joined without re-encoding.
- `compact-verify.json` passes only with the planned frame count, matching video/audio length, no decode error at chunk joins, an unchanged source, and speech sync within 25 ms on sampled pieces.

Outputs in the attempt: `compact.mp4`, `compact-audio.wav` (kept for the intro join, delete after it), `compact.timeline.json`, `publication-compact.srt`, `compact-verify.json`. Intermediate chunks and WAVs are deleted after each verified step.

Report the source and compact lengths, each fast-forward segment with its speed, pause totals from `summary`, privacy actions, and the verification. Codex cannot hear audio: ask the user to listen to one 1.1x part and one trimmed pause.
