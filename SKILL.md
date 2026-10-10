---
name: korean-video-captioner
description: Use when a user wants natural Korean subtitles generated, corrected, or burned into a local video; a finished lecture video compacted (fast-forwarded silent work, trimmed pauses, 1.1x speech) with a promo intro; or a source-grounded YouTube publishing package with chapters and an AI thumbnail using explicit private book and character reference images.
---
# Korean Video Captioner

Choose the narrowest applicable mode and preserve every source and prior output.

Skill maintenance requests update the skill only; they never resume a stopped video job. Explicit user constraints override mode defaults and the publish profile, and persist when a run is resumed:

- "웹캠 부재 전처리 제외" disables webcam-absence preprocessing.
- "컷/속도 변경 없음" disables compact editing and pause/filler cuts.
- "인트로 없이" disables the promo intro.
- "자막만" means caption mode only.

## Setup on this computer

Before the first job on a computer (and after a Skill update), run `scripts/setup.py doctor` with any Python 3.8+ and carry out its `next_actions` yourself: `install`, then `selftest`. Read `references/setup.md`. Ask the user only for steps marked `who: user` (Homebrew's Mac password, disk space, macOS folder permission). Start long jobs with `scripts/run_background.py`, which lowers priority and keeps a Mac awake. On Apple Silicon, transcription uses the GPU engine only after `selftest` validated it on that Mac (`--engine auto`).

## Personal profile

Two files outside the Skill hold one user's preferences, so they never ship with it:

- Glossary: `KVC_GLOSSARY` or `glossary.json` in the profile folder that `setup.py doctor` prints (see `references/korean-caption-policy.md`).
- Publish profile: `KVC_PUBLISH_PROFILE` or `publish-profile.json` in the same folder, loaded by `scripts/kvc/publish_profile.py`. It sets the caption look and reserved zones, whether compact editing and the promo intro run by default, whether Codex may approve its own compact-edit review, the look-lock project for intros, and YouTube chapter settings. A missing file means Skill defaults: new caption style on, compact editing and intro off.

When the user states a lasting preference ("앞으로 자막은 …", "다음부터 인트로는 …"), update the profile. Do not change Skill defaults for one person's taste.

## Caption mode

Read `references/korean-caption-policy.md`, `references/asr-operations.md`, `references/caption-style.md`, and `references/output-contract.md`. Use only the runtime Python and `scripts/transcribe_faster_whisper.py` for Whisper `large-v3`, Korean, VAD, and word timestamps (Faster-Whisper CPU int8, or the selftest-validated MLX GPU engine on Apple Silicon). The runtime folder comes from `kvc.hostenv` (`KVC_RUNTIME_ROOT` overrides it). Never use VideoCaptioner with `--asr whisper-cpp`, never ask the user to install WhisperCpp, and never use VideoCaptioner's built-in LLM optimizer.

Transcription is chunked (5-minute chunks, 2-second overlap) and resumable. Start it as a background process, then report progress only from `asr-progress.json` (`percent`, `chunks_done`/`chunks_total`, `updated_at`). Never estimate completion from elapsed time. If a run stops, rerun the same command on the same run directory; finished chunks in `asr-parts/` are reused. Never start a second transcription while `asr.lock` belongs to a live process, and never kill or restart one without the user's request.

The current Codex makes minimal meaning-preserving corrections; every proposal passes the deterministic correction validator. Apply the glossary's canonical spellings to greetings, channel names, and product terms. When the user corrects a recurring term, add it to the glossary so later videos need no repeat fix. After the whole video is corrected, reread the full caption text once in order and fix words that are spelled correctly but wrong in context (misheard product names, homophones), still through the validator.

Burn captions only with `scripts/render_captions.py` (or `kvc.render.render_captions`): one rounded white card per caption with near-black text in the Skill-bundled unmodified Noto Sans KR Bold (SIL OFL 1.1), sized and placed in real video pixels, at most two lines, no decorative effects. Check `caption_preview.py` before a long render and pass `verify_caption_layout.py` after it. Verify cue IDs/times, streams, duration, resolution, frames, source size, mtime, and SHA-256 before reporting completion. Do not report success while `quality-report.json` is `NEEDS_REVIEW` or the layout gate fails; show the reviewed cues instead.

## Tip-card mode

When controlled paired markers are present, also read `references/tip-card-policy.md`. Hide only marker text from bottom captions, preserve cue IDs/times and remaining speech, validate source-linked 1–5 item proposals, and render the upper-left card separately (pass it to `render_captions.py --tips`).

## Natural pause editing

When the user asks to tighten pauses, remove 어/음 fillers, or clean up dead air on the original timeline, or has enabled this preference earlier, read `references/pause-editing.md` and use `scripts/pause_edit.py` after correction and before caption rendering. The current Codex reviews every filler candidate. Render the full edit only after the user approves the before/after previews for that plan, then burn captions and tip cards onto `edited.mp4` with the remapped subtitle files. Do not combine it with compact editing unless the user asks for both.

## Compact editing and promo intro

After captions are verified, the publish profile (or a user request) can shorten the finished video and open it with a promo:

- Compact editing: read `references/compact-edit.md`. `scripts/compact_edit.py` detects long silent screen work (4x/8x/16x with a badge), trims pauses, and plays speech at 1.1x, protecting words and caption reading time. Codex reviews the fast-forward contact sheets for personal information before building.
- Promo intro: read `references/intro-promo.md`. Make the Shorts, a standalone 16:9 promo, and a 16:9 intro (title card instead of the CTA) with `$opus-promo-director` from the profile's look-lock project, then join with `scripts/intro_join.py` without re-encoding the main video.

Both write timelines, so remapped subtitles and YouTube chapter times stay exact. Keep the uncompacted captioned video.

## YouTube publishing-package mode

When the user requests a thumbnail, title, description, hashtags, chapters, or portable book/character reuse, read `references/youtube-package-policy.md`, `references/brand-pack-policy.md`, and `references/font-licenses.md`.

- Personal book and character images live in a private brand-pack ZIP, not the public Skill.
- Install a pack with `scripts/install_brand_pack.py`; validate relative paths, transparent alpha, checksums, and private distribution scope.
- For an already completed run, execute `scripts/run_youtube_package.py prepare --final-video FINAL`, have the current Codex write one source-linked proposal (with chapters when enabled), then execute `finalize`.
- If the user says the video is already complete, do not launch ASR, correction, clipping, or video rendering. Read only the supplied final video and `corrected.srt` as evidence.
- Never invent claims, numbers, names, identifiers, or URLs; never redraw supplied brand assets. A rejected proposal produces review data but no promoted metadata or thumbnail.

Every operation uses a new timestamped directory. Never overwrite source videos, SRT files, existing attempts, installed brand-pack versions, or prior final outputs.

## Webcam-absence preprocessing

This stage is off by default and runs only when the user asks to speed up or cut webcam-absent sections (`run_full_publish.py init --webcam-preprocess`). When requested, read `references/webcam-absence-policy.md` and run the preprocessor before ASR. It calibrates a normalized lower-right ROI, requires a continuous face absence of at least 180 seconds, and combines face presence, FFmpeg silence evidence, and non-webcam screen activity. Face absence alone never authorizes a cut: speech keeps 1x, active silent screen work uses 5x, and only silent low-activity intervals become cut proposals. Cut proposals require current-Codex contact-sheet review and may only be downgraded. Use `local-only` when frames must not enter the active Codex service; in that mode cuts are downgraded to 5x. A video shorter than 180 seconds or a failed calibration is a verified no-op using the original as `effective_input`.

## One-shot full-publish mode

When the user explicitly invokes `$korean-video-captioner` with a video or completed run and does not say "자막만" or another narrower mode, use `full-publish`: captions, then the post stages the profile enables (compact edit, promo intro, intro join), then the YouTube package. The current Codex performs every internal caption, correction, editing, promo, publishing, image-generation, candidate-review, retry, finalization, and verification action without asking the user to run intermediate commands or write JSON. Read `references/full-publish-workflow.md` and persist `workflow-state.json` after every transition. Run heavy steps one at a time at below-normal priority after checking free memory, and never stop or kill the user's other programs without asking.

After the final video and source-grounded metadata proposal are validated, use the built-in Codex `image_gen` tool by default. Pass the private brand-pack book image first and the transparent character image second, plus a video scene frame third only when the user asks for that visual (`references/ai-thumbnail-policy.md`). Generate `book-led`, `character-led`, and `balanced` candidates, inspect every candidate with `view_image`, and retry only the targeted failed candidate up to the documented limit. Do not use an image API key or CLI fallback unless the user explicitly requests it.

If the input is already a verified completed run, skip ASR, correction, tip rendering, and caption rendering. If built-in image generation is unavailable, preserve the completed work and report the blocker; do not silently substitute a deterministic thumbnail in an explicitly requested AI mode. The deterministic thumbnail remains available when explicitly selected.
