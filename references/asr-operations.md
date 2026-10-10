# ASR operations

`scripts/transcribe_faster_whisper.py VIDEO RUN/raw.srt [--profile auto|quality|balanced]` is the only transcription entry point. `transcribe_chunked.py` forwards to it.

## Engines

`--engine auto` (default) reads `runtime/engine.json`, written by `setup.py selftest`. It picks `mlx` (mlx-whisper on the Apple Silicon GPU, float16) only when the selftest validated it on that Mac, otherwise `faster-whisper` (CPU, int8), the reference engine on every platform. Both produce the same chunk files, `words.json`, and progress fields; the engine name is recorded in `asr-progress.json` and `asr-profile.json`, and chunks from a different engine are not reused. MLX has no beam search, so it decodes greedily with temperature fallback, and segments outside Silero VAD speech are dropped to match Faster-Whisper's `vad_filter`. Force an engine with `--engine faster-whisper|mlx`; caption retries follow `KVC_ASR_ENGINE`.

Start transcription with `scripts/run_background.py --log RUN/asr.log -- <runtime python> scripts/transcribe_faster_whisper.py VIDEO RUN/raw.srt`.

## Chunks and resume

Audio is split into 5-minute chunks with 2-second overlap. Each finished chunk is saved to `RUN/asr-parts/chunk-NNNN.json` with a key made of the source path, size, mtime, profile, and decoding parameters. A rerun on the same run directory reuses every chunk whose key still matches and transcribes only the rest. A changed source or profile invalidates the saved chunk. `raw.srt`, `words.json`, and `asr-profile.json` are written only after every chunk exists. Overlap duplicates are removed by segment midpoint, so cue text is never merged by string matching.

## Progress

`RUN/asr-progress.json` is rewritten at least every 10 seconds while a chunk decodes and after every chunk:

- `state`: `running`, `done`, or `failed` (with `error`)
- `percent`, `processed_ms`, `duration_ms`
- `chunks_done`, `chunks_total`, `chunks_reused`, `current_chunk`
- `profile`, `cpu_threads`, `memory_available_bytes`, `updated_at`

Report these numbers when the user asks for status. If `updated_at` stops advancing for more than 10 minutes while the process is alive, report a stall with the numbers instead of guessing.

## Memory and profiles

Before loading the model the runner checks free physical memory.

| Free memory | Result |
| --- | --- |
| under 1.5 GB | refuses to start (`ASR_BLOCKED`, exit 3); ask the user to close other apps |
| 1.5–5 GB | `auto` selects `balanced` (beam 3, best_of 3, 2 temperatures) and at most 4 CPU threads |
| 5 GB or more | `auto` selects `quality` (beam 5, best_of 5, 3 temperatures) and at most 8 CPU threads |

An explicit `--profile quality` overrides the memory choice. Record the selected profile in the final report.

## One transcription per run

`RUN/asr.lock` holds the owning PID. A second start on the same run exits with `ASR_BLOCKED` while that process is alive. A lock left by a dead process is replaced automatically.

## Targeted retry

`scripts/retry_caption_asr.py --start-ms S --end-ms E --duration-ms D --output OUT.json --video VIDEO` pads the span and re-transcribes only that span, writing absolute-time alternative segments for caption resolution. Without `--video` it writes only the padded span.
