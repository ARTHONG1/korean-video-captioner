"""Compatibility entry point: chunked transcription now lives in transcribe_faster_whisper.py.

Usage: transcribe_chunked.py VIDEO RUN_DIR [--chunk-ms N] [--overlap-ms N] [--profile auto|quality|balanced]
Writes RUN_DIR/raw.srt using the same resumable runner (plan_chunks, write_evidence, overlap-ms).
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def main() -> None:
    if len(sys.argv) < 3:
        raise SystemExit('usage: transcribe_chunked.py VIDEO RUN_DIR [options]')
    video, run, *rest = sys.argv[1:]
    script = Path(__file__).with_name('transcribe_faster_whisper.py')
    raw = Path(run) / 'raw.srt'
    raise SystemExit(subprocess.run([sys.executable, str(script), video, str(raw), *rest], env=os.environ.copy()).returncode)


if __name__ == '__main__':
    main()

