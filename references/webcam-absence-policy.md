# Webcam-Absence Policy

The webcam stage is an optional pre-ASR edit. It never identifies a person and never stores face crops or embeddings.

Defaults:

- search ROI: normalized `(0.72, 0.58, 0.28, 0.42)`
- minimum absence: 180 seconds
- coarse sampling: 1 fps
- boundary refinement: 5 fps within ±15 seconds
- keep padding: 5 seconds on each side
- silence: FFmpeg `silencedetect=noise=-40dB:d=1.0`
- speed audio: chained `atempo=2,atempo=2,atempo=1.25`

The detector calibrates a padded stable ROI from at least ten confident early detections. If calibration is uncertain, use a verified no-op. Merge face-presence islands of at most 10 seconds inside an absence and remove absence islands of at most 15 seconds inside presence before applying the 180-second threshold.

Decision order:

1. Any non-silent audio or uncertain audio → `KEEP`.
2. At least 98% silence with meaningful screen activity → `SPEED_5X`.
3. At least 98% silence and at least 95% low-activity windows → `CUT_PROPOSED`.
4. Missing/conflicting evidence → `KEEP`.

The current Codex reviews boundary-before, boundary-after, and twelve interior frames for every cut proposal. It can accept the proposed cut or downgrade it to 5x/keep, but it cannot create or widen a cut. Missing or invalid review is never a cut approval.

Default review mode uses local contact sheets as input to the active Codex review action. `local-only` sends no contact sheet to Codex and downgrades every cut proposal to 5x. Public Skill packages must exclude user videos, frames, contact sheets, run outputs, private brand assets, model caches, and personal paths.

Every run writes `webcam-analysis.json`, `webcam-candidates.json`, `webcam-review.json`, `timeline-map.json`, `effective-input.json`, `absence-workflow-state.json`, and `preprocess-verify.json` under a new `preprocess/` directory. Existing files and source fingerprints must remain unchanged.
