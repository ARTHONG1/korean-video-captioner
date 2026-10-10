# Output contract

Each caption run is `source-stem-captioned/run-YYYYMMDD-HHMMSS`. Existing outputs and sources are never overwritten.

Base caption artifacts are `manifest.json`, `raw.srt`, `batches/`, `proposals/`, `corrected.srt`, `review.json`, `preview.mp4`, `verify.json`, and `final-captioned.mp4`.

Every burned caption render writes `OUTPUT.captions.ass` (styled captions in video pixels), `OUTPUT.caption-layout.json`, and `OUTPUT.render-command.txt` next to the output; the layout gate writes `caption-layout-verify.json`.

Compact editing writes `run/compact/attempt-YYYYMMDD-HHMMSS/` with `settings.json`, `speed-plan.json`, `review/`, `timeline.json`, `chunks.json`, `compact.mp4`, `compact.timeline.json`, `publication-compact.srt`, and `compact-verify.json` (`compact-audio.wav` until the intro join passes). An intro join writes `final-with-intro-compact.mp4` with `.timeline.json`, `.publication.srt`, and `.join-verify.json` companions in the run.

Transcription also writes `words.json`, `asr-profile.json`, `asr-progress.json`, and `asr-parts/chunk-NNNN.json`; `asr.lock` exists only while a transcription is running. Correction writes `correction-audit.json` and `quality-report.json`.

Pause editing writes `run/pause-edit/attempt-YYYYMMDD-HHMMSS/` with `analysis.json`, `filler-candidates.json`, `pause-plan.json`, `cut-list.txt`, `previews/`, `pause-progress.json`, `pause-verify.json`, `timeline-map.json`, `edited.mp4`, and `remapped/`. Large intermediates (`source.wav`, `frames.gray`, `render-parts/`) are deleted after a verified render.

Marker-enabled runs additionally contain `markers.json`, `caption-without-markers.srt`, `tip-source-batches/`, `tip-proposals/`, `tips.json`, `tip-review.json`, `tips.ass`, `preview-tip.mp4`, `tip-frames/`, `verify-tip.json`, and `final-captioned-tips.mp4`.

An optional YouTube attempt is `run/youtube/attempt-YYYYMMDD-HHMMSS` and contains `metadata-source.json`, `metadata-proposal.json`, `metadata.json`, `youtube-review.json`, `title.txt`, `alternative-titles.txt`, `description.md`, `hashtags.txt`, `thumbnail.png`, and `verify-youtube.json`. Rejected proposals retain source, proposal, review, and failed verification only.

An AI reference-thumbnail attempt additionally contains `workflow-state.json`, `thumbnail-brief.json`, `thumbnail-generation-request.json`, `thumbnail-candidates/`, `thumbnail-candidates.json`, `thumbnail-review.json`, and `verify-thumbnail.json`. The current Codex generates and reviews candidates automatically; users do not run intermediate commands.

A private brand pack contains `brand-pack.json`, `profile/youtube-profile.json`, `assets/book-*.png`, `assets/character-*.png`, `legal/ASSET-RIGHTS.md`, `README.md`, and `checksums.sha256`. It contains no executable, secret, source video, transcript, model, or absolute user path.
