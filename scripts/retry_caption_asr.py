from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from kvc.caption_resolution import build_retry_span


def main() -> None:
    parser = argparse.ArgumentParser(description='Compute a padded retry span and, with --video, re-transcribe it')
    parser.add_argument("--start-ms", type=int, required=True)
    parser.add_argument("--end-ms", type=int, required=True)
    parser.add_argument("--duration-ms", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--video", type=Path, help="re-transcribe the span and store alternative segments in --output")
    parser.add_argument("--profile", choices=["auto", "quality", "balanced"], default="quality")
    args = parser.parse_args()
    start, end = build_retry_span(args.start_ms, args.end_ms, args.duration_ms)
    if not args.video:
        args.output.write_text(json.dumps({"start_ms": start, "end_ms": end}, indent=2), encoding="utf-8")
        return
    script = Path(__file__).with_name("retry_caption_asr_worker.py")
    command = [sys.executable, str(script), str(args.video), str(start), str(end), str(args.output), args.profile]
    raise SystemExit(subprocess.run(command, env=os.environ.copy()).returncode)


if __name__ == "__main__":
    main()

