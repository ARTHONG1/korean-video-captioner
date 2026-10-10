# Promo intro

The finished compact video can open with a short promo that doubles as the Shorts video. Run it when the publish profile enables `intro_promo` or the user asks for an intro or promo. "인트로 없이" disables it for that video.

## Make the promo

Use `$opus-promo-director` for the creative work. Start from `intro_promo.look_lock_project` in the profile (the last approved Remotion project) and its look-lock document so music, type, and transitions stay the same unless the user asks for a new look. All on-screen claims come from this video's corrected captions; do not show faces the user excluded, and credit third-party projects shown on screen.

Render three files from one shot plan whose length is `intro_promo.target_seconds` (default 32 s, the Shorts length):

| File | Size | Last scene |
| --- | --- | --- |
| Shorts | 1080×1920 | CTA ("풀영상은 채널에서") |
| Standalone promo | 1920×1080 | the same CTA |
| Intro | 1920×1080 | a title card with the video's headline (the CTA is replaced, because the full video follows) |

Rendering on a Mac or any new computer: install Node with Homebrew (`brew install node`) when it is missing, and let Remotion use the browser it downloads itself; never hard-code a Chrome path. The profile's `look_lock_project` is a path on one computer; when it does not exist here, start a new project from `$opus-promo-director`'s kit and the look-lock document instead.

Check stills of the 16:9 renders for clipped or overlapping text before the full render; vertical layouts do not always fit 16:9.

## Join

```text
scripts/intro_join.py --intro INTRO.mp4 --main A/compact.mp4 --main-audio A/compact-audio.wav --srt A/publication-compact.srt --out RUN/final-with-intro-compact.mp4
```

Without compact editing, pass `final-captioned.mp4` as `--main` and `publication.srt` as `--srt`. The intro is conformed to the main video's size, frame rate, color, and encoder settings and faded out over the last 0.45 s, so the main video is joined by stream copy. If the parameter sets still differ the script re-encodes the join and says so. It writes `OUT.timeline.json` (used for YouTube chapters), `OUT.publication.srt`, and `OUT.join-verify.json`. The report includes the mean loudness of the intro and of the first minute of speech; a gap over 10 dB is flagged. Codex cannot hear audio, so ask the user to listen at the joint (about `intro_seconds`).

Delete `compact-audio.wav` after a passing join. Keep earlier intros and finals; a new intro length means a new output name.
