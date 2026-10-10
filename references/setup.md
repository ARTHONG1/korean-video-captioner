# Setup on any computer

The Skill sets itself up. Before the first video job on a computer, and after updating the Skill, run:

```text
python3 scripts/setup.py doctor        # Windows: py -3 scripts\setup.py doctor  (or any python.exe)
```

Any Python 3.8+ can run `setup.py`; it uses only the standard library. Follow `next_actions` exactly:

- `who: agent` — run the command yourself (`install`, then `selftest`). Start `install` with `scripts/run_background.py` when the model still has to download, and report progress from its log.
- `who: user` — something only a person can do. Ask once, in one short sentence, then continue.

Never ask the user to type setup commands, and never skip `selftest`: a computer counts as ready only when `doctor` prints READY.

## What install does

| Step | macOS | Windows | Linux |
| --- | --- | --- | --- |
| Python 3.10–3.13 venv | an existing python3.10–3.13, else `uv` (installed for the user, no admin) downloads Python 3.12 | an existing or `py -3.12` Python, else `uv` | as macOS |
| Packages | `runtime-requirements/requirements.txt` (exact), else `requirements-compatible.txt`; Apple Silicon also gets `mlx-whisper` | same | same |
| FFmpeg (needs `ass`, `subtitles`, `libx264`, version 7+) | Homebrew `brew install ffmpeg` | BtbN GPL build, SHA-256 checked against the release checksum file | BtbN GPL build |
| Whisper large-v3 | Hugging Face cache (about 3 GB); Apple Silicon also caches the MLX copy | same | same |
| Profile | copies `assets/profile-examples` into the profile folder if empty | same | same |

User actions you may need: installing Homebrew on a Mac without it (needs the Mac password), freeing disk space (7 GB), closing apps when free memory is under 2.5 GB, and allowing Terminal/Codex access to Documents, Desktop, Downloads, or Movies when macOS asks.

## Folders

`doctor` prints them. Defaults: macOS `~/Library/Application Support/korean-video-captioner/{runtime,profile,brand-packs}`, Windows `%LOCALAPPDATA%\korean-video-captioner\...`, Linux `~/.local/share/korean-video-captioner/...`. Older installs under `~/Documents/Codex/tools` keep being used. Override with `KVC_RUNTIME_ROOT`, `KVC_PROFILE_DIR`, `KVC_BRAND_PACK_ROOT`, or `KVC_HOME`.

## What selftest proves

It makes a 40-second video with Korean speech from the system voice (macOS `say` with a ko_KR voice, Windows SAPI ko-KR), then runs caption rendering, the layout gate, compact editing, and the intro join, and transcribes the speech. On Apple Silicon it runs both engines on the same speech and selects `mlx` only when its text matches the script at least as well (within 0.05) and it is at least 1.2x faster; the choice is written to `runtime/engine.json` and used by `--engine auto`. Without a Korean system voice the CPU engine stays selected. Results: `runtime/selftest.json`.

## Running long jobs on a Mac

Start transcription and full renders with `scripts/run_background.py --log LOG -- COMMAND...`. It lowers the priority, keeps the Mac awake (`caffeinate`) until the job ends, and returns immediately. Recommend the power adapter for long videos. Match Korean file names with `kvc.hostenv.find_file` (macOS stores names decomposed).

## Distributing the Skill

`python scripts/build_release.py --out DIST` copies the Skill without caches or personal data and writes a ZIP plus `RELEASE-MANIFEST.json`. Personal files (glossary, publish profile, brand packs, runtime) live outside the Skill and are never included. A recipient unzips the folder into their skills directory (`~/.codex/skills/korean-video-captioner`) and asks the agent to set it up.
